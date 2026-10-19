"""Prepare a bounded network domain for fixed, unrouted demand; never run R.

GeoJSON is an unbuffered EPSG:4326 serialization of a densified EPSG:7899
rectangle. Only the network generator applies the network buffer, in metres.
The strict post-cleaning gate is a workflow prerequisite, not model validation.
"""
from __future__ import annotations

from dataclasses import dataclass
import gzip
import json
import math
from pathlib import Path
import re
import uuid
import xml.etree.ElementTree as ET

from rasterio.warp import transform
from shapely.geometry import Polygon, box

from wrapper.coverage_audit import audit_coverage
from wrapper.provenance import file_evidence, sha256_file, utc_now

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
EDGE_STEP_M = 100.0
ROUNDTRIP_TOLERANCE_M = 0.1


@dataclass(frozen=True)
class ActivityDomain:
    region_file: str
    evidence_path: Path
    plans_path: Path
    plans_sha256: str
    region_sha256: str
    network_buffer_m: int

    @property
    def coverage_path(self) -> Path:
        return self.evidence_path.with_name("coverage_after.json")


def validate_output_name(name: str) -> None:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", name):
        raise ValueError("Output name must be a simple 1-128 character basename.")


def validate_domain_options(plans_crs: int, network_buffer_m: int,
                            max_buffered_area_km2: float) -> None:
    if type(plans_crs) is not int or plans_crs != 7899:
        raise ValueError("Activity-domain v1 requires declared EPSG:7899 plans; CRS is not inferred.")
    if type(network_buffer_m) is not int or network_buffer_m <= 0:
        raise ValueError("Network-only buffer must be a positive integer number of metres.")
    if (isinstance(max_buffered_area_km2, bool)
            or not isinstance(max_buffered_area_km2, (int, float))
            or not math.isfinite(max_buffered_area_km2) or max_buffered_area_km2 <= 0):
        raise ValueError("An explicit positive finite maximum network-domain area is required.")


def _write_json(path: Path, value: dict, *, new: bool = False) -> None:
    text = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if new:
        with path.open("x") as stream:
            stream.write(text)
    else:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with temporary.open("x") as stream:
            stream.write(text)
        temporary.replace(path)


def _tag(element):
    return element.tag.rsplit("}", 1)[-1]


def _inventory(path: Path) -> tuple[dict, tuple | None]:
    """Strict generated-demand contract: one usable, unrouted plan per person.

    Unlike the diagnostic audit we cannot skip malformed/ambiguous persons: a
    skipped person would silently shrink the domain. No identifiers escape.
    """
    counts = dict.fromkeys(("persons", "activities", "finite_coordinates", "missing_coordinates",
                           "invalid_coordinates", "nonfinite_coordinates", "invalid_plan_selection",
                           "empty_plans", "network_bound_plans"), 0)
    xmin = ymin = math.inf
    xmax = ymax = -math.inf
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "rb") as stream:
        root = None
        for event, element in ET.iterparse(stream, events=("start", "end")):
            if root is None:
                root = element
                if _tag(root) != "population":
                    raise ValueError("Expected population XML for activity-domain preparation.")
            if event != "end" or _tag(element) != "person":
                continue
            counts["persons"] += 1
            plans = [e for e in element if _tag(e) == "plan"]
            if (len(plans) != 1 or (plans[0].get("selected") or "").strip().lower()
                    not in ("", "yes", "true", "1")):
                counts["invalid_plan_selection"] += 1
                root.clear()
                continue
            plan = plans[0]
            acts = [e for e in plan if _tag(e) in ("activity", "act")]
            counts["empty_plans"] += not acts
            if (any(_tag(e) == "route" for e in plan.iter())
                    or any(any(k in e.attrib for k in ("link", "linkId", "link_id")) for e in acts)):
                counts["network_bound_plans"] += 1
            for act in acts:
                counts["activities"] += 1
                raw = [act.get(axis) for axis in ("x", "y")]
                if any(v is None or not v.strip() for v in raw):
                    counts["missing_coordinates"] += 1
                    continue
                try:
                    x, y = map(float, raw)
                except ValueError:
                    counts["invalid_coordinates"] += 1
                    continue
                if not math.isfinite(x) or not math.isfinite(y):
                    counts["nonfinite_coordinates"] += 1
                    continue
                counts["finite_coordinates"] += 1
                xmin, ymin, xmax, ymax = min(xmin, x), min(ymin, y), max(xmax, x), max(ymax, y)
            root.clear()
    return counts, (xmin, ymin, xmax, ymax) if counts["finite_coordinates"] else None


