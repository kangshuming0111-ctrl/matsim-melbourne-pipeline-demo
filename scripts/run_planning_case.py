"""Prepare, then explicitly run a bounded, matched MATSim planning experiment.

No demand generation, route search, or simulation at import/prepare time. The
compiler owns plan semantics; this module owns case provenance and lifecycle.
"""
from __future__ import annotations

import argparse
import copy
import csv
import fcntl
import hashlib
import importlib
import json
import math
import re
import shutil
import statistics
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

from rasterio.warp import transform as project_coordinates
from shapely.geometry import LineString

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wrapper.analyze import compute_summary_data, summarize
from wrapper.baseline_runner import CONFIG_TEMPLATE, run as run_simulation
from wrapper.ifline import compare_summaries, resolve_run_assets, run_ifline_scenario
from wrapper.landmark_geometry import project_clip_areas
from wrapper.planning import building_conflicts, check_plan
from wrapper.provenance import RunRecorder, file_evidence, sha256_file
from wrapper.skyline import landmark_cache_path, render_skyline_scene

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
DEFAULT_SOURCE = "cbd_demo_20260926T050044Z_a805bd_sim"
DEFAULT_SEEDS = [4711, 4712, 4713]
CORRIDOR_COORDINATES = {"8844": [2496581.0, 2408829.0], "8954": [2496544.0, 2408715.0],
                        "8695": [2496731.0, 2408809.0], "9032": [2496648.0, 2408628.0]}
# Geometry-only visibility-path candidate around 6.5 m buffered known footprints.
# Predeclared before expanded-network simulation; see docs for method and limits.
DETOUR_POINTS = [
    [2496731.0, 2408809.0], [2496735.106633699, 2408811.376643512],
    [2496778.6986190155, 2408784.695861228], [2496798.399840286, 2408725.8270277665],
    [2496799.2763582594, 2408719.7452203017], [2496798.968636925, 2408713.6024208576],
    [2496797.486688741, 2408707.6396062113], [2496794.887687746, 2408702.070909949],
    [2496784.708316491, 2408688.0891451905], [2496752.1116703996, 2408646.908405306],
    [2496732.5895657004, 2408622.9497667626], [2496706.6411270313, 2408595.5579299913],
    [2496661.8552034562, 2408601.356219772], [2496648.0, 2408628.0],
]
STAGES = ("baseline", "closure", "alternative")
MAX_ATTEMPTS = 3
GEOGRAPHIC_CAVEAT = (
    "The inherited small CBD network may not cover the full SA1-based population/activity geography. "
    "This case proves the matched workflow on those fixed inputs, not a geographically validated CBD "
    "policy benefit. An expanded-network experiment must be prepared and assessed separately."
)
EXPANDED_CAVEAT = (
    "Expanded network, unchanged original synthetic population. Bounding-box inclusion alone does "
    "not prove connected routes, calibration, or policy benefit; construction conflicts remain separate."
)
LIMITATION = (
    "Fixed synthetic population and activity locations; conceptual option screening, "
    "not engineering approval, a calibrated forecast, or long-term development prediction. "
    "Seed ranges are descriptive, not confidence intervals or evidence of convergence."
)


def now():
    return datetime.now(timezone.utc).isoformat()


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2,
                       allow_nan=False) + "\n").encode()


def _new_json(path, value):
    with path.open("xb") as stream:
        stream.write(_json_bytes(value))


def _save_manifest(case_dir, manifest, filename="case_manifest.json"):
    # Only the lifecycle manifest is replaced. Inputs, checks and results are immutable.
    path = case_dir / filename
    temporary = case_dir / f".manifest_{uuid.uuid4().hex}.tmp"
    _new_json(temporary, manifest)
    temporary.replace(path)


def _read(path):
    return json.loads(path.read_text())


def _relative(path):
    return str(path.resolve().relative_to(ROOT.resolve()))


def _evidence(path):
    return {"path": _relative(path), "sha256": sha256_file(path)}


def _verify_file(item):
    path = (ROOT / item["path"]).resolve()
    if OUTPUT.resolve() not in path.parents:
        raise ValueError("Case evidence must remain inside output/")
    if not path.is_file() or sha256_file(path) != item["sha256"]:
        raise ValueError(f"Missing or changed case evidence: {item['path']}")
    return path


def _validate_controls(seeds, last_iteration):
    if (not isinstance(seeds, list) or not 1 <= len(seeds) <= 10
            or any(type(seed) is not int or not 1 <= seed <= 2**31 - 1 for seed in seeds)
            or len(set(seeds)) != len(seeds)):
        raise ValueError("Use 1–10 distinct integer seeds in [1, 2147483647]")
    if type(last_iteration) is not int or not 1 <= last_iteration <= 49:
        raise ValueError("last_iteration must be an integer in [1, 49] (2–50 total iterations)")


def _validate_case_id(case_id):
    if not isinstance(case_id, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,47}", case_id):
        raise ValueError("case_id must be 1–48 letters/digits/underscores, starting with a letter")


def _geographic_caveat(spec):
    return EXPANDED_CAVEAT if spec.get("scope") == "expanded_network_fixed_population" else GEOGRAPHIC_CAVEAT


