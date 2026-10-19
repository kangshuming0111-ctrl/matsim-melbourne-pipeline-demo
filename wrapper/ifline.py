"""Auditable counterfactual branches built from completed MATSim runs.

An IF Line branch keeps the baseline demand, random seed and iteration count
fixed, changes a small, explicit part of the network, then runs MATSim into a
new output directory.  It is an early option-screening experiment, not a claim
of causal or long-term land-use prediction.
"""

from __future__ import annotations

import gzip
import json
import math
import re
import statistics
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from wrapper.analyze import compute_summary_data, summarize
from wrapper.baseline_runner import run as run_simulation
from wrapper.jobs import set_stage
from wrapper.provenance import RunRecorder, file_evidence
from wrapper.runs import list_runs, validate_run_name
from wrapper.skyline import _network_data, _parse_events, render_skyline_scene

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
IFLINE_DIR = OUTPUT_DIR / "ifline"
SAFE_LINK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")
INTERVENTION_TYPES = {"speed_limit", "capacity_scale", "road_closure", "new_road"}
NEW_ROAD_MODES = ("car", "bike", "walk")
MAX_NEW_ROAD_POINTS = 32
MAX_NEW_ROAD_LENGTH_M = 25_000.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_scenario_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"if_{stamp}_{uuid.uuid4().hex[:6]}"


def _safe_project_output(relative: str, *, expected_suffix: str) -> Path:
    path = (PROJECT_ROOT / relative).resolve()
    output_root = OUTPUT_DIR.resolve()
    if path != output_root and output_root not in path.parents:
        raise ValueError("Run record points outside output/")
    if not path.name.endswith(expected_suffix):
        raise ValueError(f"Run record does not identify a {expected_suffix} directory")
    return path


def _record_for_sim(run_name: str) -> dict[str, Any]:
    base_id = run_name[:-4] if run_name.endswith("_sim") else run_name
    path = OUTPUT_DIR / "run_records" / base_id / "run_manifest.json"
    if not path.is_file():
        raise FileNotFoundError("IF Line requires a completed run with an audit record")
    try:
        record = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError("Baseline run record is not valid JSON") from exc
    if record.get("status") != "completed":
        raise ValueError("Baseline run is not marked completed")
    return record


def resolve_run_assets(run_name: str) -> dict[str, Any]:
    """Resolve reusable network/demand assets from a completed run record."""
    run_name = validate_run_name(run_name)
    if not run_name.endswith("_sim"):
        raise ValueError("Baseline must identify a completed *_sim result")
    sim_dir = OUTPUT_DIR / run_name
    if not sim_dir.is_dir():
        raise FileNotFoundError(f"Baseline result '{run_name}' does not exist")
    record = _record_for_sim(run_name)
    outputs = record.get("outputs", {})
    base_id = run_name[:-4]
    network_dir = _safe_project_output(
        outputs.get("network", f"output/{base_id}_network"), expected_suffix="_network"
    )
    demand_dir = _safe_project_output(
        outputs.get("demand", f"output/{base_id}_demand"), expected_suffix="_demand"
    )
    network_file = network_dir / "network.xml"
    plans_file = demand_dir / "8.xml" / "plan.xml"
    for label, path in (("network", network_file), ("plans", plans_file)):
        if not path.is_file():
            raise FileNotFoundError(f"Baseline {label} file is missing")
    configuration = record.get("configuration", {})
    seeds = record.get("random_seeds", {})
    return {
        "run_name": run_name,
        "run_id": record.get("run_id", base_id),
        "record": record,
        "record_path": OUTPUT_DIR / "run_records" / base_id / "run_manifest.json",
        "sim_dir": sim_dir,
        "network_dir": network_dir,
        "network_file": network_file,
        "demand_dir": demand_dir,
        "plans_file": plans_file,
        "region_key": configuration.get("region_key"),
        "last_iteration": int(configuration.get("matsim_last_iteration", 2)),
        "matsim_seed": int(seeds.get("matsim", 4711)),
        "demand_seed": seeds.get("demand"),
    }


def available_baselines(limit: int = 50) -> list[dict[str, Any]]:
    """Completed, recorded runs whose network and demand can be reused."""
    baselines = []
    for run in list_runs(limit=limit):
        if run.get("status") != "completed" or not run.get("has_run_record"):
            continue
        try:
            assets = resolve_run_assets(run["id"])
        except (ValueError, FileNotFoundError, OSError, TypeError):
            continue
        record = assets["record"]
        parent = record.get("configuration", {}).get("baseline_run")
        baselines.append({
            "id": run["id"],
            "run_id": assets["run_id"],
            "label": run["label"],
            "region_key": assets["region_key"],
            "profile_id": record.get("profile", {}).get("id"),
            "is_ifline": bool(parent),
            "parent_run": parent,
        })
    return baselines