def _region_geometry(bounds: tuple) -> tuple[dict, float]:
    native = box(*bounds)
    corners = list(native.exterior.coords)
    ring = []
    for start, end in zip(corners, corners[1:]):
        pieces = max(1, math.ceil(math.dist(start, end) / EDGE_STEP_M))
        ring.extend([(start[0] + (end[0] - start[0]) * i / pieces,
                      start[1] + (end[1] - start[1]) * i / pieces) for i in range(pieces)])
    ring.append(ring[0])
    lons, lats = transform("EPSG:7899", "EPSG:4326", *zip(*ring))
    if any(not math.isfinite(v) for v in (*lons, *lats)):
        raise ValueError("Domain reprojection produced nonfinite coordinates.")
    xs, ys = transform("EPSG:4326", "EPSG:7899", lons, lats)
    restored = Polygon(zip(xs, ys))
    error = native.hausdorff_distance(restored)
    if not restored.is_valid or not math.isfinite(error) or error > ROUNDTRIP_TOLERANCE_M:
        raise ValueError("Domain projection roundtrip exceeds the 0.1 m geometry tolerance.")
    return {"type": "Polygon", "coordinates": [list(map(list, zip(lons, lats)))]}, error


def prepare_activity_domain(plans_path: Path, *, output_name: str, plans_crs: int,
                            max_buffered_area_km2: float,
                            network_buffer_m: int = 500) -> ActivityDomain:
    validate_output_name(output_name)
    validate_domain_options(plans_crs, network_buffer_m, max_buffered_area_km2)
    directory = OUTPUT_DIR / f"{output_name}_domain"
    directory.mkdir(parents=True, exist_ok=False)
    evidence_path = directory / "domain_manifest.json"
    plans_path = Path(plans_path).resolve()
    manifest = {
        "schema_version": 1, "policy": "activity_bbox_v1", "status": "preparing",
        "started_at": utc_now(), "plans_crs": plans_crs, "region_crs": 4326,
        "network_buffer_m": network_buffer_m, "geojson_is_buffered": False,
        "max_buffered_area_km2": max_buffered_area_km2,
        "plan_selection": "one selected or unmarked single unrouted plan per person; no skipped persons",
        "validation_status": "experimental", "error": None,
        "limitations": ["BBox coverage is not polygon accuracy, access, routing or simulation validity."],
    }
    _write_json(evidence_path, manifest, new=True)
    try:
        manifest["plans"] = file_evidence(plans_path, checksum=True)
        counts, bounds = _inventory(plans_path)
        manifest["activity_inventory"] = counts
        if (not counts["persons"] or not counts["activities"]
                or counts["finite_coordinates"] != counts["activities"]
                or any(counts[k] for k in ("invalid_plan_selection", "empty_plans", "network_bound_plans"))):
            raise ValueError("Domain requires nonempty, finite-coordinate, uniquely selected unrouted demand; see aggregate inventory.")
        width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
        if not math.isfinite(width) or not math.isfinite(height):
            raise ValueError("Activity bbox extent overflow; domain preparation stopped.")
        if width <= 0 or height <= 0:
            raise ValueError("Degenerate activity bbox is unsupported; no coordinates were changed.")
        # This is a conservative *budget check*, not extra buffering of the
        # geometry. Allow for the vendor's 1 m snap grid and reprojection error.
        budget_buffer = network_buffer_m + 2.0
        upper_area = (width * height + 2 * budget_buffer * (width + height)
                      + math.pi * budget_buffer**2) / 1e6
        if not math.isfinite(upper_area):
            raise ValueError("Activity domain area overflow; domain preparation stopped.")
        manifest["domain_geometry"] = {
            "width_m": width, "height_m": height, "unbuffered_area_km2": width * height / 1e6,
            "buffered_area_upper_bound_km2": upper_area, "budget_rounding_allowance_m": 2.0,
            "edge_densification_max_step_m": EDGE_STEP_M,
        }
        if upper_area > max_buffered_area_km2:
            raise ValueError("Activity domain exceeds the explicit area budget; demand was not clipped. Review domain scope.")
        geometry, error = _region_geometry(bounds)
        manifest["domain_geometry"]["python_roundtrip_hausdorff_m"] = error
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        region_file = f"{output_name}_activity_bbox_{uuid.uuid4().hex[:12]}.geojson"
        region_path = DATA_DIR / region_file
        _write_json(region_path, {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {}, "geometry": geometry}]}, new=True)
        manifest["region"] = {**file_evidence(region_path, checksum=True), "data_relative_path": region_file}
        if sha256_file(plans_path) != manifest["plans"]["sha256"]:
            raise ValueError("Plans changed during domain preparation; no generation permitted.")
        manifest.update(status="prepared", prepared_at=utc_now())
        _write_json(evidence_path, manifest)
        return ActivityDomain(region_file, evidence_path, plans_path,
                              manifest["plans"]["sha256"], manifest["region"]["sha256"], network_buffer_m)
    except BaseException as exc:
        manifest.update(status="failed", finished_at=utc_now(), error={"type": type(exc).__name__, "message": str(exc)})
        _write_json(evidence_path, manifest)
        raise


