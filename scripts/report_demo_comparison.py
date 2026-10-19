"""Verify an existing capacity experiment and export aggregate-only evidence.

Run from the project root with `python -m scripts.report_demo_comparison`.
This does not run Docker or MATSim, change simulation outputs, or overwrite an
existing report. Production run records remain authoritative for job status.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from wrapper.analyze import compute_summary_data
from wrapper.ifline import compare_summaries, resolve_run_assets
from wrapper.provenance import PROJECT_ROOT, OUTPUT_DIR, sha256_file, utc_now


def _xml_value(element):
    return (element.tag, sorted(element.attrib.items()), (element.text or "").strip(),
            [_xml_value(child) for child in element])


def _config(path: Path):
    root = ET.parse(path).getroot()
    # Only the changed network and separate output destination may differ.
    for module in root.findall("module"):
        for param in module.findall("param"):
            pair = (module.get("name"), param.get("name"))
            if pair in {("network", "inputNetworkFile"), ("controler", "outputDirectory")}:
                param.set("value", "<run-specific>")
    return _xml_value(root)


def _network(path: Path):
    root = ET.parse(path).getroot()
    nodes = {node.get("id"): _xml_value(node) for node in root.find("nodes")}
    links = {link.get("id"): link for link in root.find("links")}
    return nodes, links


def verify_capacity_change(baseline_path: Path, proposal_path: Path, spec: dict) -> dict:
    if spec.get("type") != "capacity_scale" or not 1 <= float(spec["value"]) <= 300:
        raise ValueError("This report verifies capacity-scale experiments only")
    base_nodes, base_links = _network(baseline_path)
    alt_nodes, alt_links = _network(proposal_path)
    if base_nodes != alt_nodes or set(base_links) != set(alt_links):
        raise ValueError("Capacity-only experiment unexpectedly changed network topology")
    selected = base_links[spec["link_id"]]
    expected = {spec["link_id"]}
    if spec.get("include_reverse"):
        expected.update(key for key, link in base_links.items()
                        if link.get("from") == selected.get("to")
                        and link.get("to") == selected.get("from")
                        and "car" in link.get("modes", "").split(","))
    changes = []
    for key, before in base_links.items():
        after = alt_links[key]
        if key in expected:
            base_capacity = float(before.get("capacity"))
            alt_capacity = float(after.get("capacity"))
            if not math.isclose(alt_capacity, base_capacity * float(spec["value"]) / 100):
                raise ValueError("Capacity change does not match the recorded intervention")
            changes.append({"link_id": key, "before_capacity": base_capacity,
                            "after_capacity": alt_capacity})
            after.set("capacity", before.get("capacity"))
        if _xml_value(before) != _xml_value(after):
            raise ValueError(f"Unexpected non-capacity network change on link {key}")
    return {"nodes": len(base_nodes), "directed_links": len(base_links), "changes": changes}


# These diagnostics were added in summary schema v2. Old records may omit them,
# but their original numerical claims must still equal a fresh recomputation.
_ADDED_QUALITY_FIELDS = {"time_valid_count", "distance_valid_count", "data_quality",
                         "baseline_time_valid_count", "proposal_time_valid_count",
                         "baseline_distance_valid_count", "proposal_distance_valid_count"}


def recorded_comparison_matches(recorded, current):
    if isinstance(current, dict):
        return isinstance(recorded, dict) and all(
            (key not in recorded and key in _ADDED_QUALITY_FIELDS)
            or (key in recorded and recorded_comparison_matches(recorded[key], value))
            for key, value in current.items())
    if isinstance(current, list):
        return isinstance(recorded, list) and len(recorded) == len(current) and all(
            recorded_comparison_matches(a, b) for a, b in zip(recorded, current))
    return recorded == current


def build_evidence(baseline_run: str, proposal_run: str) -> dict:
    baseline = resolve_run_assets(baseline_run)
    proposal = resolve_run_assets(proposal_run)
    for assets in (baseline, proposal):
        if not assets["record"].get("verification", {}).get("passed"):
            raise ValueError("A run did not pass artifact verification")
        log = (assets["sim_dir"] / "logfile.log").read_text(errors="replace").lower()
        if "shutdown completed" not in log or "unexpectedly terminated" in log:
            raise ValueError("MATSim did not shut down cleanly")
    config = proposal["record"]["configuration"]
    if config.get("baseline_run") != baseline_run:
        raise ValueError("Proposal belongs to a different baseline")
    spec = config["intervention"]
    if baseline["plans_file"].resolve() != proposal["plans_file"].resolve():
        raise ValueError("Runs do not reuse the same input plans")
    plans_hash = sha256_file(baseline["plans_file"])
    if plans_hash != proposal["record"]["inputs"]["baseline_plans"]["sha256"]:
        raise ValueError("Plans changed after the proposal input snapshot")
    config_paths = [OUTPUT_DIR / f"{name}_config/config.xml" for name in (baseline_run, proposal_run)]
    if _config(config_paths[0]) != _config(config_paths[1]):
        raise ValueError("Simulation configuration differs beyond network/output paths")
    network = verify_capacity_change(baseline["network_file"], proposal["network_file"], spec)
    summaries = [compute_summary_data(name) for name in (baseline_run, proposal_run)]
    if summaries[0]["num_iterations"] != summaries[1]["num_iterations"]:
        raise ValueError("Executed iteration counts do not match")
    comparison = compare_summaries(*summaries)
    comparison_path = OUTPUT_DIR / "ifline" / proposal["run_id"] / "comparison.json"
    recorded = json.loads(comparison_path.read_text())
    if not recorded_comparison_matches(recorded, comparison):
        raise ValueError("Recorded comparison does not match the current raw trip outputs")
    files = [baseline["record_path"], proposal["record_path"], comparison_path,
             baseline["plans_file"], baseline["network_file"], proposal["network_file"], *config_paths]
    for assets in (baseline, proposal):
        files.extend(assets["sim_dir"] / name for name in (
            "output_events.xml.gz", "output_trips.csv.gz", "output_persons.csv.gz", "scorestats.txt"))
    fingerprints = {str(path.relative_to(PROJECT_ROOT)): sha256_file(path) for path in files}
    runtime_sources = [path for path in (PROJECT_ROOT / "wrapper").rglob("*")
                       if path.is_file() and path.suffix in {".py", ".js", ".html", ".css"}]
    runtime_sources += list((PROJECT_ROOT / "docker").glob("*.Dockerfile"))
    runtime_sources += [PROJECT_ROOT / "requirements.txt", PROJECT_ROOT / "start.command"]
    return {
        "created_at": utc_now(),
        "scope": "Local small-CBD single-seed capacity stress test; not a calibrated forecast",
        "baseline_run": baseline_run, "proposal_run": proposal_run,
        "intervention": spec, "network": network,
        "controls": {"same_plans_sha256": plans_hash,
                     "config_equal_except_network_and_output": True,
                     "matsim_seed": baseline["matsim_seed"],
                     "executed_iterations": summaries[0]["num_iterations"]},
        "comparison": comparison,
        "run_times": {assets["run_name"]: {
            key: assets["record"].get(key) for key in ("started_at", "finished_at", "duration_seconds")
        } for assets in (baseline, proposal)},
        "run_code": {assets["run_name"]: assets["record"]["code"] for assets in (baseline, proposal)},
        "artifact_sha256": fingerprints,
        "runtime_source_sha256_at_verification": {
            str(path.relative_to(PROJECT_ROOT)): sha256_file(path) for path in sorted(runtime_sources)
        },
        "limitations": [
            "Existing local data, Python environment and Docker image caches were reused; no clean-machine reproduction.",
            "Single seed and three iterations do not establish convergence, significance or real-world impact.",
            "Synthetic agents, not real users; public transport is teleported, not a timetable/vehicle simulation.",
            "Counts and times come from recorded simulation output, not measured city traffic.",
            "Git baseline plus a dirty flag alone does not reconstruct all local source edits.",
        ],
    }


def _metric(value, signed=False):
    return "Unavailable" if value is None else format(value, "+.3f" if signed else ".3f")


def export_report(evidence: dict, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    comparison = evidence["comparison"]
    rows = comparison["mode_changes"]
    with (destination / "mode_comparison.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    base, alt, delta = (comparison[key] for key in ("baseline", "proposal", "delta"))
    lines = ["# CBD capacity stress test — verified local comparison", "",
             "This is an aggregate-only technical demonstration, not a policy recommendation.", "",
             f"Baseline: `{evidence['baseline_run']}`", f"Proposal: `{evidence['proposal_run']}`", "",
             "| Metric | Baseline | Proposal | Difference |", "| --- | ---: | ---: | ---: |",
             f"| Synthetic agents | {base['person_count']} | {alt['person_count']} | {alt['person_count'] - base['person_count']:+d} |",
             f"| Recorded trips | {base['total_trips']} | {alt['total_trips']} | {delta['trip_count']:+d} |",
             f"| Mean trip time (s) | {_metric(base['avg_trip_time_seconds'], False)} | {_metric(alt['avg_trip_time_seconds'], False)} | {_metric(delta['avg_trip_time_seconds'], True)} |",
             f"| Mean trip distance (m) | {_metric(base['avg_trip_distance_m'], False)} | {_metric(alt['avg_trip_distance_m'], False)} | {_metric(delta['avg_trip_distance_m'], True)} |",
             "", "## Mode-level travel time", "",
             "| Mode | Baseline mean (s) | Proposal mean (s) | Difference (s) |",
             "| --- | ---: | ---: | ---: |"]
    for row in rows:
        lines.append(f"| {row['mode']} | {_metric(row['baseline_avg_time_seconds'], False)} | {_metric(row['proposal_avg_time_seconds'], False)} | {_metric(row['avg_time_delta_seconds'], True)} |")
    lines.extend(["", "## Evidence and limits", "",
                  "Input-plan hash, configuration equality, actual network changes and artifact hashes are in `evidence.json`.",
                  "Means use each metric's valid count; missing/invalid measurements are excluded, never zero-filled. Counts and quality diagnostics are in evidence.json.",
                  "The CSV retains numerical precision; displayed tables round for readability.", ""])
    lines.extend(f"- {item}" for item in evidence["limitations"])
    (destination / "README.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    evidence = build_evidence(args.baseline, args.proposal)
    export_report(evidence, args.destination)
    print(f"Verified aggregate report: {args.destination}")


if __name__ == "__main__":
    main()