def list_scenarios(limit: int = 50) -> list[dict[str, Any]]:
    """Small branch catalogue for the UI; full evidence stays in scenario.json."""
    if not IFLINE_DIR.is_dir():
        return []
    rows = []
    paths = sorted(
        IFLINE_DIR.glob("*/scenario.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in paths[:max(1, min(limit, 200))]:
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        comparison = data.get("comparison") or {}
        rows.append({
            "scenario_id": data.get("scenario_id"),
            "name": data.get("name"),
            "status": data.get("status"),
            "baseline_run": data.get("baseline_run"),
            "created_at": data.get("created_at"),
            "finished_at": data.get("finished_at"),
            "intervention": data.get("intervention"),
            "delta": comparison.get("delta"),
            "proposal_run": comparison.get("proposal_run"),
        })
    return rows


def _event_volumes(sim_dir: Path) -> dict[str, int]:
    volumes: dict[str, int] = {}
    with gzip.open(sim_dir / "output_events.xml.gz", "rt") as stream:
        for _, elem in ET.iterparse(stream, events=("end",)):
            if elem.tag == "event" and elem.get("type") == "entered link":
                link_id = elem.get("link")
                if link_id:
                    volumes[link_id] = volumes.get(link_id, 0) + 1
            elem.clear()
    return volumes


def _network_tree(path: Path) -> tuple[ET.ElementTree, ET.Element, dict[str, tuple[float, float]]]:
    tree = ET.parse(path)
    root = tree.getroot()
    nodes_element = root.find("nodes")
    links_element = root.find("links")
    if nodes_element is None or links_element is None:
        raise ValueError("Not a MATSim network_v2 document")
    nodes = {
        node.get("id", ""): (float(node.get("x", "0")), float(node.get("y", "0")))
        for node in nodes_element.findall("node")
    }
    return tree, links_element, nodes


def network_map(run_name: str) -> dict[str, Any]:
    """Compact network geometry and mode metadata for the browser picker.

    The 3D scene renders every MATSim link.  Returning only car links made more
    than half of the visible lines silently unresponsive in the CBD network.
    Keep every link identifiable here and mark whether the current motor-road
    interventions can act on it; the UI can then select and explain a walk or
    bike path instead of pretending the click missed.
    """
    assets = resolve_run_assets(run_name)
    _, links_element, nodes = _network_tree(assets["network_file"])
    volumes = _event_volumes(assets["sim_dir"])
    links = []
    for link in links_element.findall("link"):
        modes = {mode.strip() for mode in (link.get("modes") or "").split(",") if mode.strip()}
        from_id, to_id = link.get("from"), link.get("to")
        if from_id not in nodes or to_id not in nodes:
            continue
        x1, y1 = nodes[from_id]
        x2, y2 = nodes[to_id]
        road_type = "road"
        attributes = link.find("attributes")
        if attributes is not None:
            for attribute in attributes.findall("attribute"):
                if attribute.get("name") == "type" and attribute.text:
                    road_type = attribute.text
                    break
        links.append({
            "id": link.get("id"),
            "from": from_id,
            "to": to_id,
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "length_m": round(float(link.get("length", "0")), 1),
            "speed_kph": round(float(link.get("freespeed", "0")) * 3.6, 1),
            "capacity": round(float(link.get("capacity", "0")), 1),
            "lanes": round(float(link.get("permlanes", "1")), 1),
            "modes": sorted(modes),
            "car_editable": "car" in modes,
            "road_type": road_type,
            "volume": volumes.get(link.get("id", ""), 0),
        })
    if not links:
        raise ValueError("Baseline network contains no links")
    xs = [coordinate for link in links for coordinate in (link["x1"], link["x2"])]
    ys = [coordinate for link in links for coordinate in (link["y1"], link["y2"])]
    return {
        "run_name": run_name,
        "bounds": {"min_x": min(xs), "max_x": max(xs), "min_y": min(ys), "max_y": max(ys)},
        "links": links,
    }


def validate_intervention(intervention: dict[str, Any]) -> dict[str, Any]:
    kind = str(intervention.get("type", ""))
    if kind == 'plan':
        from wrapper.planning import validate_plan
        return {**validate_plan(intervention), 'check_token':intervention.get('check_token'),
                'acknowledge_conflicts':intervention.get('acknowledge_conflicts') is True}
    if kind not in INTERVENTION_TYPES:
        raise ValueError(f"Unsupported intervention type: {kind!r}")

    if kind == "new_road":
        raw_points = intervention.get("points")
        if not isinstance(raw_points, list) or not 2 <= len(raw_points) <= MAX_NEW_ROAD_POINTS:
            raise ValueError(
                f"New road requires 2 to {MAX_NEW_ROAD_POINTS} coordinate points"
            )
        points: list[list[float]] = []
        for index, raw_point in enumerate(raw_points):
            if not isinstance(raw_point, (list, tuple)) or len(raw_point) != 2:
                raise ValueError(f"New road point {index + 1} must contain x and y")
            try:
                x, y = float(raw_point[0]), float(raw_point[1])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"New road point {index + 1} must be numeric") from exc
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError(f"New road point {index + 1} must be finite")
            points.append([x, y])

        raw_length = sum(
            math.hypot(b[0] - a[0], b[1] - a[1])
            for a, b in zip(points, points[1:])
        )
        if raw_length < 5:
            raise ValueError("New road must be at least 5 metres long")
        if raw_length > MAX_NEW_ROAD_LENGTH_M:
            raise ValueError(
                f"New road cannot exceed {MAX_NEW_ROAD_LENGTH_M / 1000:g} km"
            )

        def finite_number(field: str, label: str, minimum: float, maximum: float) -> float:
            try:
                number = float(intervention.get(field))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{label} requires a numeric value") from exc
            if not math.isfinite(number) or not minimum <= number <= maximum:
                raise ValueError(f"{label} must be between {minimum:g} and {maximum:g}")
            return number

        speed_kph = finite_number("speed_kph", "New road speed", 5, 130)
        lanes = finite_number("lanes", "New road lanes per direction", 1, 8)
        capacity = finite_number("capacity_per_hour", "New road capacity", 100, 20_000)
        snap_tolerance = finite_number("snap_tolerance_m", "Node snap tolerance", 5, 500)

        raw_modes = intervention.get("modes") or list(NEW_ROAD_MODES)
        if not isinstance(raw_modes, list):
            raise ValueError("New road modes must be a list")
        modes = [mode for mode in NEW_ROAD_MODES if mode in {str(item) for item in raw_modes}]
        if "car" not in modes:
            raise ValueError("New road must support car mode for this experiment")

        return {
            "type": kind,
            "points": points,
            "speed_kph": speed_kph,
            "lanes": lanes,
            "capacity_per_hour": capacity,
            "bidirectional": bool(intervention.get("bidirectional", True)),
            "snap_tolerance_m": snap_tolerance,
            "modes": modes,
        }

    link_id = str(intervention.get("link_id", ""))
    if not SAFE_LINK_ID.fullmatch(link_id) or ".." in link_id:
        raise ValueError("Invalid link ID")
    value = intervention.get("value")
    if kind == "speed_limit":
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Speed limit requires a numeric value") from exc
        if not math.isfinite(value):
            raise ValueError("Speed limit requires a finite numeric value")
        if not 5 <= value <= 130:
            raise ValueError("Speed limit must be between 5 and 130 km/h")
    elif kind == "capacity_scale":
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Capacity requires a numeric percentage") from exc
        if not math.isfinite(value):
            raise ValueError("Capacity requires a finite numeric percentage")
        if not 1 <= value <= 300:
            raise ValueError("Capacity must be between 1% and 300% of baseline")
    else:
        value = None
    return {
        "type": kind,
        "link_id": link_id,
        "value": value,
        "include_reverse": bool(intervention.get("include_reverse", True)),
    }


def _write_network(tree: ET.ElementTree, target_network: Path) -> None:
    target_network.parent.mkdir(parents=True, exist_ok=False)
    ET.indent(tree, space="  ")
    xml = ET.tostring(tree.getroot(), encoding="unicode")
    temporary = target_network.with_suffix(".tmp")
    temporary.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v2.dtd">\n'
        + xml
        + "\n"
    )
    temporary.replace(target_network)


