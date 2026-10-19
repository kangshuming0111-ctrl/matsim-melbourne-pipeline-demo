"""Generate a fresh network around the fixed CBD population; never run MATSim.

Run explicitly with --run. All generated data, scratch, logs and provenance live
in a new output/domain_experiments/<id>/ directory. No existing input is edited.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wrapper.coverage_audit import audit_coverage
from wrapper.docker_image import FINGERPRINT_LABEL, source_fingerprint
from wrapper.process_logging import announce, run_logged

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "cbd_demo_20260926T050044Z_a805bd"
PLANS_SHA256 = "3b886ede8f0d5fac1fb17bf3602d2b09d0ada3dd986f231c5a00d0bbffaf872c"
NETWORK_SHA256 = "a1c20f60224f892b7ef1adc9bcde585ba9f0b5b8a1f74b00514c5df2eaec7473"
EXPECTED_PERSONS = 1037
EXPECTED_ACTIVITIES = 4660
BUFFER_M = 500
CRS = 7899
IMAGE = "matsim-network-generator"

R_DRIVER = r'''
suppressPackageStartupMessages(library(sf))
suppressPackageStartupMessages(library(lwgeom))
suppressPackageStartupMessages(library(xml2))
suppressPackageStartupMessages(library(jsonlite))
packages <- c("sf", "lwgeom", "xml2", "jsonlite", "osmextract", "igraph", "data.table")
write_json(list(R = R.version.string, platform = R.version$platform,
                packages = setNames(lapply(packages, function(x) as.character(packageVersion(x))), packages),
                sf_external = as.list(sf_extSoftVersion())),
           "output/r_environment.json", auto_unbox = TRUE, pretty = TRUE)
doc <- read_xml("/source/plans.xml")
persons <- xml_find_all(doc, "/population/person")
stopifnot(length(persons) == 1037L)
stopifnot(all(vapply(persons, function(p) {
  length(xml_find_all(p, "./plan[@selected='yes']")) == 1L
}, logical(1))))
acts <- xml_find_all(doc, "/population/person/plan[@selected='yes']/*[self::activity or self::act]")
xy <- data.frame(x = as.numeric(xml_attr(acts, "x")), y = as.numeric(xml_attr(acts, "y")))
stopifnot(nrow(xy) == 4660L, all(is.finite(as.matrix(xy))))
locations <- st_as_sf(xy, coords = c("x", "y"), crs = 7899)
region <- st_sf(geometry = st_as_sfc(st_bbox(locations)))
buffered <- lwgeom::st_snap_to_grid(st_buffer(region, 500), 1)
bb <- st_bbox(buffered)
stopifnot(all(st_is_valid(buffered)), as.numeric(st_area(buffered)) < 25000000)
write_json(list(crs = 7899L, buffer_m = 500L, snap_grid_m = 1L,
                unbuffered_area_km2 = as.numeric(st_area(region)) / 1e6,
                buffered_area_km2 = as.numeric(st_area(buffered)) / 1e6,
                buffered_width_km = unname(bb["xmax"] - bb["xmin"]) / 1000,
                buffered_height_km = unname(bb["ymax"] - bb["ymin"]) / 1000,
                activities_outside_extraction_polygon = sum(lengths(st_intersects(locations, buffered)) == 0L)),
           "output/domain_summary.json", auto_unbox = TRUE, pretty = TRUE)
region_file <- Sys.getenv("NETWORK_REGION")
stopifnot(!file.exists(region_file))
st_write(region, region_file, layer = "activity_bbox", quiet = TRUE)
# Copy the original PBF because osmextract creates/deletes a GPKG beside it.
pbf <- Sys.getenv("NETWORK_OSM_PBF")
stopifnot(!file.exists(pbf))
stopifnot(file.copy("/app/data/geofabrik_victoria-latest.osm.pbf", pbf, overwrite = FALSE))
out <- file.path("output", Sys.getenv("NETWORK_OUTPUT_SUBDIR"))
stopifnot(!dir.exists(out))
source("NetworkGenerator.R")
makeNetwork(Sys.getenv("NETWORK_CITY"), Sys.getenv("NETWORK_OUTPUT_SUBDIR"))
stopifnot(file.exists(file.path(out, "network.xml")), file.exists(file.path(out, "network.sqlite")))
'''


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence(path):
    return {"path": str(Path(path).resolve()), "size_bytes": Path(path).stat().st_size,
            "sha256": _hash(path)}


def _new_json(path, data):
    with Path(path).open("x") as stream:
        json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def _save_manifest(directory, manifest):
    # Only the experiment's own lifecycle file is atomically replaced.
    temporary = directory / f".manifest_{uuid.uuid4().hex}.json"
    _new_json(temporary, manifest)
    temporary.replace(directory / "manifest.json")


def _capture_json(command):
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _cached_environment(root):
    inspected = _capture_json(["docker", "image", "inspect", IMAGE])[0]
    fingerprint = source_fingerprint([root / "docker/network.Dockerfile", root / "vendor/network"])
    labels = inspected.get("Config", {}).get("Labels") or {}
    if labels.get(FINGERPRINT_LABEL) != fingerprint:
        raise ValueError("Cached R image does not match source; no automatic rebuild or installation permitted.")
    info = _capture_json(["docker", "info", "--format", "{{json .}}"])
    return {
        "python": platform.python_version(), "platform": platform.platform(),
        "packages": {name: importlib.metadata.version(name) for name in ("shapely", "rasterio")},
        "image_id": inspected["Id"], "image_created": inspected.get("Created"),
        "image_architecture": inspected.get("Architecture"), "source_fingerprint": fingerprint,
        "image_platform": f"{inspected['Os']}/{inspected['Architecture']}"
                          + (f"/{inspected['Variant']}" if inspected.get("Variant") else ""),
        "docker": {key: info.get(key) for key in ("ServerVersion", "NCPU", "MemTotal", "Architecture")},
    }


def _validate_plans(path):
    if _hash(path) != PLANS_SHA256:
        raise ValueError("Source plans differ from the fixed baseline SHA-256.")
    root = ET.parse(path).getroot()
    persons = root.findall("person")
    points = []
    for person in persons:
        selected = person.findall("plan[@selected='yes']")
        if len(selected) != 1:
            raise ValueError("Fixed source requires exactly one selected plan per person.")
        for act in selected[0]:
            if act.tag in ("act", "activity"):
                point = tuple(float(act.attrib[axis]) for axis in ("x", "y"))
                if not all(math.isfinite(value) for value in point):
                    raise ValueError("Fixed source has nonfinite activity coordinates.")
                points.append(point)
    if len(persons) != EXPECTED_PERSONS or len(points) != EXPECTED_ACTIVITIES:
        raise ValueError("Fixed source population/activity counts have changed.")
    width = max(x for x, _ in points) - min(x for x, _ in points)
    height = max(y for _, y in points) - min(y for _, y in points)
    area = width * height + 2 * BUFFER_M * (width + height) + math.pi * BUFFER_M**2
    if area > 25_000_000:
        raise ValueError("Proposed buffered activity envelope exceeds the bounded 25 km2 scope.")
    return {"persons": len(persons), "activities": len(points), "crs": CRS,
            "buffer_m": BUFFER_M, "rectangle_width_km": width / 1000,
            "rectangle_height_km": height / 1000,
            "ideal_buffered_area_km2": area / 1e6,
            "units_evidence": "Fixed source hash and baseline manifest output_crs=7899"}


def _command(root, directory, plans, image_id, container_name):
    env = {
        "RENV_CONFIG_AUTOLOADER_ENABLED": "false",
        "CPL_TMPDIR": "/app/output/scratch", "TMPDIR": "/app/output/scratch",
        "NETWORK_CITY": directory.name, "NETWORK_OUTPUT_SUBDIR": "expanded_network",
        "NETWORK_REGION": "./output/activity_bbox.gpkg", "NETWORK_OUTPUT_CRS": str(CRS),
        "NETWORK_REGION_BUFFER_DIST": str(BUFFER_M), "NETWORK_DOWNLOAD_OSM": "TRUE",
        "NETWORK_PARALLEL_CORES": "2",
        "NETWORK_OSM_PBF": "./output/scratch/geofabrik_victoria-latest.osm.pbf",
        "NETWORK_OSM_GPKG": "./output/scratch/osm_extract.gpkg",
        "NETWORK_UNCONFIGURED_SQLITE": "./output/scratch/network_unconfigured.sqlite",
    }
    command = ["docker", "run", "--rm", "--name", container_name,
               # Docker Desktop can reject the cached OCI index with an explicit
               # platform even though inspect reports amd64. Use its local resolver
               # (as the existing runner does); pin identity and disable pulls.
               "--pull", "never", "--network", "none",
               "--memory", "32g", "--cpus", "4", "--user", f"{os.getuid()}:{os.getgid()}",
               "-v", f"{root / 'data'}:/app/data:ro",
               "-v", f"{directory}:/app/output",
               "-v", f"{plans}:/source/plans.xml:ro"]
    for key, value in env.items():
        command.extend(["-e", f"{key}={value}"])
    command.extend(["--entrypoint", "Rscript", image_id, "--vanilla", "/app/output/driver.R"])
    return command, env


def _network(path):
    root = ET.parse(path).getroot()
    nodes = {e.get("id"): (float(e.get("x")), float(e.get("y")))
             for e in root.findall("./nodes/node")}
    links = {e.get("id"): dict(e.attrib) for e in root.findall("./links/link")}
    return nodes, links


def map_network_ids(old_path, new_path):
    """Geometric candidates, not proof of equivalent topology or a plan rewrite."""
    from shapely import Point, STRtree
    old_nodes, old_links = _network(old_path)
    new_nodes, new_links = _network(new_path)
    if not new_nodes:
        raise ValueError("Generated network has no nodes.")
    ids = list(new_nodes)
    tree = STRtree([Point(new_nodes[key]) for key in ids])
    node_map = {}
    for key, xy in old_nodes.items():
        indices, distances = tree.query_nearest(Point(xy), all_matches=True, return_distance=True)
        candidates = sorted(ids[int(index)] for index in indices)
        distance = float(min(distances))
        matched = len(candidates) == 1 and distance <= 1.0
        node_map[key] = {"new_node_id": candidates[0] if matched else None,
                         "nearest_candidate_ids": candidates, "distance_m": distance,
                         "status": "matched" if matched else "ambiguous_or_more_than_1m"}
    by_endpoints = {}
    for key, link in new_links.items():
        by_endpoints.setdefault((link["from"], link["to"]), []).append(key)
    link_map = {}
    for key, old in old_links.items():
        start = node_map.get(old["from"], {}).get("new_node_id")
        end = node_map.get(old["to"], {}).get("new_node_id")
        old_modes = set(old.get("modes", "").split(","))
        candidates = sorted(k for k in by_endpoints.get((start, end), [])
                            if old_modes <= set(new_links[k].get("modes", "").split(",")))
        link_map[key] = {"new_link_id": candidates[0] if len(candidates) == 1 else None,
                         "candidate_ids": candidates,
                         "status": "matched_endpoints_modes" if len(candidates) == 1 else "unresolved"}
    anchor_ids = ("8844", "8954", "8695", "9032")
    anchor_map = {key: node_map.get(key) for key in anchor_ids}
    start = (node_map.get("8695") or {}).get("new_node_id")
    end = (node_map.get("9032") or {}).get("new_node_id")
    direct_chord = [key for key, link in new_links.items()
                    if start is not None and end is not None
                    and {link["from"], link["to"]} == {start, end}]
    return {
        "schema_version": 1, "crs": CRS, "node_tolerance_m": 1.0,
        "method": "unique_nearest_node_within_1m_then_directed_endpoints_and_mode_superset",
        "counts": {"old_nodes": len(old_nodes), "new_nodes": len(new_nodes),
                   "old_links": len(old_links), "new_links": len(new_links),
                   "matched_nodes": sum(v["new_node_id"] is not None for v in node_map.values()),
                   "matched_links": sum(v["new_link_id"] is not None for v in link_map.values())},
        "nodes": node_map, "links": link_map,
        "case_anchors": {"nodes": anchor_map,
                         "closure_links": {key: link_map.get(key) for key in ("890", "2071")},
                         "existing_direct_alternative_links": direct_chord},
        "limitations": ["No raw node/activity coordinates are included in this mapping.",
                        "Node proximity and matching endpoints/modes do not establish identical attributes or routing.",
                        "Unresolved links may be split or removed. Recheck corridor geometry before preparing a case.",
                        "This mapping never edits case plans or frozen experiment inputs."],
    }


def expand_network(*, experiment_id=None, root=ROOT):
    root = Path(root).resolve()
    experiment_id = experiment_id or f"cbd_bbox500_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:6]}"
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", experiment_id):
        raise ValueError("Experiment ID must be 1-64 letters/digits/underscores, starting with a letter.")
    parent = root / "output/domain_experiments"
    parent.mkdir(parents=True, exist_ok=True)
    directory = parent / experiment_id
    directory.mkdir(exist_ok=False)
    manifest = {"schema_version": 1, "experiment_id": experiment_id, "status": "preparing",
                "started_at": _now(), "finished_at": None, "stage": "preflight",
                "error": None, "events": [], "simulation_started": False,
                "network_generation_started_at": None, "network_generation_finished_at": None}
    container_name = f"domain-{experiment_id.lower()}"
    generation_started = False

    def stage(name):
        manifest.update(stage=name)
        manifest["events"].append({"stage": name, "at": _now()})
        _save_manifest(directory, manifest)
        announce(f"Domain experiment {experiment_id}: {name}")

    try:
        stage("preflight")
        plans = root / f"output/{BASELINE}_demand/8.xml/plan.xml"
        original_network = root / f"output/{BASELINE}_network/network.xml"
        baseline_record = root / f"output/run_records/{BASELINE}/run_manifest.json"
        pbf = root / "data/geofabrik_victoria-latest.osm.pbf"
        manifest["inputs"] = {key: _evidence(path) for key, path in
                              (("plans", plans), ("original_network", original_network),
                               ("baseline_manifest", baseline_record), ("osm_pbf", pbf))}
        if manifest["inputs"]["original_network"]["sha256"] != NETWORK_SHA256:
            raise ValueError("Original network differs from fixed baseline SHA-256.")
        record = json.loads(baseline_record.read_text())
        if record.get("configuration", {}).get("output_crs") != CRS:
            raise ValueError("Fixed baseline does not declare EPSG:7899.")
        manifest["domain_request"] = _validate_plans(plans)
        manifest["environment"] = _cached_environment(root)
        manifest["source"] = {
            "script": _evidence(Path(__file__)),
            "coverage_audit": _evidence(root / "wrapper/coverage_audit.py"),
            "generator_source_fingerprint": manifest["environment"]["source_fingerprint"],
        }
        before = audit_coverage(original_network, plans)
        _new_json(directory / "coverage_before.json", before)
        (directory / "scratch").mkdir()
        (directory / "driver.R").write_text(R_DRIVER)
        manifest["driver"] = _evidence(directory / "driver.R")
        command, env = _command(root, directory, plans, manifest["environment"]["image_id"], container_name)
        manifest.update(command=command, container_environment=env, container_name=container_name,
                        status="running", console_log=str(directory / "console.log"))
        manifest["network_generation_started_at"] = _now()
        stage("network_generation")
        generation_started = True
        run_logged(command, log_path=directory / "console.log", cwd=root)
        manifest["network_generation_finished_at"] = _now()
        manifest["generator_returncode"] = 0
        stage("audit_after_cleaning")
        network_dir = directory / "expanded_network"
        for name in ("network.xml", "network.sqlite"):
            if not (network_dir / name).is_file() or (network_dir / name).stat().st_size == 0:
                raise ValueError(f"Generator did not produce nonempty {name}.")
        after = audit_coverage(network_dir / "network.xml", plans)
        if not after["network"]["nodes"]["finite_coordinates"] or not after["network"]["links"]["usable_car_segments"]:
            raise ValueError("Generated artifact has no finite nodes/usable car segments.")
        _new_json(directory / "coverage_after.json", after)
        mapping = map_network_ids(original_network, network_dir / "network.xml")
        _new_json(directory / "network_id_mapping.json", mapping)
        preserved = {key: _hash(item["path"]) == item["sha256"] for key, item in manifest["inputs"].items()}
        manifest["input_hashes_unchanged"] = preserved
        if not all(preserved.values()):
            raise ValueError("An original input hash changed during the experiment.")
        manifest["domain_result"] = json.loads((directory / "domain_summary.json").read_text())
        manifest["r_environment"] = json.loads((directory / "r_environment.json").read_text())
        artifacts = ["expanded_network/network.xml", "expanded_network/network.sqlite", "activity_bbox.gpkg",
                     "coverage_before.json", "coverage_after.json", "network_id_mapping.json", "console.log",
                     "domain_summary.json", "r_environment.json"]
        manifest["artifacts"] = {name: _evidence(directory / name) for name in artifacts}
        manifest["audit_summary"] = {
            "before": before["activities"], "after": after["activities"],
            "car_endpoint_activities_after": after["car_endpoint_activities"],
            "case_anchors": mapping["case_anchors"],
        }
        manifest.update(status="completed", finished_at=_now())
        stage("completed")
        return directory
    except BaseException as exc:
        if generation_started:
            # This name was allocated by this experiment; never stop other jobs.
            try:
                stopped = subprocess.run(["docker", "stop", "--time", "10", container_name],
                                         capture_output=True, text=True, check=False, timeout=30)
                manifest["container_stop_returncode"] = stopped.returncode
            except (OSError, subprocess.TimeoutExpired) as stop_error:
                manifest["container_stop_error"] = type(stop_error).__name__
        if "inputs" in manifest:
            manifest["input_hashes_unchanged"] = {
                key: _hash(item["path"]) == item["sha256"] if Path(item["path"]).is_file() else False
                for key, item in manifest["inputs"].items()}
        manifest.update(status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                        finished_at=_now(), error={"type": type(exc).__name__, "message": str(exc)})
        if hasattr(exc, "returncode"):
            manifest["generator_returncode"] = exc.returncode
        if generation_started and manifest["network_generation_finished_at"] is None:
            manifest["network_generation_finished_at"] = _now()
        _save_manifest(directory, manifest)
        announce(f"Domain experiment failed; evidence preserved at {directory}")
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", required=True, help="Explicitly generate the network, without MATSim")
    parser.add_argument("--experiment-id", default=None, help="Fresh output name; existing names are never reused")
    args = parser.parse_args(argv)
    try:
        directory = expand_network(experiment_id=args.experiment_id)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, ET.ParseError) as exc:
        print(f"Network expansion failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "completed", "experiment_dir": str(directory),
                      "network_file": str(directory / "expanded_network/network.xml"),
                      "manifest": str(directory / "manifest.json"), "simulation_started": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