def _fixed_plans(assets, alternative_route="straight"):
    """Resolve the one predeclared corridor and chord, using only network geometry."""
    if assets["record"]["configuration"].get("output_crs") != 7899:
        raise ValueError("This predeclared CBD case requires native metre coordinates EPSG:7899")
    tree = ET.parse(assets["network_file"])
    nodes = {node.attrib["id"]: [float(node.attrib["x"]), float(node.attrib["y"])]
             for node in tree.findall("nodes/node")}
    links = {link.attrib["id"]: dict(link.attrib) for link in tree.findall("links/link")}
    car_nodes = {link[end] for link in links.values() if "car" in link.get("modes", "").split(",")
                 for end in ("from", "to")}
    resolved = {}
    for original_id, xy in CORRIDOR_COORDINATES.items():
        candidates = [node_id for node_id in car_nodes if node_id in nodes
                      and math.dist(nodes[node_id], xy) <= 1.0]
        if len(candidates) != 1:
            raise ValueError(f"Original corridor node {original_id} needs exactly one car node within 1 m; found {len(candidates)}")
        resolved[original_id] = candidates[0]
    closure_ids = []
    for start, end in (("8844", "8954"), ("8954", "8844")):
        candidates = [key for key, link in links.items()
                      if (link.get("from"), link.get("to")) == (resolved[start], resolved[end])
                      and "car" in link.get("modes", "").split(",")]
        if len(candidates) != 1:
            raise ValueError("Original closure corridor needs one directed car link each way; ambiguous or split geometry requires review")
        closure_ids.append(candidates[0])
    alternative_ids = {resolved["8695"], resolved["9032"]}
    if any({link["from"], link["to"]} == alternative_ids for link in links.values()):
        raise ValueError("Predeclared alternative duplicates an existing direct link")
    if any(not math.isfinite(v) for key in resolved.values() for v in nodes[key]):
        raise ValueError("Non-finite native node coordinates")
    closure = {"type": "road_closure", "link_id": closure_ids[0], "include_reverse": True}
    if alternative_route not in ("straight", "detour"):
        raise ValueError("Alternative route must be straight or detour")
    points = copy.deepcopy(DETOUR_POINTS) if alternative_route == "detour" else [None, None]
    points[0], points[-1] = nodes[resolved["8695"]], nodes[resolved["9032"]]
    if alternative_route == "detour":
        for start, end in zip(points, points[1:]):
            segment = LineString([start, end])
            for link in links.values():
                if "car" not in link.get("modes", "").split(","):
                    continue
                a, b = nodes[link["from"]], nodes[link["to"]]
                length = math.dist(a, b)
                if not length or not segment.length:
                    raise ValueError("Zero-length road geometry in detour duplicate screening")
                alignment = abs((end[0]-start[0])*(b[0]-a[0]) + (end[1]-start[1])*(b[1]-a[1])) / (segment.length*length)
                if (alignment > math.cos(math.radians(20)) and
                        segment.intersection(LineString([a, b]).buffer(4.5, cap_style="flat")).length > 20):
                    raise ValueError(f"Detour follows existing car link {link['id']} within 4.5 m for over 20 m; review alignment")
    road = {"type": "new_road", "points": points,
            "heights": [0]*len(points), "snap_points": [False]*len(points), "snap_tolerance_m": 5,
            "speed_kph": 30, "lanes": 1, "capacity_per_hour": 900,
            "bidirectional": True, "modes": ["car", "bike", "walk"]}
    plans = {"closure": {"type": "plan", "operations": [closure]},
             "alternative": {"type": "plan", "operations": [closure, road]}}
    geometry = {"crs": "EPSG:7899", "coordinate_units": "metres",
                "closure_links": [links[key] for key in closure_ids],
                "nodes": {key: nodes[key] for key in sorted(resolved.values())},
                "original_reference_run": DEFAULT_SOURCE,
                "original_reference_nodes": CORRIDOR_COORDINATES,
                "resolved_node_ids": resolved,
                "node_match_tolerance_m": 1.0,
                "node_displacement_m": {original: math.dist(CORRIDOR_COORDINATES[original], nodes[current])
                                        for original, current in resolved.items()},
                "alternative_endpoint_nodes": [resolved["8695"], resolved["9032"]],
                "alternative_length_m": sum(math.dist(a, b) for a, b in zip(points, points[1:])),
                "alternative_route": alternative_route,
                "selection": ("Predeclared footprint detour: 9 m corridor plus 2 m side margin, geometry only; no traffic outcome search."
                              if alternative_route == "detour" else
                              "Predeclared eastern connecting chord; chosen from geometry, not simulation outcomes.")}
    return plans, geometry


def _check_signature(report):
    return {key: report[key] for key in
            ("plan", "changed_links", "roads", "conflicts", "building_data_available")}


def _detour_clearance(assets, report):
    scene = _read(assets["sim_dir"] / report["source_scene"])
    corridors = [{**road, "width_m": road["width_m"] + 4} for road in report["roads"]]
    conflicts, _ = building_conflicts(corridors, scene, report["plan"]["building_labels"])
    result = {"side_margin_m": 2, "screened_width_m": 13, "conflicts": conflicts,
              "known_building_features": len(scene["landmarks"]["buildings"]),
              "limitation": "Known planar footprints only; no assurance of complete coverage, ownership, utilities or engineering approval"}
    # The display scene can omit lower buildings. Never equate a browser cap
    # with complete source-footprint screening; bind the uncapped source too.
    omitted = scene.get("landmark_diagnostics", {}).get("buildings", {}).get("omitted_by_limit", 0)
    cache = landmark_cache_path(assets["region_key"])
    if not cache.is_file():
        if omitted:
            raise ValueError("Display omitted building footprints but the full building source is unavailable")
        return result
    source_bytes = cache.read_bytes()
    raw = json.loads(source_bytes)
    if not isinstance(raw.get("buildings"), list) or not raw["buildings"]:
        raise ValueError("Full building source has no usable building layer")
    points = [p[:2] for road in report["roads"] for segment in road["segments"] for p in segment]
    extent = raw.get("metadata", {}).get("bounds")
    if (not isinstance(extent, list) or len(extent) != 4
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in extent)
            or not -180 <= extent[0] < extent[1] <= 180 or not -90 <= extent[2] < extent[3] <= 90):
        raise ValueError("Full building source lacks a valid geographic cache extent")
    margin_ring = list(LineString(points).buffer(6.5).exterior.coords)
    lons, lats = project_coordinates("EPSG:7899", "EPSG:4326", *zip(*margin_ring))
    if any(not (extent[0] <= lon <= extent[1] and extent[2] <= lat <= extent[3])
           for lon, lat in zip(lons, lats)):
        raise ValueError("Detour plus margin is outside the full building cache extent")
    bounds = LineString(points).buffer(150).bounds
    parts, diagnostics = project_clip_areas(raw["buildings"], bounds, "EPSG:4326", "EPSG:7899")
    if diagnostics["invalid"]:
        raise ValueError("Full building source contains invalid footprints; cannot certify the detour screen")
    full_scene = {"coordinate_transform": {"scene_units_per_metre": 1, "center_x": 0, "center_y": 0},
                  "landmarks": {"buildings": [
                      {"points": list(polygon.exterior.coords),
                       "holes": [list(ring.coords) for ring in polygon.interiors],
                       "osm_id": entry.get("osm_id"), "name": entry.get("name", ""),
                       "height": entry.get("height", 3)} for entry, polygon, _ in parts]}}
    width9, _ = building_conflicts(report["roads"], full_scene, report["plan"]["building_labels"])
    width13, _ = building_conflicts(corridors, full_scene, report["plan"]["building_labels"])
    result["full_source_screen"] = {
        "source": {"path": _relative(cache), "sha256": hashlib.sha256(source_bytes).hexdigest()},
        "source_metadata": raw.get("metadata", {}), "local_bounds_m": list(bounds),
        "corridor_and_margin_inside_cache_extent": True,
        "diagnostics": diagnostics, "scene_omitted_by_limit": omitted,
        "corridor_conflicts": width9, "margin_conflicts": width13,
        "coverage": "All cached source footprints screened locally without the display cap; cache extent and missing OSM buildings remain limitations"}
    result["conflicts"] = list({hit["key"]: hit for hit in conflicts + width9 + width13}.values())
    return result


