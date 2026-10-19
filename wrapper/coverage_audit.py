"""Read-only, aggregate screening of MATSim network/population XML (also .gz).

The two input files are authoritative. No demand is changed, no simulation is
started, and no validity/pass decision is made. Distances use coordinate units:
the caller must independently establish a shared projected CRS before treating
them as metres. A node bounding box is not a study-area polygon.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import gzip
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def _tag(element):
    return element.tag.rsplit("}", 1)[-1]


def _records(path, expected_root, record_paths):
    """Retain one record at a time, including its children; never resolve DTDs."""
    path = Path(path)
    opener = gzip.open if path.suffix.lower() == ".gz" else open
    with opener(path, "rb") as stream:
        stack = []
        for event, element in ET.iterparse(stream, events=("start", "end")):
            if event == "start":
                if not stack and _tag(element) != expected_root:
                    raise ValueError(f"Expected a {expected_root} XML root.")
                stack.append(element)
                continue
            tags = tuple(_tag(node) for node in stack[1:])
            if tags in record_paths:
                yield element
                stack[-2].remove(element)
                element.clear()
            elif len(stack) == 2:
                # Metadata/empty containers can also be released at root level.
                stack[0].remove(element)
                element.clear()
            stack.pop()


def _coordinates(element):
    raw = [element.get(axis) for axis in ("x", "y")]
    if any(value is None or not value.strip() for value in raw):
        return "missing_coordinates", None
    try:
        point = tuple(float(value) for value in raw)
    except ValueError:
        return "invalid_coordinates", None
    if not all(math.isfinite(value) for value in point):
        return "nonfinite_coordinates", None
    return "finite_coordinates", point


def _bbox(points):
    if not points:
        return None
    return [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]


def _inside(point, bbox):
    if point is None or bbox is None:
        return None
    return bbox[0] <= point[0] <= bbox[2] and bbox[1] <= point[1] <= bbox[3]


def _counts():
    return Counter(dict.fromkeys(("total", "finite_coordinates", "missing_coordinates",
                                 "invalid_coordinates", "nonfinite_coordinates"), 0))


def _read_network(path):
    nodes = {}
    node_counts = _counts()
    node_counts["missing_identifiers"] = 0
    car_links = []
    link_counts = Counter(dict.fromkeys(("total", "explicit_car_links", "missing_modes",
                                        "car_links_with_unusable_endpoints",
                                        "usable_car_segments", "zero_length_car_segments"), 0))
    finite_points = []
    for element in _records(path, "network", {("nodes", "node"), ("links", "link")}):
        if _tag(element) == "node":
            status, point = _coordinates(element)
            node_counts["total"] += 1
            node_counts[status] += 1
            if point is not None:
                finite_points.append(point)
            identifier = element.get("id")
            if not identifier:
                node_counts["missing_identifiers"] += 1
            elif identifier in nodes:
                raise ValueError("Network contains duplicate node identifiers.")
            else:
                nodes[identifier] = point
        else:
            link_counts["total"] += 1
            raw_modes = (element.get("modes") or "").strip()
            if not raw_modes:
                link_counts["missing_modes"] += 1
            if "car" in re.split(r"[,\s]+", raw_modes):
                link_counts["explicit_car_links"] += 1
                car_links.append((element.get("from"), element.get("to")))
    segments = []
    for source, target in car_links:
        start, end = nodes.get(source), nodes.get(target)
        if start is None or end is None:
            link_counts["car_links_with_unusable_endpoints"] += 1
        else:
            segments.append((start, end))
            link_counts["usable_car_segments"] += 1
            link_counts["zero_length_car_segments"] += start == end
    return {"nodes": dict(node_counts), "links": dict(link_counts),
            "node_bbox": _bbox(finite_points)}, segments


def _distance_query(segments):
    if not segments:
        return None, "no_usable_explicit_car_links"
    try:
        from shapely import LineString, Point, STRtree
    except ImportError:
        return None, "shapely_unavailable"
    geometries = [Point(start) if start == end else LineString((start, end))
                  for start, end in segments]
    tree = STRtree(geometries)

    def distance(point):
        geometry = Point(point)
        result = float(geometry.distance(geometries[tree.nearest(geometry)]))
        return result if math.isfinite(result) else None

    return distance, "available"


def _distance_summary(values, finite_count):
    values = sorted(values)
    count = len(values)
    # Nearest-rank quantiles: deterministic for both tiny and large groups.
    return {
        "count": count,
        "unavailable_for_finite_coordinates": finite_count - count,
        "min": values[0] if count else None,
        "p50": values[math.ceil(0.50 * count) - 1] if count else None,
        "p95": values[math.ceil(0.95 * count) - 1] if count else None,
        "max": values[-1] if count else None,
        # Divide before summation to avoid overflow of otherwise finite values.
        "mean": math.fsum(value / count for value in values) if count else None,
        "count_greater_than": {str(limit): sum(value > limit for value in values)
                               for limit in (100, 500, 1000)},
    }


@dataclass
class _ActivityTotals:
    counts: Counter = field(default_factory=_counts)
    distances: list = field(default_factory=list)

    def add(self, status, inside, distance):
        self.counts["total"] += 1
        self.counts[status] += 1
        if inside is not None:
            self.counts["inside_node_bbox" if inside else "outside_node_bbox"] += 1
        elif status == "finite_coordinates":
            self.counts["bbox_unavailable_for_finite_coordinates"] += 1
        if distance is not None:
            self.distances.append(distance)

    def summary(self, bbox_available):
        counts = self.counts.copy()
        for name in ("inside_node_bbox", "outside_node_bbox",
                     "bbox_unavailable_for_finite_coordinates"):
            counts.setdefault(name, 0)
        finite = counts["finite_coordinates"]
        return {**counts,
                "inside_node_bbox_fraction_of_finite": (
                    counts["inside_node_bbox"] / finite if finite and bbox_available else None),
                "nearest_car_distance": _distance_summary(self.distances, finite)}


def _select_plan(person, counts):
    plans = [child for child in person if _tag(child) == "plan"]
    counts["persons_total"] += 1
    counts["plans_total"] += len(plans)
    if not plans:
        counts["persons_without_plans"] += 1
        return None
    flags = [(plan.get("selected") or "").strip().lower() for plan in plans]
    if any(flag not in ("", "yes", "true", "1", "no", "false", "0") for flag in flags):
        counts["persons_invalid_selection_flags"] += 1
        return None
    selected = [plan for plan, flag in zip(plans, flags) if flag in ("yes", "true", "1")]
    if len(selected) == 1:
        counts["persons_explicit_selected"] += 1
        return selected[0]
    if len(selected) > 1:
        counts["persons_multiple_selected"] += 1
    elif len(plans) == 1 and not flags[0]:
        counts["persons_unmarked_single_plan"] += 1
        return plans[0]
    else:
        counts["persons_no_unique_selected_plan"] += 1
    return None


def _label(value):
    return value.strip() if value and value.strip() else "__missing__"


def audit_coverage(network_path: str | Path, plans_path: str | Path) -> dict:
    """Return JSON-safe aggregate evidence from network and population XML.

    Unique explicitly selected plans (yes/true/1) are audited. A sole unmarked
    plan is a counted fallback; ambiguous, explicitly deselected or invalidly
    marked populations are counted as unaudited, never silently first-picked.
    Coordinate failures are exclusive pair-level categories, in precedence
    missing, invalid numeric text, nonfinite. Activities without coordinates
    (including link/facility-only activities) are not imputed.

    OSError / ElementTree.ParseError propagate for unreadable/malformed files;
    ValueError identifies wrong XML roots or duplicate network node IDs. Empty
    files with valid XML roots and unusable coordinates return diagnostics.
    Missing Shapely disables distances explicitly, while retaining bbox counts.
    Memory is O(network nodes/links + audited activities + largest person XML).
    No person IDs, per-person records, paths or raw activity coordinates escape.
    """
    network, segments = _read_network(network_path)
    distance_query, distance_status = _distance_query(segments)
    bbox = network["node_bbox"]
    counts = Counter(dict.fromkeys((
        "persons_total", "plans_total", "persons_audited", "persons_explicit_selected",
        "persons_unmarked_single_plan", "persons_without_plans", "persons_multiple_selected",
        "persons_invalid_selection_flags", "persons_no_unique_selected_plan",
        "persons_with_no_activities", "persons_with_any_outside_bbox",
        "persons_with_home_outside_bbox", "persons_with_nonhome_outside_bbox",
        "persons_with_only_nonhome_outside_bbox", "persons_with_unusable_coordinates",
    ), 0))
    all_activities = _ActivityTotals()
    car_endpoints = _ActivityTotals()
    by_type = defaultdict(_ActivityTotals)
    by_arriving = defaultdict(_ActivityTotals)
    by_departing = defaultdict(_ActivityTotals)
    by_bbox = {"inside": _ActivityTotals(), "outside": _ActivityTotals()}
    legs_by_mode = {}
    for person in _records(plans_path, "population", {("person",)}):
        plan = _select_plan(person, counts)
        if plan is None:
            continue
        counts["persons_audited"] += 1
        sequence = [child for child in plan if _tag(child) in ("act", "activity", "leg")]
        home_outside = nonhome_outside = unusable = False
        person_activities = 0
        for index, element in enumerate(sequence):
            before = sequence[index - 1] if index else None
            after = sequence[index + 1] if index + 1 < len(sequence) else None
            if _tag(element) == "leg":
                mode = _label(element.get("mode"))
                leg_counts = legs_by_mode.setdefault(mode, Counter(dict.fromkeys((
                    "total", "missing_adjacent_activity", "unusable_endpoint_coordinates",
                    "bbox_unavailable", "both_inside", "inside_to_outside",
                    "outside_to_inside", "both_outside",
                ), 0)))
                leg_counts["total"] += 1
                if before is None or after is None or _tag(before) == "leg" or _tag(after) == "leg":
                    leg_counts["missing_adjacent_activity"] += 1
                else:
                    origin, destination = _coordinates(before)[1], _coordinates(after)[1]
                    if origin is None or destination is None:
                        leg_counts["unusable_endpoint_coordinates"] += 1
                    elif bbox is None:
                        leg_counts["bbox_unavailable"] += 1
                    else:
                        inside_pair = (_inside(origin, bbox), _inside(destination, bbox))
                        name = {(True, True): "both_inside", (True, False): "inside_to_outside",
                                (False, True): "outside_to_inside", (False, False): "both_outside"}
                        leg_counts[name[inside_pair]] += 1
                continue
            person_activities += 1
            status, point = _coordinates(element)
            inside = _inside(point, bbox)
            distance = distance_query(point) if point is not None and distance_query else None
            activity_type = _label(element.get("type"))
            arriving = (_label(before.get("mode")) if before is not None and _tag(before) == "leg"
                        else "__no_adjacent_leg__")
            departing = (_label(after.get("mode")) if after is not None and _tag(after) == "leg"
                         else "__no_adjacent_leg__")
            groups = [all_activities, by_type[activity_type], by_arriving[arriving], by_departing[departing]]
            if inside is not None:
                groups.append(by_bbox["inside" if inside else "outside"])
            if "car" in (arriving, departing):
                groups.append(car_endpoints)
            for group in groups:
                group.add(status, inside, distance)
            if point is None:
                unusable = True
            if inside is False:
                if activity_type.casefold() == "home":
                    home_outside = True
                else:
                    nonhome_outside = True
        counts["persons_with_no_activities"] += person_activities == 0
        counts["persons_with_any_outside_bbox"] += home_outside or nonhome_outside
        counts["persons_with_home_outside_bbox"] += home_outside
        counts["persons_with_nonhome_outside_bbox"] += nonhome_outside
        counts["persons_with_only_nonhome_outside_bbox"] += nonhome_outside and not home_outside
        counts["persons_with_unusable_coordinates"] += unusable
    counts["persons_unaudited"] = counts["persons_total"] - counts["persons_audited"]
    counts["plans_not_audited"] = counts["plans_total"] - counts["persons_audited"]
    def summarize(group):
        return group.summary(bbox is not None)

    limitations = [
        {"code": "bbox_not_polygon", "message": "Node bbox containment is not polygon coverage, road access or route feasibility."},
        {"code": "crs_unverified", "message": "Two XML paths do not establish shared CRS/units. Verify provenance before interpreting distances as metres; no reprojection is performed."},
        {"code": "distance_is_geometric", "message": "Distance is to straight from/to segments of explicitly car-enabled links, ignoring road shape, direction, connectivity, barriers and MATSim activity-link assignment."},
        {"code": "activity_weighted", "message": "Repeated activities and home visits count separately; these are not unique places or population-weighted coverage."},
        {"code": "mode_is_adjacent_leg", "message": "Mode groups describe immediate incoming/outgoing legs, not inferred trip main modes. Stage activities are included."},
        {"code": "external_destinations_unresolved", "message": "Outside bbox does not identify an external SA1 or trip purpose. Compare upstream region/address records before changing demand or network extent."},
        {"code": "no_simulation_decision", "message": "Counts and distance thresholds are diagnostics, not automatic simulation validity or pass/fail criteria."},
    ]
    if counts["persons_unaudited"] or counts["persons_unmarked_single_plan"]:
        limitations.append({"code": "plan_selection", "message": "Review selection counts: ambiguous/deselected persons are unaudited; sole unmarked plans use an explicit counted fallback."})
    if all_activities.counts["total"] != all_activities.counts["finite_coordinates"]:
        limitations.append({"code": "unusable_activity_coordinates", "message": "Review missing/invalid/nonfinite coordinate counts. Link/facility references are not resolved; these activities are excluded from spatial denominators."})
    if bbox is None or network["nodes"]["finite_coordinates"] != network["nodes"]["total"]:
        limitations.append({"code": "incomplete_node_bbox", "message": "Network bbox uses only finite nodes; unavailable bbox fractions are null. Inspect network coordinate data."})
    if network["links"]["missing_modes"] or network["links"]["car_links_with_unusable_endpoints"]:
        limitations.append({"code": "incomplete_car_network", "message": "Links without explicit car mode or usable endpoints are excluded from distance geometry; inspect link-mode and endpoint counts."})
    if distance_status != "available":
        limitations.append({"code": "car_distance_unavailable", "message": f"Distance unavailable: {distance_status}. Bbox evidence remains separate."})
    elif len(all_activities.distances) < all_activities.counts["finite_coordinates"]:
        limitations.append({"code": "nonfinite_distance", "message": "Some finite coordinates produced nonfinite geometric distances; those distances are unavailable. Inspect coordinate magnitudes and CRS."})
    return {
        "schema_version": 1,
        "method": {
            "plan_selection": "unique_selected_else_single_unmarked_else_unaudited",
            "bbox": "inclusive_all_finite_network_nodes",
            "coordinate_status_precedence": ["missing", "invalid", "nonfinite", "finite"],
            "coordinate_units": "input_coordinate_units",
            "crs_verified": False,
            "car_distance": "euclidean_to_explicit_car_link_endpoint_segments",
            "car_distance_status": distance_status,
            "quantiles": "nearest_rank",
            "distance_thresholds": "strictly_greater_than_in_input_coordinate_units",
            "home_type_rule": "case_insensitive_exact_home",
            "reserved_group_labels": ["__missing__", "__no_adjacent_leg__"],
        },
        "network": network,
        "plans": dict(counts),
        "activities": summarize(all_activities),
        "by_activity_type": {key: summarize(value) for key, value in sorted(by_type.items())},
        "by_arriving_leg_mode": {key: summarize(value) for key, value in sorted(by_arriving.items())},
        "by_departing_leg_mode": {key: summarize(value) for key, value in sorted(by_departing.items())},
        "by_bbox": {key: summarize(value) for key, value in by_bbox.items()},
        "car_endpoint_activities": summarize(car_endpoints),
        "legs_by_mode": {key: dict(value) for key, value in sorted(legs_by_mode.items())},
        "limitations": limitations,
    }