def _apply_new_road(
    tree: ET.ElementTree,
    links_element: ET.Element,
    nodes: dict[str, tuple[float, float]],
    target_network: Path,
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    """Insert a connected polyline into a MATSim network.

    Every endpoint must snap to an existing node. Intermediate clicks also
    snap when close enough; otherwise they become explicit new geometry
    nodes. This makes the topology auditable and avoids a visually touching
    line that MATSim cannot actually route through.
    """
    root = tree.getroot()
    nodes_element = root.find("nodes")
    if nodes_element is None:
        raise ValueError("Not a MATSim network_v2 document")

    xs = [point[0] for point in nodes.values()]
    ys = [point[1] for point in nodes.values()]
    boundary_pad = max(1_000.0, spec["snap_tolerance_m"] * 2)
    for x, y in spec["points"]:
        if not (
            min(xs) - boundary_pad <= x <= max(xs) + boundary_pad
            and min(ys) - boundary_pad <= y <= max(ys) + boundary_pad
        ):
            raise ValueError("New road contains a point outside the editable network area")

    existing_node_ids = set(nodes)
    existing_link_ids = {link.get("id", "") for link in links_element.findall("link")}
    suffix = 1
    while (
        f"ifline_new_{suffix}_n1" in existing_node_ids
        or f"ifline_new_{suffix}_f1" in existing_link_ids
    ):
        suffix += 1
    prefix = f"ifline_new_{suffix}"

    node_items = list(nodes.items())
    resolved: list[dict[str, Any]] = []
    created_node_count = 0
    for index, (x, y) in enumerate(spec["points"]):
        nearest_id, nearest_xy = min(
            node_items,
            key=lambda item: (item[1][0] - x) ** 2 + (item[1][1] - y) ** 2,
        )
        distance = math.hypot(nearest_xy[0] - x, nearest_xy[1] - y)
        endpoint = index in (0, len(spec["points"]) - 1)
        if endpoint and distance > spec["snap_tolerance_m"]:
            side = "start" if index == 0 else "end"
            raise ValueError(
                f"New road {side} is {distance:.1f} m from the nearest network node; "
                f"maximum snap distance is {spec['snap_tolerance_m']:.1f} m"
            )
        if distance <= spec["snap_tolerance_m"]:
            node_id = nearest_id
            resolved_point = {
                "node_id": node_id,
                "x": nearest_xy[0],
                "y": nearest_xy[1],
                "snapped": True,
                "snap_distance_m": round(distance, 3),
            }
        else:
            created_node_count += 1
            node_id = f"{prefix}_n{created_node_count}"
            ET.SubElement(nodes_element, "node", {
                "id": node_id,
                "x": f"{x:.6f}",
                "y": f"{y:.6f}",
            })
            existing_node_ids.add(node_id)
            resolved_point = {
                "node_id": node_id,
                "x": x,
                "y": y,
                "snapped": False,
                "snap_distance_m": None,
            }
        if resolved and resolved[-1]["node_id"] == node_id:
            continue
        resolved.append(resolved_point)

    if len(resolved) < 2:
        raise ValueError("New road collapses to one network node after snapping")

    segment_lengths = [
        math.hypot(b["x"] - a["x"], b["y"] - a["y"])
        for a, b in zip(resolved, resolved[1:])
    ]
    if any(length < 2 for length in segment_lengths):
        raise ValueError("New road contains a segment shorter than 2 metres after snapping")
    total_length = sum(segment_lengths)
    if total_length > MAX_NEW_ROAD_LENGTH_M:
        raise ValueError(
            f"New road cannot exceed {MAX_NEW_ROAD_LENGTH_M / 1000:g} km after snapping"
        )

    modes = ",".join(spec["modes"])
    changed: list[dict[str, Any]] = []

    def add_link(link_id: str, start: dict[str, Any], end: dict[str, Any], length: float) -> None:
        link = ET.SubElement(links_element, "link", {
            "id": link_id,
            "from": start["node_id"],
            "to": end["node_id"],
            "length": f"{length:.6f}",
            "capacity": f"{spec['capacity_per_hour']:.6f}",
            "freespeed": f"{spec['speed_kph'] / 3.6:.12g}",
            "permlanes": f"{spec['lanes']:.6f}",
            "oneway": "1",
            "modes": modes,
        })
        attributes = ET.SubElement(link, "attributes")
        attribute = ET.SubElement(attributes, "attribute", {
            "name": "type",
            "class": "java.lang.String",
        })
        attribute.text = "ifline_new_road"
        changed.append({
            "action": "added",
            "link_id": link_id,
            "from": start["node_id"],
            "to": end["node_id"],
            "before": None,
            "after": {
                "freespeed_mps": spec["speed_kph"] / 3.6,
                "speed_kph": spec["speed_kph"],
                "capacity": spec["capacity_per_hour"],
                "lanes": spec["lanes"],
                "length_m": length,
                "modes": modes,
            },
        })

    for index, (start, end, length) in enumerate(
            zip(resolved, resolved[1:], segment_lengths), start=1):
        add_link(f"{prefix}_f{index}", start, end, length)
        if spec["bidirectional"]:
            add_link(f"{prefix}_r{index}", end, start, length)

    for row in changed:
        row["road_summary"] = {
            "total_length_m": round(total_length, 3),
            "created_nodes": created_node_count,
            "resolved_points": resolved,
        }
    _write_network(tree, target_network)
    return changed


def apply_network_intervention(
    source_network: Path,
    target_network: Path,
    intervention: dict[str, Any],
) -> list[dict[str, Any]]:
    """Apply one explicit intervention and return an auditable before/after diff."""
    spec = validate_intervention(intervention)
    tree, links_element, nodes = _network_tree(source_network)
    if spec["type"] == "new_road":
        return _apply_new_road(tree, links_element, nodes, target_network, spec)
    links_by_id = {link.get("id", ""): link for link in links_element.findall("link")}
    selected = links_by_id.get(spec["link_id"])
    if selected is None:
        raise ValueError(f"Link '{spec['link_id']}' does not exist in the baseline network")
    selected_modes = {item.strip() for item in (selected.get("modes") or "").split(",") if item.strip()}
    if "car" not in selected_modes:
        raise ValueError("Selected link is not open to cars in the baseline")

    selected_ids = [spec["link_id"]]
    if spec["include_reverse"]:
        from_id, to_id = selected.get("from"), selected.get("to")
        for candidate in links_element.findall("link"):
            candidate_id = candidate.get("id", "")
            if candidate_id != spec["link_id"] and candidate.get("from") == to_id and candidate.get("to") == from_id:
                candidate_modes = {
                    item.strip() for item in (candidate.get("modes") or "").split(",") if item.strip()
                }
                if "car" in candidate_modes:
                    selected_ids.append(candidate_id)

    changed = []
    for link_id in selected_ids:
        link = links_by_id[link_id]
        before = {
            "freespeed_mps": float(link.get("freespeed", "0")),
            "speed_kph": float(link.get("freespeed", "0")) * 3.6,
            "capacity": float(link.get("capacity", "0")),
            "modes": link.get("modes", ""),
        }
        if spec["type"] == "speed_limit":
            link.set("freespeed", f"{spec['value'] / 3.6:.12g}")
        elif spec["type"] == "capacity_scale":
            link.set("capacity", f"{before['capacity'] * spec['value'] / 100.0:.12g}")
        elif spec["type"] == "road_closure":
            modes = [item.strip() for item in before["modes"].split(",") if item.strip() != "car"]
            link.set("modes", ",".join(modes))
        after = {
            "freespeed_mps": float(link.get("freespeed", "0")),
            "speed_kph": float(link.get("freespeed", "0")) * 3.6,
            "capacity": float(link.get("capacity", "0")),
            "modes": link.get("modes", ""),
        }
        changed.append({
            "link_id": link_id,
            "from": link.get("from"),
            "to": link.get("to"),
            "before": before,
            "after": after,
        })

    _write_network(tree, target_network)
    return changed


def _valid_count(row: dict, field: str) -> int:
    quality = "time_quality" if field == "avg_time_seconds" else "distance_quality"
    # Older recorded summaries have no per-metric counts. Retain their original weighting.
    if row.get(field) is None:
        return 0
    return row.get(quality, {}).get("valid", row.get("count", 0))


def _overall_average(summary: dict[str, Any], field: str) -> float | None:
    rows = summary["mode_rows"]
    count = sum(_valid_count(row, field) for row in rows)
    if not count:
        return None
    return sum(_valid_count(row, field) * row[field] for row in rows if _valid_count(row, field)) / count


def _difference(baseline: float | None, proposal: float | None) -> float | None:
    return None if baseline is None or proposal is None else proposal - baseline


def _relative_delta_percent(baseline: float | None, proposal: float | None) -> float | None:
    """Unavailable measurements and zero bases do not define a percentage."""
    if baseline is None or proposal is None or abs(baseline) < 1e-12:
        return None
    return ((proposal - baseline) / abs(baseline)) * 100


def compare_summaries(baseline: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    base_modes = {row["mode"]: row for row in baseline["mode_rows"]}
    proposal_modes = {row["mode"]: row for row in proposal["mode_rows"]}
    mode_changes = []
    for mode in sorted(set(base_modes) | set(proposal_modes)):
        base = base_modes.get(mode, {})
        alt = proposal_modes.get(mode, {})
        base_share = float(base.get("share", 0))
        alt_share = float(alt.get("share", 0))
        base_count = int(base.get("count", 0))
        alt_count = int(alt.get("count", 0))
        base_time = base.get("avg_time_seconds")
        alt_time = alt.get("avg_time_seconds")
        base_distance = base.get("avg_distance_m")
        alt_distance = alt.get("avg_distance_m")
        mode_changes.append({
            "mode": mode,
            "baseline_count": base_count,
            "proposal_count": alt_count,
            "count_delta": alt_count - base_count,
            "baseline_share": base_share,
            "proposal_share": alt_share,
            "share_delta_points": (alt_share - base_share) * 100,
            "baseline_avg_time_seconds": base_time,
            "proposal_avg_time_seconds": alt_time,
            "avg_time_delta_seconds": _difference(base_time, alt_time),
            "baseline_time_valid_count": _valid_count(base, "avg_time_seconds"),
            "proposal_time_valid_count": _valid_count(alt, "avg_time_seconds"),
            "baseline_distance_valid_count": _valid_count(base, "avg_distance_m"),
            "proposal_distance_valid_count": _valid_count(alt, "avg_distance_m"),
            "avg_time_delta_percent": _relative_delta_percent(base_time, alt_time),
            "baseline_avg_distance_m": base_distance,
            "proposal_avg_distance_m": alt_distance,
            "avg_distance_delta_m": _difference(base_distance, alt_distance),
        })
    baseline_avg_time = _overall_average(baseline, "avg_time_seconds")
    proposal_avg_time = _overall_average(proposal, "avg_time_seconds")
    baseline_avg_distance = _overall_average(baseline, "avg_distance_m")
    proposal_avg_distance = _overall_average(proposal, "avg_distance_m")
    return {
        "baseline": {
            "run_name": baseline["sim_output_subdir"],
            "time_valid_count": sum(_valid_count(row, "avg_time_seconds") for row in baseline["mode_rows"]),
            "distance_valid_count": sum(_valid_count(row, "avg_distance_m") for row in baseline["mode_rows"]),
            "data_quality": baseline.get("data_quality"),
            "person_count": baseline["person_count"],
            "total_trips": baseline["total_trips"],
            "avg_trip_time_seconds": baseline_avg_time,
            "avg_trip_distance_m": baseline_avg_distance,
            "last_score": baseline["last_score"],
        },
        "proposal": {
            "run_name": proposal["sim_output_subdir"],
            "time_valid_count": sum(_valid_count(row, "avg_time_seconds") for row in proposal["mode_rows"]),
            "distance_valid_count": sum(_valid_count(row, "avg_distance_m") for row in proposal["mode_rows"]),
            "data_quality": proposal.get("data_quality"),
            "person_count": proposal["person_count"],
            "total_trips": proposal["total_trips"],
            "avg_trip_time_seconds": proposal_avg_time,
            "avg_trip_distance_m": proposal_avg_distance,
            "last_score": proposal["last_score"],
        },
        "delta": {
            "avg_trip_time_seconds": _difference(baseline_avg_time, proposal_avg_time),
            "avg_trip_time_percent": _relative_delta_percent(baseline_avg_time, proposal_avg_time),
            "avg_trip_distance_m": _difference(baseline_avg_distance, proposal_avg_distance),
            "avg_trip_distance_percent": _relative_delta_percent(
                baseline_avg_distance, proposal_avg_distance
            ),
            "last_score": proposal["last_score"] - baseline["last_score"],
            "trip_count": proposal["total_trips"] - baseline["total_trips"],
        },
        "mode_changes": mode_changes,
        "interpretation": (
            "Counterfactual difference under the recorded model assumptions; "
            "not a calibrated forecast or long-term development prediction."
        ),
    }


def _delay_by_link(sim_dir: Path) -> tuple[dict[str, float], dict[str, int]]:
    volumes, travel_times = _parse_events(sim_dir)
    _, links = _network_data(sim_dir)
    delay = {}
    for link_id, times in travel_times.items():
        link = links.get(link_id)
        if not link or not times or link["freespeed"] <= 0:
            continue
        freeflow = link["length"] / link["freespeed"]
        delay[link_id] = max(0.0, statistics.mean(times) - freeflow)
    return delay, volumes


def render_difference_scene(
    baseline_sim_dir: Path,
    proposal_sim_dir: Path,
    changed_link_ids: set[str],
    incomparable_link_ids: set[str] | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Re-colour the proposal scene by delay change and retain raw deltas."""
    scene_path = proposal_sim_dir / "skyline_scene.json"
    scene = json.loads(scene_path.read_text())
    baseline_delay, baseline_volumes = _delay_by_link(baseline_sim_dir)
    proposal_delay, proposal_volumes = _delay_by_link(proposal_sim_dir)
    delay_deltas = {
        link_id: proposal_delay.get(link_id, 0.0) - baseline_delay.get(link_id, 0.0)
        for link_id in (set(baseline_delay) & set(proposal_delay)) - (incomparable_link_ids or set())
    }
    # One second is a display tolerance, not a significance test. Keep a
    # fixed 60-second saturation across scenarios, never auto-amplify noise.
    scale = 60.0
    neutral = (0.48, 0.52, 0.56)
    better = (0.08, 0.62, 0.48)
    worse = (0.84, 0.20, 0.18)
    intervention_color = (0.12, 0.47, 0.95)
    changed_road_deltas = []
    for road in scene.get("roads", []):
        link_id = str(road.get("link_id", ""))
        delay_delta = delay_deltas.get(link_id, 0.0)
        volume_delta = proposal_volumes.get(link_id, 0) - baseline_volumes.get(link_id, 0)
        strength = min(1.0, abs(delay_delta) / scale) if abs(delay_delta) >= 1.0 else 0.0
        if link_id in changed_link_ids:
            color = intervention_color
            road["glow"] = 0.48
        elif strength:
            target = worse if delay_delta > 0 else better
            color = tuple(neutral[i] + (target[i] - neutral[i]) * (0.25 + 0.75 * strength) for i in range(3))
            road["glow"] = round(0.08 + 0.28 * strength, 2)
        else:
            color = neutral
            road["glow"] = 0.0
        road["color"] = [round(channel, 3) for channel in color]
        road["delay_delta_seconds"] = round(delay_delta, 3) if link_id in delay_deltas else None
        road['delay_comparable'] = link_id in delay_deltas
        road["volume_delta"] = volume_delta
        if abs(delay_delta) >= 1.0:
            changed_road_deltas.append({
                "link_id": link_id,
                "delay_delta_seconds": round(delay_delta, 3),
                "volume_delta": volume_delta,
            })
    changed_road_deltas.sort(key=lambda row: abs(row["delay_delta_seconds"]), reverse=True)
    less_delay = [row for row in changed_road_deltas if row["delay_delta_seconds"] < 0]
    more_delay = [row for row in changed_road_deltas if row["delay_delta_seconds"] > 0]
    scene["ifline"] = {
        "display_mode": "delay_difference",
        "color_scale_version": 2,
        "color_scale_seconds": 60,
        "neutral_tolerance_seconds": 1,
        "baseline_sim": baseline_sim_dir.name,
        "proposal_sim": proposal_sim_dir.name,
        "changed_link_ids": sorted(changed_link_ids),
        "legend": {
            "better": "less average link delay than baseline",
            "neutral": "no material measured delay change",
            "worse": "more average link delay than baseline",
            "intervention": "directly changed or newly added link",
        },
    }
    difference_path = proposal_sim_dir / "ifline_scene.json"
    difference_path.write_text(json.dumps(scene))
    link_summary = {
        "links_with_material_delay_change": len(changed_road_deltas),
        "links_with_less_delay": len(less_delay),
        "links_with_more_delay": len(more_delay),
        "mean_absolute_delay_change_seconds": round(
            statistics.mean(abs(row["delay_delta_seconds"]) for row in changed_road_deltas), 3
        ) if changed_road_deltas else 0.0,
        "largest_delay_reduction_seconds": round(
            abs(min((row["delay_delta_seconds"] for row in less_delay), default=0.0)), 3
        ),
        "largest_delay_increase_seconds": round(
            max((row["delay_delta_seconds"] for row in more_delay), default=0.0), 3
        ),
        "largest_changes": changed_road_deltas[:12],
        "delay_scale_seconds": round(scale, 3),
        "comparison_note": "仅比较两次均有观测且几何未拆分的路段；新建、拆分或缺少一侧观测不计入路段延误增减。全网出行指标仍单独比较。",
    }
    return difference_path, link_summary


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    temporary.replace(path)


def _scenario_label(name: str) -> str:
    cleaned = " ".join(name.strip().split())
    if not 2 <= len(cleaned) <= 80 or any(ord(char) < 32 for char in cleaned):
        raise ValueError("Scenario name must contain 2 to 80 visible characters")
    return cleaned


def run_ifline_scenario(
    baseline_run: str,
    scenario_name: str,
    intervention: dict[str, Any],
    *,
    scenario_id: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Create, execute, compare and record one counterfactual branch."""
    assets = resolve_run_assets(baseline_run)
    label = _scenario_label(scenario_name)
    spec = validate_intervention(intervention)
    scenario_id = scenario_id or new_scenario_id()
    plan_tree = None
    plan_report = None
    if spec['type'] == 'plan':
        from wrapper.planning import check_plan
        plan_tree, plan_report = check_plan(baseline_run, spec)
        if spec.get('check_token') != plan_report['token']:
            raise ValueError('方案或基线已变化，请重新检查后再运行')
        if plan_report['conflicts'] and not spec['acknowledge_conflicts']:
            raise ValueError('请先确认建筑/用地冲突风险')
    validate_run_name(scenario_id)
    scenario_dir = IFLINE_DIR / scenario_id
    scenario_file = scenario_dir / "scenario.json"
    target_network_dir = OUTPUT_DIR / f"{scenario_id}_network"
    target_network = target_network_dir / "network.xml"
    proposal_sim_name = f"{scenario_id}_sim"
    proposal_sim_dir = OUTPUT_DIR / proposal_sim_name

    scenario_data: dict[str, Any] = {
        "schema_version": 1,
        "scenario_id": scenario_id,
        "name": label,
        "status": "running",
        "created_at": utc_now(),
        "finished_at": None,
        "baseline_run": baseline_run,
        "intervention": spec,
        "changed_links": [],
        "controls": {
            "same_demand_file": True,
            "demand_seed": assets["demand_seed"],
            "matsim_seed": assets["matsim_seed"],
            "last_iteration": assets["last_iteration"],
        },
        "outputs": {
            "network": f"output/{target_network_dir.name}",
            "demand": f"output/{assets['demand_dir'].name}",
            "demand_reused_from": f"output/{assets['demand_dir'].name}",
            "simulation": f"output/{proposal_sim_name}",
            "comparison": f"output/ifline/{scenario_id}/comparison.json",
        },
        "comparison": None,
        "plan_check": plan_report,
        "error": None,
    }
    if scenario_dir.exists() or target_network_dir.exists() or proposal_sim_dir.exists():
        raise FileExistsError(f"Scenario output '{scenario_id}' already exists")
    scenario_dir.mkdir(parents=True)
    _write_json_atomic(scenario_file, scenario_data)

    record = RunRecorder(
        scenario_id,
        job_id=job_id,
        profile={
            "id": "ifline_v1",
            "label": f"IF · {label}",
            "validation_status": "experimental_counterfactual",
        },
        configuration={
            "region_key": assets["region_key"],
            "baseline_run": baseline_run,
            "scenario_name": label,
            "intervention": spec,
            "matsim_first_iteration": 0,
            "matsim_last_iteration": assets["last_iteration"],
            "comparison_design": "same demand plans and MATSim random seed",
        },
        inputs={
            "baseline_run_record": file_evidence(assets["record_path"], checksum=True),
            "baseline_network": file_evidence(assets["network_file"], checksum=True),
            "baseline_plans": file_evidence(assets["plans_file"], checksum=True),
        },
        outputs=scenario_data["outputs"],
        random_seeds={"demand": assets["demand_seed"], "matsim": assets["matsim_seed"]},
        logs={
            "pipeline": f"output/run_records/{scenario_id}/pipeline.log",
            "baseline_demand": (
                f"output/{assets['demand_dir'].name}/makeExamplePopulation.log"
            ),
            "simulation": f"output/{proposal_sim_name}/logfile.log",
            "simulation_console": f"output/process_logs/{proposal_sim_name}.log",
            "scenario": f"output/ifline/{scenario_id}/scenario.json",
        },
        output_dir=OUTPUT_DIR,
    )

    def stage(message: str) -> None:
        if job_id:
            set_stage(job_id, message)

    try:
        stage("正在创建 IF Line 路网分支…")
        record.stage("network_intervention", "running")
        if plan_tree is not None:
            _write_network(plan_tree, target_network)
            changed = plan_report['changed_links']
        else:
            changed = apply_network_intervention(assets["network_file"], target_network, spec)
        scenario_data["changed_links"] = changed
        _write_json_atomic(scenario_file, scenario_data)
        record.add_input("proposal_network", file_evidence(target_network, checksum=True))
        record.stage("network_intervention", "completed", f"Applied {len(changed)} directed link change(s)")

        stage("正在使用相同人口运行方案…")
        record.stage("proposal_simulation", "running")
        run_simulation(
            network_output_subdir=target_network_dir.name,
            demand_output_subdir=assets["demand_dir"].name,
            output_subdir=proposal_sim_name,
            last_iteration=assets["last_iteration"],
            random_seed=assets["matsim_seed"],
        )
        record.stage("proposal_simulation", "completed")

        stage("正在计算基线与方案差异…")
        record.stage("comparison", "running")
        summarize(proposal_sim_name)
        proposal_summary = compute_summary_data(proposal_sim_name)
        baseline_summary = compute_summary_data(baseline_run)
        render_skyline_scene(proposal_sim_name, region_key=assets["region_key"])
        difference_scene, link_summary = render_difference_scene(
            assets["sim_dir"], proposal_sim_dir, {row["link_id"] for row in changed},
            {row['link_id'] for row in changed if row.get('action')=='split'},
        )
        comparison = compare_summaries(baseline_summary, proposal_summary)
        comparison.update({
            "scenario_id": scenario_id,
            "scenario_name": label,
            "baseline_run": baseline_run,
            "proposal_run": proposal_sim_name,
            "intervention": spec,
            "changed_links": changed,
            "network_effects": link_summary,
            "plan_check": plan_report,
        })
        comparison_path = scenario_dir / "comparison.json"
        _write_json_atomic(comparison_path, comparison)
        scenario_data.update({
            "status": "completed",
            "finished_at": utc_now(),
            "comparison": comparison,
        })
        _write_json_atomic(scenario_file, scenario_data)

        required = {
            "proposal_network": file_evidence(target_network, checksum=True),
            "generated_config": file_evidence(OUTPUT_DIR / f"{proposal_sim_name}_config" / "config.xml", checksum=True),
            "events": file_evidence(proposal_sim_dir / "output_events.xml.gz"),
            "trips": file_evidence(proposal_sim_dir / "output_trips.csv.gz"),
            "persons": file_evidence(proposal_sim_dir / "output_persons.csv.gz"),
            "simulation_log": file_evidence(proposal_sim_dir / "logfile.log"),
            "summary": file_evidence(proposal_sim_dir / "summary.md"),
            "difference_scene": file_evidence(difference_scene),
            "comparison": file_evidence(comparison_path, checksum=True),
            "scenario": file_evidence(scenario_file, checksum=True),
        }
        missing = [key for key, item in required.items() if not item.get("exists") or item.get("size_bytes", 0) <= 0]
        if missing:
            raise RuntimeError("IF Line artifacts are missing or empty: " + ", ".join(missing))
        log_tail = (proposal_sim_dir / "logfile.log").read_text(errors="replace")[-20_000:].lower()
        if "shutdown completed" not in log_tail or "unexpectedly terminated" in log_tail:
            raise RuntimeError("Proposal MATSim run did not finish with a clean shutdown")
        record.set_artifacts(required)
        record.stage("comparison", "completed")
        record.complete({
            "passed": True,
            "checks": {
                "same_demand_file": True,
                "same_matsim_seed": True,
                "changed_directed_links": len(changed),
                "proposal_clean_shutdown": True,
                "required_artifacts_present": True,
            },
        })
        (proposal_sim_dir / "run_metadata.json").write_text(record.manifest_path.read_text())

        proposal_summary.update({
            "run_id": scenario_id,
            "result_source": "new_ifline_run",
            "profile_id": "ifline_v1",
            "validation_status": "experimental_counterfactual",
            "run_record_url": f"/results/run_records/{scenario_id}/run_manifest.json",
            "modestats_chart_url": f"/results/{proposal_sim_name}/modestats.png",
            "scorestats_chart_url": f"/results/{proposal_sim_name}/scorestats.png",
            "skyline_scene_url": f"/results/{proposal_sim_name}/ifline_scene.json",
            "ifline_scenario_url": f"/results/ifline/{scenario_id}/scenario.json",
            "ifline_comparison_url": f"/results/ifline/{scenario_id}/comparison.json",
            "ifline_comparison": comparison,
        })
        stage("IF Line 方案完成并通过产物核对")
        return proposal_summary
    except BaseException as exc:
        scenario_data.update({
            "status": "failed",
            "finished_at": utc_now(),
            "error": {
                "type": type(exc).__name__,
                "message": str(exc).replace(str(PROJECT_ROOT), "."),
            },
        })
        _write_json_atomic(scenario_file, scenario_data)
        record.fail(exc)
        stage("IF Line 方案失败；已保留审计记录")
        raise