def _network_directory(directory):
    directory = Path(directory).resolve()
    if (OUTPUT.resolve() not in directory.parents or not directory.name.endswith("_network")
            or not (directory / "network.xml").is_file()):
        raise ValueError("Network override must be an existing output/<name>_network directory containing network.xml")
    return directory


def prepare_case(*, source_run=DEFAULT_SOURCE, seeds=None, last_iteration=9, case_id=None,
                 network_dir=None, alternative_route="straight"):
    seeds = list(DEFAULT_SEEDS) if seeds is None else seeds
    _validate_controls(seeds, last_iteration)
    if case_id is None:
        case_id = f"pc_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:6]}"
    _validate_case_id(case_id)
    case_dir = OUTPUT / "planning_cases" / case_id
    snapshot_network_dir = OUTPUT / f"{case_id}_inputs_network"
    demand_dir = OUTPUT / f"{case_id}_inputs_demand"
    for path in (case_dir, snapshot_network_dir, demand_dir):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite {path}")
    assets = resolve_run_assets(source_run)
    if network_dir is not None:
        override = _network_directory(network_dir)
        origin = assets["record"]["configuration"].get("network_override_origin")
        is_verified_origin = (origin and (ROOT / origin["path"]).resolve() == override / "network.xml"
                              and sha256_file(override / "network.xml") == origin["sha256"]
                              == sha256_file(assets["network_file"]))
        if override != assets["network_dir"].resolve() and not is_verified_origin:
            raise ValueError("Network override differs from the recorded source: first --bootstrap --network-dir, then --prepare --source-run <bootstrap_sim>")
    if not (assets["record"].get("verification") or {}).get("passed"):
        raise ValueError("Source run lacks successful verification")
    plans, geometry = _fixed_plans(assets, alternative_route)
    population_count = sum(1 for _, elem in ET.iterparse(assets["plans_file"], events=("end",))
                           if elem.tag == "person")
    if population_count <= 0:
        raise ValueError("Source plans have no synthetic persons")
    checks = {}
    for stage, plan in plans.items():
        _, report = check_plan(source_run, plan)
        if not report["building_data_available"]:
            raise ValueError("Building conflict evidence is unavailable")
        checks[stage] = report
        if stage == "alternative" and alternative_route == "detour":
            report["detour_clearance"] = _detour_clearance(assets, report)
        plans[stage] = report["plan"]
    closure_ids = {row["link_id"] for row in checks["closure"]["changed_links"]}
    if closure_ids != {row["id"] for row in geometry["closure_links"]}:
        raise ValueError("Compiler closure scope differs from the predeclared two links")
    source_evidence = {key: _evidence(assets[key]) for key in ("network_file", "plans_file", "record_path")}
    case_dir.mkdir(parents=True, exist_ok=False)
    manifest = {"schema_version": 1, "case_id": case_id, "status": "preparing",
                "prepared_at": None, "started_at": None, "finished_at": None,
                "error": None, "aggregate": None, "rows": [], "executions": []}
    _save_manifest(case_dir, manifest)
    try:
        snapshot_network_dir.mkdir(exist_ok=False)
        (demand_dir / "8.xml").mkdir(parents=True, exist_ok=False)
        snapshots = {}
        for key, target in (("network_file", snapshot_network_dir / "network.xml"),
                            ("plans_file", demand_dir / "8.xml" / "plan.xml")):
            with assets[key].open("rb") as source, target.open("xb") as destination:
                shutil.copyfileobj(source, destination)
            snapshots[key] = _evidence(target)
            if snapshots[key]["sha256"] != source_evidence[key]["sha256"]:
                raise ValueError("Source inputs changed during preparation")
        (case_dir / "checks").mkdir()
        (case_dir / "results").mkdir()
        check_files = {}
        for stage, report in checks.items():
            path = case_dir / "checks" / f"{stage}.json"
            _new_json(path, report)
            check_files[stage] = _evidence(path)
        if alternative_route == "detour" and (checks["alternative"]["conflicts"] or
                                               checks["alternative"]["detour_clearance"]["conflicts"]):
            raise ValueError("Detour has known building conflicts; diagnostics retained, no policy-example case prepared")
        spec = {"schema_version": 1, "case_id": case_id, "source_run": source_run,
                "prepared_at": now(), "seeds": seeds, "last_iteration": last_iteration,
                "total_iterations": last_iteration + 1, "max_attempts_per_stage": MAX_ATTEMPTS,
                "source_evidence": source_evidence, "inputs": snapshots,
                "population_count": population_count, "demand_seed": assets["demand_seed"],
                "region_key": assets["region_key"], "geometry": geometry,
                "scope": assets["record"]["configuration"].get("planning_scope", "original_small_network"),
                "plans": plans, "checks": check_files,
                "config_template_sha256": hashlib.sha256(CONFIG_TEMPLATE.encode()).hexdigest(),
                "conflict_count": {stage: len(report["conflicts"]) for stage, report in checks.items()},
                "limitations": LIMITATION,
                "controls": {"same_population_across_all_runs": True,
                             "same_initial_network_across_seeds": True,
                             "matched_matsim_seed_within_triple": True,
                             "branches_anchor_fresh_baseline": True,
                             "demand_regenerated": False}}
        _new_json(case_dir / "case_spec.json", spec)
        manifest.update(status="prepared", prepared_at=spec["prepared_at"],
                        spec_sha256=sha256_file(case_dir / "case_spec.json"),
                        rows=[{"seed": seed, "stages": {stage: {"attempts": []} for stage in STAGES}}
                              for seed in seeds])
        _save_manifest(case_dir, manifest)
        return case_dir
    except BaseException as exc:
        manifest.update(status="prepare_failed", finished_at=now(), error=str(exc))
        _save_manifest(case_dir, manifest)
        raise