def fail_activity_domain(domain: ActivityDomain, exc: BaseException) -> None:
    manifest = json.loads(domain.evidence_path.read_text())
    manifest.update(status="failed", finished_at=utc_now(),
                    error={"type": type(exc).__name__, "message": str(exc)})
    _write_json(domain.evidence_path, manifest)


def audit_activity_network(domain: ActivityDomain, network_path: Path) -> dict:
    """Save the cleaned-network audit before enforcing the required 100% gate."""
    manifest = json.loads(domain.evidence_path.read_text())
    try:
        report = audit_coverage(network_path, domain.plans_path)
        _write_json(domain.coverage_path, report, new=True)
        acts, nodes = report["activities"], report["network"]["nodes"]
        checks = {
            "plans_unchanged": sha256_file(domain.plans_path) == domain.plans_sha256,
            "region_unchanged": sha256_file(DATA_DIR / domain.region_file) == domain.region_sha256,
            "same_activity_count": acts["total"] == manifest["activity_inventory"]["activities"],
            "all_activities_finite": acts["total"] > 0 and acts["finite_coordinates"] == acts["total"],
            "all_finite_activities_inside_node_bbox": acts["inside_node_bbox"] == acts["finite_coordinates"] > 0,
            "all_network_nodes_finite": nodes["finite_coordinates"] == nodes["total"] > 0,
            "usable_car_network": report["network"]["links"]["usable_car_segments"] > 0,
        }
        manifest["post_cleaning_gate"] = {"passed": all(checks.values()), "checks": checks,
            "meaning": "Required workflow domain condition only; not transport or simulation validity."}
        manifest["network"] = file_evidence(Path(network_path), checksum=True)
        manifest["coverage_after"] = file_evidence(domain.coverage_path, checksum=True)
        _write_json(domain.evidence_path, manifest)
        if not all(checks.values()):
            raise ValueError("Post-cleaning activity-domain gate failed: " + ", ".join(k for k, v in checks.items() if not v))
        manifest.update(status="completed", finished_at=utc_now())
        _write_json(domain.evidence_path, manifest)
        return report
    except BaseException as exc:
        fail_activity_domain(domain, exc)
        raise