def bootstrap_baseline(*, network_dir, source_run=DEFAULT_SOURCE, bootstrap_id=None):
    """One explicit fresh baseline on a generated network, reusing source plans.

    This action never launches any intervention or the later nine-run batch.
    Generation must be finished and the original corridor must resolve before
    consuming simulator time. The caller supplies the coverage agent's directory.
    """
    source = resolve_run_assets(source_run)
    if not (source["record"].get("verification") or {}).get("passed"):
        raise ValueError("Source population run did not pass verification")
    network_dir = _network_directory(network_dir)
    domain_manifest = network_dir.parent / "manifest.json"
    domain_evidence = None
    if domain_manifest.is_file():
        domain = _read(domain_manifest)
        if domain.get("status") != "completed":
            raise ValueError("Expanded-domain experiment is not completed")
        recorded_network = domain.get("artifacts", {}).get("expanded_network/network.xml", {})
        recorded_plans = domain.get("inputs", {}).get("plans", {})
        if (recorded_network.get("sha256") != sha256_file(network_dir / "network.xml")
                or recorded_plans.get("sha256") != sha256_file(source["plans_file"])):
            raise ValueError("Domain generation evidence does not match the network or fixed source plans")
        domain_evidence = _evidence(domain_manifest)
    log = network_dir / "makeMatsimNetwork.log"
    if not log.is_file() or "Finished generating the xml output" not in log.read_text(errors="replace")[-20000:]:
        raise ValueError("Network generation has not recorded XML completion")
    network = network_dir / "network.xml"
    tree = ET.parse(network)
    nodes = {node.get("id"): (float(node.get("x")), float(node.get("y")))
             for node in tree.findall("nodes/node")}
    if (tree.getroot().tag != "network" or not nodes or None in nodes or "" in nodes
            or len(nodes) != len(tree.findall("nodes/node"))
            or any(not math.isfinite(value) for xy in nodes.values() for value in xy)):
        raise ValueError("Generated network has invalid node coordinates")
    links = tree.findall("links/link")
    if not links:
        raise ValueError("Generated network contains no links")
    if any(not link.get("id") for link in links) or len({link.get("id") for link in links}) != len(links):
        raise ValueError("Generated network has missing or duplicate link IDs")
    for link in links:
        if link.get("from") not in nodes or link.get("to") not in nodes:
            raise ValueError("Generated link refers to a missing node")
        for key in ("length", "freespeed", "capacity", "permlanes"):
            value = float(link.get(key, "nan"))
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"Generated network contains invalid {key}")
    _, geometry = _fixed_plans({**source, "network_file": network})
    plans = ET.parse(source["plans_file"])
    population_count = len(plans.findall("person"))
    if not population_count:
        raise ValueError("Original plans contain no persons")
    xs, ys = zip(*nodes.values())
    bounds = (min(xs), max(xs), min(ys), max(ys))
    activities = plans.findall("person/plan/act") + plans.findall("person/plan/activity")
    positions = [(float(act.get("x")), float(act.get("y"))) for act in activities]
    outside = sum(not (math.isfinite(x) and math.isfinite(y)
                       and bounds[0] <= x <= bounds[1] and bounds[2] <= y <= bounds[3]) for x, y in positions)
    if not positions or outside:
        raise ValueError(f"Expanded network bounding box must contain every fixed activity; outside={outside}, activities={len(positions)}")
    bootstrap_id = bootstrap_id if bootstrap_id is not None else f"pcb_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:6]}"
    _validate_case_id(bootstrap_id)
    directory = OUTPUT / "planning_bootstraps" / bootstrap_id
    run_id = f"{bootstrap_id}_baseline"
    _unused_run_id(run_id)
    snapshot_network = OUTPUT / f"{bootstrap_id}_inputs_network"
    if snapshot_network.exists():
        raise FileExistsError(f"Refusing to overwrite {snapshot_network}")
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {"status": "preparing", "started_at": now(), "finished_at": None,
                "run_id": run_id, "source_run": source_run, "error": None, "result": None}
    _save_manifest(directory, manifest, "bootstrap_manifest.json")
    network_origin = _evidence(network)
    snapshot_network.mkdir(exist_ok=False)
    with network.open("rb") as original, (snapshot_network / "network.xml").open("xb") as frozen:
        shutil.copyfileobj(original, frozen)
    inputs = {"network_file": _evidence(snapshot_network / "network.xml"), "plans_file": _evidence(source["plans_file"])}
    if inputs["network_file"]["sha256"] != network_origin["sha256"]:
        raise ValueError("Expanded network changed while snapshotting")
    spec = {"schema_version": 1, "case_id": bootstrap_id, "source_run": source_run,
            "scope": "expanded_network_fixed_population",
            "network_override_origin": network_origin,
            "domain_experiment_manifest": domain_evidence,
            "region_key": source["region_key"], "demand_seed": source["demand_seed"],
            "population_count": population_count, "inputs": inputs, "last_iteration": 9,
            "total_iterations": 10, "seed": 4711, "geometry": geometry,
            "generation_log": _evidence(log), "controls": {"same_original_plans": True},
            "coverage": {"activity_count": len(positions), "outside_network_bbox": outside,
                         "limitation": "Bounding-box inclusion is not proof of connected route coverage"}}
    _new_json(directory / "bootstrap_spec.json", spec)
    manifest["status"] = "running"
    _save_manifest(directory, manifest, "bootstrap_manifest.json")
    try:
        summary = _baseline(spec, 4711, run_id)
        result = _result_evidence(spec, 4711, "baseline", run_id, summary, f"{run_id}_sim")
        _new_json(directory / "result.json", result)
        manifest.update(status="completed", finished_at=now(), result=_evidence(directory / "result.json"))
        _save_manifest(directory, manifest, "bootstrap_manifest.json")
        return f"{run_id}_sim"
    except BaseException as exc:
        manifest.update(status="interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed",
                        finished_at=now(), error=f"{type(exc).__name__}: {exc}")
        _save_manifest(directory, manifest, "bootstrap_manifest.json")
        raise


@contextmanager
def _case_lock(case_dir):
    with (case_dir / ".run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("This case is already running in another process") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _load_case(case_dir):
    manifest = _read(case_dir / "case_manifest.json")
    if sha256_file(case_dir / "case_spec.json") != manifest.get("spec_sha256"):
        raise ValueError("Case specification changed; prepare a new case")
    spec = _read(case_dir / "case_spec.json")
    _validate_case_id(spec["case_id"])
    if case_dir != (OUTPUT / "planning_cases" / spec["case_id"]).resolve():
        raise ValueError("Case directory does not match its recorded identity")
    _validate_controls(spec["seeds"], spec["last_iteration"])
    if spec["config_template_sha256"] != hashlib.sha256(CONFIG_TEMPLATE.encode()).hexdigest():
        raise ValueError("Simulation configuration template changed; prepare a new case")
    for section in ("inputs", "source_evidence", "checks"):
        for evidence in spec[section].values():
            _verify_file(evidence)
    for stage in ("closure", "alternative"):
        _, current = check_plan(spec["source_run"], spec["plans"][stage])
        prepared = _read(_verify_file(spec["checks"][stage]))
        if current["token"] != prepared["token"]:
            raise ValueError("Source plan/network/building evidence changed; prepare a new case")
        if prepared.get("detour_clearance"):
            clearance = _detour_clearance(resolve_run_assets(spec["source_run"]), current)
            if clearance != prepared["detour_clearance"]:
                raise ValueError("Detour clearance/source evidence changed or is incomplete; prepare a new case")
    if [row["seed"] for row in manifest["rows"]] != spec["seeds"]:
        raise ValueError("Manifest seeds differ from the case specification")
    return spec, manifest


def _unused_run_id(run_id):
    paths = [OUTPUT / f"{run_id}_{suffix}" for suffix in ("sim", "sim_config", "network")]
    paths += [OUTPUT / "run_records" / run_id, OUTPUT / "ifline" / run_id,
              OUTPUT / "process_logs" / f"{run_id}_sim.log"]
    for path in paths:
        if path.exists():
            raise FileExistsError(f"Refusing to reuse simulation artifacts: {path}")


def _verify_summary(summary, spec):
    if (summary["first_iteration"] != 0 or summary["last_iteration"] != spec["last_iteration"]
            or summary["num_iterations"] != spec["total_iterations"]):
        raise ValueError("Simulation did not complete every predeclared iteration")
    if summary["person_count"] != spec["population_count"] or summary["total_trips"] <= 0:
        raise ValueError("Output person count changed or no trips were recorded")
    with (OUTPUT / summary["sim_output_subdir"] / "scorestats.txt").open() as stream:
        iterations = [int(row["ITERATION"]) for row in csv.DictReader(stream, delimiter="\t")]
    if iterations != list(range(spec["total_iterations"])):
        raise ValueError("Score history contains missing, duplicated, or unordered iterations")


def _xml_shape(node):
    return (node.tag, sorted(node.attrib.items()), (node.text or "").strip(),
            [_xml_shape(child) for child in node])


def _config_fingerprint(assets, seed, spec):
    root = ET.parse(assets["sim_dir"] / "output_config.xml").getroot()
    expected = {("global", "randomSeed"): str(seed),
                ("controler", "firstIteration"): "0",
                ("controler", "lastIteration"): str(spec["last_iteration"]),
                ("plans", "inputPlansFile"): f"/app/output/{assets['demand_dir'].name}/8.xml/plan.xml",
                ("network", "inputNetworkFile"): f"/app/output/{assets['network_dir'].name}/network.xml",
                ("controler", "outputDirectory"): f"/app/output/{assets['run_name']}"}
    for (module, name), value in expected.items():
        matches = root.findall(f"module[@name='{module}']/param[@name='{name}']")
        if len(matches) != 1 or matches[0].get("value") != value:
            raise ValueError(f"Actual simulation control mismatch: {module}.{name}")
        if (module, name) in {("global", "randomSeed"), ("network", "inputNetworkFile"),
                              ("controler", "outputDirectory")}:
            matches[0].set("value", "<matched-run-specific>")
    return hashlib.sha256(_json_bytes(_xml_shape(root))).hexdigest()


def _optional_impact(baseline_run, proposal_run):
    try:
        impact = importlib.import_module("wrapper.impact")
    except ModuleNotFoundError as exc:
        if exc.name != "wrapper.impact":
            raise
        return {"available": False, "reason": "wrapper.impact is not installed; native comparisons retained"}
    # Do not mask a real analyzer error as an unavailable module or invented zero.
    return {"available": True, "source": "wrapper.impact.analyze_impact",
            "report": impact.analyze_impact(baseline_run, proposal_run, start_s=0,
                                             end_s=108000, mode="all")}


def _baseline(spec, seed, run_id):
    network = _verify_file(spec["inputs"]["network_file"])
    plans = _verify_file(spec["inputs"]["plans_file"])
    sim_name = f"{run_id}_sim"
    outputs = {"network": _relative(network.parent), "demand": _relative(plans.parent.parent),
               "simulation": f"output/{sim_name}",
               "simulation_config": f"output/{sim_name}_config/config.xml"}
    recorder = RunRecorder(
        run_id, job_id=None, output_dir=OUTPUT,
        profile={"id": "planning_case_v1", "label": "Planning case matched baseline",
                 "validation_status": "experimental_counterfactual"},
        configuration={"region_key": spec["region_key"], "output_crs": 7899,
                       "planning_case": spec["case_id"], "source_run": spec["source_run"],
                       "planning_scope": spec.get("scope", "original_small_network"),
                       "network_override_origin": spec.get("network_override_origin"),
                       "matsim_first_iteration": 0, "matsim_last_iteration": spec["last_iteration"],
                       "matsim_actual_iteration_count_expected": spec["total_iterations"]},
        inputs=copy.deepcopy(spec["inputs"]), outputs=outputs,
        random_seeds={"demand": spec["demand_seed"], "matsim": seed})
    try:
        recorder.stage("simulation", "running")
        run_simulation(network_output_subdir=network.parent.name,
                       demand_output_subdir=plans.parent.parent.name, output_subdir=sim_name,
                       last_iteration=spec["last_iteration"], random_seed=seed)
        recorder.stage("simulation", "completed")
        recorder.stage("analysis", "running")
        summarize(sim_name)
        render_skyline_scene(sim_name, region_key=spec["region_key"])
        summary = compute_summary_data(sim_name)
        _verify_summary(summary, spec)
        sim = OUTPUT / sim_name
        required = {name: file_evidence(sim / name, checksum=True) for name in
                    ("output_config.xml", "output_events.xml.gz", "output_trips.csv.gz",
                     "output_persons.csv.gz", "scorestats.txt", "summary.md", "skyline_scene.json", "logfile.log")}
        required["generated_config"] = file_evidence(OUTPUT / f"{sim_name}_config" / "config.xml", checksum=True)
        if any(not item.get("size_bytes", 0) for item in required.values()):
            raise ValueError("Fresh baseline has missing or empty required artifacts")
        tail = (sim / "logfile.log").read_text(errors="replace")[-20_000:].lower()
        if "shutdown completed" not in tail or "unexpectedly terminated" in tail:
            raise ValueError("Fresh baseline did not shut down cleanly")
        _config_fingerprint({"sim_dir": sim, "network_dir": network.parent,
                             "demand_dir": plans.parent.parent, "run_name": sim_name}, seed, spec)
        recorder.set_artifacts(required)
        recorder.stage("analysis", "completed")
        recorder.complete({"passed": True, "checks": {"matched_controls": True,
                           "all_iterations_present": True, "clean_shutdown": True}})
        _new_json(sim / "run_metadata.json", recorder.data)
        resolved = resolve_run_assets(sim_name)
        if (resolved["matsim_seed"], resolved["last_iteration"]) != (seed, spec["last_iteration"]):
            raise ValueError("Fresh baseline record does not resolve the matched controls")
        return summary
    except BaseException as exc:
        recorder.fail(exc)
        raise


def _branch(spec, baseline_run, stage, run_id, acknowledge):
    tree, report = check_plan(baseline_run, spec["plans"][stage])
    prepared = _read(_verify_file(spec["checks"][stage]))
    if _check_signature(report) != _check_signature(prepared):
        raise ValueError("Fresh baseline plan geometry or conflict diagnostics differ from preparation")
    if prepared.get("detour_clearance"):
        clearance = _detour_clearance(resolve_run_assets(baseline_run), report)
        if clearance["conflicts"] or clearance != prepared["detour_clearance"]:
            raise ValueError("Fresh baseline detour failed the frozen source/2 m footprint margin check")
    if report["conflicts"] and not acknowledge:
        raise ValueError("Conceptual conflicts require explicit acknowledgement")
    intervention = {**report["plan"], "check_token": report["token"],
                    "acknowledge_conflicts": acknowledge}
    summary = run_ifline_scenario(baseline_run, f"{spec['case_id']} {stage}", intervention,
                                 scenario_id=run_id)
    _verify_summary(summary, spec)
    actual = resolve_run_assets(f"{run_id}_sim")
    if _xml_shape(ET.parse(actual["network_file"]).getroot()) != _xml_shape(tree.getroot()):
        raise ValueError("Executed branch network differs from the checked plan")
    return summary


def _result_evidence(spec, seed, stage, run_id, summary, baseline_run):
    assets = resolve_run_assets(f"{run_id}_sim")
    if assets["matsim_seed"] != seed or assets["last_iteration"] != spec["last_iteration"]:
        raise ValueError("Completed stage has mismatched seed/iteration controls")
    if sha256_file(assets["plans_file"]) != spec["inputs"]["plans_file"]["sha256"]:
        raise ValueError("Completed stage used a different population")
    if stage == "baseline" and sha256_file(assets["network_file"]) != spec["inputs"]["network_file"]["sha256"]:
        raise ValueError("Fresh baseline used a different initial network")
    files = {"network": _evidence(assets["network_file"]), "plans": _evidence(assets["plans_file"]),
             "run_record": _evidence(assets["record_path"])}
    for name in ("output_config.xml", "output_trips.csv.gz", "output_persons.csv.gz", "scorestats.txt",
                 "output_events.xml.gz", "output_network.xml.gz", "run_metadata.json", "skyline_scene.json"):
        files[name] = _evidence(assets["sim_dir"] / name)
    files["generated_config"] = _evidence(OUTPUT / f"{run_id}_sim_config" / "config.xml")
    native = None
    impact = None
    if stage != "baseline":
        files["comparison"] = _evidence(OUTPUT / "ifline" / run_id / "comparison.json")
        native = _read(_verify_file(files["comparison"]))
        if native.get("baseline_run") != baseline_run or native.get("proposal_run") != f"{run_id}_sim":
            raise ValueError("Native comparison has the wrong baseline/proposal anchor")
        recomputed = compare_summaries(compute_summary_data(baseline_run), summary)
        if any(native.get(key) != value for key, value in recomputed.items()):
            raise ValueError("Native comparison differs from the actual summary outputs")
        impact = _optional_impact(baseline_run, f"{run_id}_sim")
    return {"seed": seed, "stage": stage, "run_id": run_id, "baseline_run": baseline_run,
            "summary": summary, "files": files, "controls": spec["controls"],
            "native_comparison": native, "impact": impact,
            "geographic_scope_caveat": _geographic_caveat(spec),
            "normalized_config_sha256": _config_fingerprint(assets, seed, spec),
            "source_network_sha256": spec["inputs"]["network_file"]["sha256"],
            "last_iteration": spec["last_iteration"]}


def _completed(stage):
    return next((attempt for attempt in reversed(stage["attempts"])
                 if attempt["status"] == "completed"), None)


def _descriptive_range(values):
    valid = [value for value in values if isinstance(value, (int, float))
             and not isinstance(value, bool) and math.isfinite(value)]
    return {"n": len(valid), "missing": len(values) - len(valid),
            "min": min(valid) if valid else None, "max": max(valid) if valid else None,
            "mean": statistics.mean(valid) if valid else None,
            "median": statistics.median(valid) if valid else None}


def _car_mean_delta(comparison):
    car = next((row for row in comparison["mode_changes"] if row["mode"] == "car"), None)
    if car is None or car.get("baseline_count", 0) <= 0 or car.get("proposal_count", 0) <= 0:
        return None
    return car["avg_time_delta_seconds"]


def aggregate_results(triples, expected_seeds, *, geographic_caveat=GEOGRAPHIC_CAVEAT):
    """Pair within seed first; use native comparisons, never subtract percentages."""
    rows = []
    for seed, summaries in triples:
        comparisons = {}
        for label, left, right in (("closure_vs_baseline", "baseline", "closure"),
                                   ("alternative_vs_baseline", "baseline", "alternative"),
                                   ("alternative_vs_closure", "closure", "alternative")):
            comparisons[label] = compare_summaries(summaries[left], summaries[right])
        rows.append({"seed": seed, "comparisons": comparisons})
    ranges = {}
    if rows:
        for label in rows[0]["comparisons"]:
            ranges[label] = {}
            for metric in rows[0]["comparisons"][label]["delta"]:
                values = [row["comparisons"][label]["delta"][metric] for row in rows]
                ranges[label][metric] = _descriptive_range(values)
            ranges[label]["car_mean_travel_time_s"] = _descriptive_range(
                [_car_mean_delta(row["comparisons"][label]) for row in rows])
    return {"schema_version": 1, "comparison_source": "wrapper.ifline.compare_summaries",
            "expected_seeds": expected_seeds, "completed_seeds": [row["seed"] for row in rows],
            "incomplete_seeds": [seed for seed in expected_seeds if seed not in {row['seed'] for row in rows}],
            "paired_results": rows, "descriptive_ranges": ranges, "limitations": LIMITATION,
            "metric_definitions": {"car_mean_travel_time_s": {
                "label": "全天汽车均耗时差", "unit": "seconds", "sign": "proposal minus baseline",
                "population_basis": "Full-population car-mode aggregate, not paired trips; both sides need positive car trip counts",
                "time_basis": "All rows in each run's native trip table; no departure-time window filter"}},
            "geographic_scope_caveat": geographic_caveat}


def _publish_aggregate(case_dir, spec, manifest):
    triples = []
    for row in manifest["rows"]:
        complete = {stage: _completed(row["stages"][stage]) for stage in STAGES}
        if all(complete.values()):
            summaries = {stage: _read(_verify_file(attempt["result"]))["summary"]
                         for stage, attempt in complete.items()}
            triples.append((row["seed"], summaries))
    aggregate = aggregate_results(triples, spec["seeds"], geographic_caveat=_geographic_caveat(spec))
    path = case_dir / f"aggregate_{uuid.uuid4().hex[:12]}.json"
    _new_json(path, aggregate)
    manifest["aggregate"] = _evidence(path)
    _save_manifest(case_dir, manifest)


def run_case(case_dir, *, acknowledge_conceptual_conflicts=False, resume=False):
    case_dir = Path(case_dir).resolve()
    if not case_dir.is_dir() or case_dir.parent != (OUTPUT / "planning_cases").resolve():
        raise ValueError("Prepare an existing case directory before --run")
    with _case_lock(case_dir):
        spec, manifest = _load_case(case_dir)
        if manifest["status"] == "completed":
            raise ValueError("Case already completed; its outputs will not be overwritten")
        if manifest["status"] != "prepared" and not resume:
            raise ValueError("Case has prior execution state; inspect it and use --resume explicitly")
        if manifest["status"] not in ("prepared", "running", "failed", "interrupted"):
            raise ValueError("Case preparation was incomplete; prepare a new case")
        if any(spec["conflict_count"].values()) and not acknowledge_conceptual_conflicts:
            raise ValueError("Building conflicts recorded; --acknowledge-conceptual-conflicts is required")
        # Verify every completed artifact before trusting it during recovery.
        for row in manifest["rows"]:
            for stage in row["stages"].values():
                completed = _completed(stage)
                if completed:
                    result = _read(_verify_file(completed["result"]))
                    for evidence in result["files"].values():
                        _verify_file(evidence)
                for attempt in stage["attempts"]:
                    if attempt["status"] == "running":
                        attempt.update(status="interrupted", finished_at=now(),
                                       error="Previous process ended without a terminal record; artifacts retained.")
        execution = {"started_at": now(), "finished_at": None,
                     "acknowledge_conceptual_conflicts": acknowledge_conceptual_conflicts,
                     "geographic_scope_caveat": _geographic_caveat(spec)}
        manifest["executions"].append(execution)
        manifest.update(status="running", started_at=manifest["started_at"] or now(), finished_at=None, error=None)
        _save_manifest(case_dir, manifest)
        active = None
        try:
            for row in manifest["rows"]:
                baseline_run = None
                for stage_name in STAGES:
                    stage = row["stages"][stage_name]
                    completed = _completed(stage)
                    if completed:
                        if stage_name == "baseline":
                            baseline_run = f"{completed['run_id']}_sim"
                        continue
                    if len(stage["attempts"]) >= MAX_ATTEMPTS:
                        raise ValueError("Bounded retry limit reached; retain this case and prepare a new one")
                    for evidence in spec["inputs"].values():
                        _verify_file(evidence)
                    run_id = f"{spec['case_id']}_s{row['seed']}_{stage_name}_a{len(stage['attempts']) + 1:02d}"
                    _unused_run_id(run_id)
                    active = {"run_id": run_id, "status": "running", "started_at": now(),
                              "finished_at": None, "result": None, "error": None}
                    stage["attempts"].append(active)
                    _save_manifest(case_dir, manifest)
                    print(f"{now()} seed={row['seed']} stage={stage_name} run={run_id}", flush=True)
                    if stage_name == "baseline":
                        summary = _baseline(spec, row["seed"], run_id)
                        baseline_run = f"{run_id}_sim"
                    else:
                        summary = _branch(spec, baseline_run, stage_name, run_id,
                                          acknowledge_conceptual_conflicts)
                    result = _result_evidence(spec, row["seed"], stage_name, run_id, summary, baseline_run)
                    fingerprint = result["normalized_config_sha256"]
                    if manifest.get("normalized_config_sha256", fingerprint) != fingerprint:
                        raise ValueError("Actual configs changed beyond matched seed/network/output controls")
                    manifest["normalized_config_sha256"] = fingerprint
                    result_path = case_dir / "results" / f"{run_id}.json"
                    _new_json(result_path, result)
                    active.update(status="completed", finished_at=now(), result=_evidence(result_path))
                    _save_manifest(case_dir, manifest)
                    active = None
                _publish_aggregate(case_dir, spec, manifest)
            execution["finished_at"] = now()
            manifest.update(status="completed", finished_at=now())
            _save_manifest(case_dir, manifest)
            return manifest
        except BaseException as exc:
            status = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed"
            if active is not None:
                active.update(status=status, finished_at=now(), error=f"{type(exc).__name__}: {exc}")
            execution["finished_at"] = now()
            manifest.update(status=status, finished_at=now(), error=f"{type(exc).__name__}: {exc}")
            _save_manifest(case_dir, manifest)
            _publish_aggregate(case_dir, spec, manifest)
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", action="store_true", help="Snapshot inputs and compile checks; no simulation")
    action.add_argument("--bootstrap", action="store_true", help="Explicitly run ONE recorded baseline on --network-dir, reusing source plans")
    action.add_argument("--run", type=Path, metavar="CASE_DIR", help="Explicitly execute a prepared case")
    parser.add_argument("--source-run", default=None)
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--network-dir", type=Path, default=None,
                        help="Expanded generated network; prepare requires a source run already recorded against this directory")
    parser.add_argument("--alternative-route", choices=("straight", "detour"), default=None,
                        help="Prepare-only predeclared geometry; detour requires zero known building conflicts")
    parser.add_argument("--seeds", nargs="+", type=int, default=None)
    parser.add_argument("--last-iteration", type=int, default=None)
    parser.add_argument("--acknowledge-conceptual-conflicts", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Retain completed stages; retry failed stages in new directories")
    args = parser.parse_args(argv)
    if not args.run and (args.resume or args.acknowledge_conceptual_conflicts):
        parser.error("Acknowledgement and --resume apply only to --run")
    if args.run and any(value is not None for value in (args.source_run, args.case_id, args.seeds, args.last_iteration, args.network_dir, args.alternative_route)):
        parser.error("Run controls are frozen; use prepare options to create a new case")
    if args.bootstrap and (args.network_dir is None or args.seeds is not None or args.last_iteration is not None or args.alternative_route is not None):
        parser.error("Bootstrap requires --network-dir and uses fixed seed 4711 / last_iteration 9")
    try:
        if args.prepare:
            case_dir = prepare_case(source_run=args.source_run or DEFAULT_SOURCE,
                                    seeds=args.seeds, last_iteration=args.last_iteration if args.last_iteration is not None else 9,
                                    case_id=args.case_id, network_dir=args.network_dir,
                                    alternative_route=args.alternative_route or "straight")
            spec = _read(case_dir / "case_spec.json")
            print(json.dumps({"case_dir": str(case_dir), "status": "prepared", "seeds": spec["seeds"],
                              "total_iterations": spec["total_iterations"], "conflict_count": spec["conflict_count"],
                              "geometry": spec["geometry"], "limitations": LIMITATION}, ensure_ascii=False, indent=2))
        elif args.bootstrap:
            run_name = bootstrap_baseline(network_dir=args.network_dir, source_run=args.source_run or DEFAULT_SOURCE,
                                          bootstrap_id=args.case_id)
            print(json.dumps({"status": "completed", "bootstrap_run": run_name,
                              "next_action": "--prepare --source-run " + run_name,
                              "interventions_launched": 0}, indent=2))
        else:
            result = run_case(args.run, acknowledge_conceptual_conflicts=args.acknowledge_conceptual_conflicts,
                              resume=args.resume)
            print(json.dumps({"status": result["status"], "aggregate": result["aggregate"]}, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, ET.ParseError) as exc:
        print(f"Planning case stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
