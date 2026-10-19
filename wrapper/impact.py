"""Read-only, evidence-checked comparison of completed MATSim runs.

``analyze_impact`` is the only public interface. It returns JSON-safe aggregates,
never person/vehicle IDs. ValueError means invalid input or incomparable evidence;
FileNotFoundError means a required artifact is absent. CSV/XML are read as streams;
compact trip indexes are retained to pair trips and attribute selected-link use.
There is no cache, simulation, or artifact write in this module.
"""

from __future__ import annotations

import bisect
import csv
import gzip
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from wrapper.ifline import resolve_run_assets
from wrapper.provenance import file_evidence
from wrapper.measurements import parse_time as _time, trip_mode as _trip_mode

__all__ = ["analyze_impact"]
_MODES = {"car", "bike", "walk", "pt", "all"}
_NETWORK_MODES = {"car", "bike"}
_IGNORED_CONFIG = {("network", "inputNetworkFile"),
                   ("controler", "outputDirectory"),
                   ("controller", "outputDirectory")}
_COLORS = {
    "le_minus_60": [0.0, 0.35, 0.24], "minus_60_to_minus_15": [0.12, 0.57, 0.38],
    "minus_15_to_minus_1": [0.49, 0.76, 0.60], "within_1s": [0.76, 0.78, 0.80],
    "plus_1_to_plus_15": [0.98, 0.70, 0.48], "plus_15_to_plus_60": [0.88, 0.32, 0.23],
    "ge_plus_60": [0.61, 0.07, 0.13], "unavailable": [0.44, 0.43, 0.59],
}
_BIN_RANGES = [
    ("le_minus_60", "≤ −60 s", None, -60, False, True),
    ("minus_60_to_minus_15", "−60 < Δ ≤ −15 s", -60, -15, False, True),
    ("minus_15_to_minus_1", "−15 < Δ ≤ −1 s", -15, -1, False, True),
    ("within_1s", "|Δ| < 1 s", -1, 1, False, False),
    ("plus_1_to_plus_15", "+1 ≤ Δ < +15 s", 1, 15, True, False),
    ("plus_15_to_plus_60", "+15 ≤ Δ < +60 s", 15, 60, True, False),
    ("ge_plus_60", "≥ +60 s", 60, None, True, False),
    ("unavailable", "Unavailable / not comparable", None, None, False, False),
]


def _number(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("Expected a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Expected a finite number")
    return result


def _open(path: Path, *, text: bool = False):
    kwargs = {"encoding": "utf-8-sig", "newline": ""} if text else {}
    return (gzip.open if path.suffix == ".gz" else open)(path, "rt" if text else "rb", **kwargs)


def _xml(path: Path) -> ET.Element:
    try:
        with _open(path) as stream:
            return ET.parse(stream).getroot()
    except ET.ParseError:
        raise ValueError(f"Malformed XML artifact: {path.name}") from None


def _config(path: Path) -> tuple[tuple, dict[tuple[str, str], str]]:
    root = _xml(path)
    if root.tag != "config":
        raise ValueError("Expected an output_config.xml config document")
    params = {}
    modules = set()
    for module in root.findall("module"):
        name = module.get("name", "")
        if not name or name in modules:
            raise ValueError("Missing or duplicate module in output_config.xml")
        modules.add(name)
        for param in module.findall("param"):
            key = (name, param.get("name", ""))
            if not key[1] or key in params or "value" not in param.attrib:
                raise ValueError("Missing or duplicate parameter in output_config.xml")
            params[key] = param.attrib["value"]

    def normalize(node: ET.Element, module: str = "") -> tuple:
        if node.tag == "module":
            module = node.get("name", "")
        children = [normalize(child, module) for child in node
                    if not (node.tag == "module" and child.tag == "param"
                            and (module, child.get("name")) in _IGNORED_CONFIG)]
        return (node.tag, tuple(sorted(node.attrib.items())), (node.text or "").strip(),
                tuple(sorted(children)))

    controller = "controler" if "controler" in modules else "controller"
    for key in (("global", "randomSeed"), (controller, "firstIteration"),
                (controller, "lastIteration"), ("plans", "inputPlansFile"),
                ("network", "inputNetworkFile"), (controller, "outputDirectory")):
        if key not in params or not params[key].strip():
            raise ValueError(f"Required output_config.xml parameter missing: {key[0]}.{key[1]}")
    for key in (("global", "randomSeed"), (controller, "firstIteration"),
                (controller, "lastIteration")):
        try:
            int(params[key])
        except ValueError:
            raise ValueError(f"Invalid integer output_config.xml parameter: {key[1]}") from None
    if not 0 <= int(params[controller, "firstIteration"]) <= int(params[controller, "lastIteration"]):
        raise ValueError("Invalid iteration range in output_config.xml")
    return normalize(root), params


def _verify_input_path(value: str, expected: Path, sim_dir: Path) -> None:
    """Resolve the project's Docker mount, without trusting manifest file hashes."""
    path = Path(value)
    if value.startswith("/app/output/"):
        path = sim_dir.parent / value[len("/app/output/"):]
    elif not path.is_absolute():
        path = sim_dir / path
    if path.resolve() != expected.resolve():
        raise ValueError("output_config.xml input path does not match resolved run assets")


def _network(path: Path) -> dict[str, dict]:
    nodes, links = {}, {}
    try:
        with _open(path) as stream:
            parser = ET.iterparse(stream, events=("start", "end"))
            _, root = next(parser)
            if root.tag != "network":
                raise ValueError("Expected MATSim output network")
            for event, elem in parser:
                if event != "end":
                    continue
                if elem.tag == "node":
                    key = elem.get("id")
                    if not key or key in nodes:
                        raise ValueError("Missing or duplicate network node ID")
                    nodes[key] = (_number(elem.get("x")), _number(elem.get("y")))
                    elem.clear()
                elif elem.tag == "link":
                    key, origin, destination = elem.get("id"), elem.get("from"), elem.get("to")
                    if not key or key in links or origin not in nodes or destination not in nodes:
                        raise ValueError("Missing, duplicate, or disconnected network link")
                    length, speed = _number(elem.get("length")), _number(elem.get("freespeed"))
                    if length <= 0 or speed <= 0:
                        raise ValueError("Network length and freespeed must be positive")
                    x1, y1 = nodes[origin]
                    x2, y2 = nodes[destination]
                    links[key] = {"from": origin, "to": destination, "x1": x1, "y1": y1,
                                  "x2": x2, "y2": y2, "length_m": length,
                                  "freespeed_m_s": speed, "freeflow_s": length / speed}
                    elem.clear()
                elif elem.tag in {"nodes", "links"}:
                    elem.clear()
    except (ET.ParseError, TypeError, OverflowError):
        raise ValueError("Invalid output network artifact") from None
    if not links:
        raise ValueError("Output network has no links")
    return links


@dataclass(frozen=True)
class _Trip:
    departure: float | None
    duration: float | None
    mode: str | None


@dataclass
class _Trips:
    rows: dict[tuple[str, int], _Trip]
    keys: set[tuple[str, int]]
    quality: dict
    headers: list[str]


def _trips(path: Path) -> _Trips:
    rows, keys, duplicates = {}, set(), set()
    quality = Counter({"rows": 0, "invalid_rows": 0, "invalid_key_rows": 0,
                       "invalid_departure_rows": 0, "invalid_travel_time_rows": 0,
                       "invalid_mode_rows": 0, "mode_fallback_rows": 0,
                       "duplicate_rows": 0, "duplicate_keys": 0})
    with _open(path, text=True) as stream:
        reader = csv.DictReader(stream, delimiter=";")
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or not {"person", "trip_number", "dep_time", "trav_time"} <= set(headers):
            raise ValueError("Trip table requires unique person, trip_number, dep_time, trav_time headers")
        mode_field = "main_mode" if "main_mode" in headers else "modes"
        if mode_field not in headers:
            raise ValueError("Trip table requires main_mode (or unambiguous modes) header")
        for row in reader:
            quality["rows"] += 1
            person, trip_number = row.get("person"), row.get("trip_number")
            try:
                number = int(trip_number or "")
                if not person or not person.strip() or number < 1:
                    raise ValueError
            except (ValueError, TypeError):
                quality["invalid_key_rows"] += 1
                quality["invalid_rows"] += 1
                continue
            key = person, number
            if key in keys:
                duplicates.add(key)
                quality["duplicate_rows"] += 1
            keys.add(key)
            departure, duration = _time(row.get("dep_time")), _time(row.get("trav_time"))
            trip_mode, fallback = _trip_mode(row)
            quality["mode_fallback_rows"] += fallback
            quality["invalid_departure_rows"] += departure is None
            quality["invalid_travel_time_rows"] += duration is None
            quality["invalid_mode_rows"] += trip_mode is None
            if None in (departure, duration, trip_mode) or None in row:
                quality["invalid_rows"] += 1
                if None in row:
                    duration = None
            rows[key] = _Trip(departure, duration, trip_mode)
    for key in duplicates:
        rows.pop(key, None)
    quality["duplicate_keys"] = len(duplicates)
    quality["unique_usable_key_count"] = len(rows)
    return _Trips(rows, keys, dict(quality), headers)


class _TripIndex:
    """Associate traffic events to trip intervals, never count legs as trip numbers."""

    def __init__(self, trips: _Trips):
        self.people = defaultdict(list)
        for key, trip in trips.rows.items():
            if trip.departure is not None and trip.duration is not None:
                self.people[key[0]].append((trip.departure, trip.departure + trip.duration, key))
        self.times = {}
        self.latest_ends = {}
        for person, intervals in self.people.items():
            intervals.sort()
            self.times[person] = [item[0] for item in intervals]
            ends, latest = [], -1.0
            for _, end, _ in intervals:
                latest = max(latest, end)
                ends.append(latest)
            self.latest_ends[person] = ends

    def at(self, person: str, time: float) -> tuple[str, int] | None:
        intervals = self.people.get(person, [])
        position = bisect.bisect_right(self.times.get(person, []), time) - 1
        if position < 0 or time > intervals[position][1]:
            return None
        # Overlapping trip intervals make attribution ambiguous. Exclude both.
        if position > 0 and self.latest_ends[person][position - 1] >= time:
            return None
        return intervals[position][2]


@dataclass
class _LinkStats:
    entered: int = 0
    complete: int = 0
    travel: float = 0.0
    delay: float = 0.0

    def output(self) -> dict:
        return {"entered_count": self.entered, "complete_traversal_count": self.complete,
                "mean_travel_time_s": self.travel / self.complete if self.complete else None,
                "mean_delay_s": self.delay / self.complete if self.complete else None}


def _events(path: Path, network: dict, trips: _Trips, selected: set[str],
            modes: set[str], start: float, end: float) -> tuple[dict, set, dict, dict]:
    stats = defaultdict(_LinkStats)
    hits = set()
    active, pending = {}, {}
    person_vehicles = defaultdict(set)
    index = _TripIndex(trips) if selected else None
    completion = {mode: {"departures": 0, "arrivals": 0, "stuck": 0}
                  for mode in ("car", "bike", "walk", "pt", "other")}
    quality = Counter({key: 0 for key in (
        "invalid_time_events", "out_of_order_events", "unknown_link_events",
        "unattributed_link_entries", "unmatched_link_exits", "partial_departure_link_exits",
        "interrupted_link_entries", "incomplete_link_entries", "partial_arrival_link_entries", "invalid_traversals",
        "selected_traversals_without_trip", "unsupported_network_mode_sessions")})

    def clear_vehicle(vehicle: str) -> None:
        if vehicle in pending:
            quality["incomplete_link_entries"] += 1
            pending.pop(vehicle)
        session = active.pop(vehicle, None)
        if session:
            person_vehicles[session[1]].discard(vehicle)

    previous_time = -1.0
    try:
        with _open(path) as stream:
            parser = ET.iterparse(stream, events=("start", "end"))
            _, root = next(parser)
            if root.tag != "events":
                raise ValueError("Expected MATSim events artifact")
            for event, elem in parser:
                if event != "end" or elem.tag != "event":
                    continue
                attrs = elem.attrib
                kind, vehicle, person = attrs.get("type"), attrs.get("vehicle", ""), attrs.get("person", "")
                time = _time(attrs.get("time"))
                # Even a malformed termination event must break a parking gap.
                if kind == "vehicle leaves traffic":
                    entry = pending.get(vehicle)
                    if entry and entry[0] == attrs.get("link"):
                        quality["partial_arrival_link_entries"] += 1
                        pending.pop(vehicle)
                    clear_vehicle(vehicle)
                elif kind in {"arrival", "stuckAndAbort", "stuck"}:
                    for owned in tuple(person_vehicles.get(person, ())):
                        clear_vehicle(owned)
                if time is None:
                    quality["invalid_time_events"] += 1
                    clear_vehicle(vehicle)
                    elem.clear()
                    root.clear()
                    continue
                if time < previous_time:
                    quality["out_of_order_events"] += 1
                    quality["incomplete_link_entries"] += len(pending)
                    pending.clear()
                previous_time = time
                if kind in {"departure", "arrival", "stuckAndAbort", "stuck"} and start <= time < end:
                    leg_mode = attrs.get("legMode", attrs.get("mode", "other"))
                    leg_mode = leg_mode if leg_mode in completion else "other"
                    count_key = {"departure": "departures", "arrival": "arrivals"}.get(kind, "stuck")
                    completion[leg_mode][count_key] += 1
                if kind == "vehicle enters traffic":
                    clear_vehicle(vehicle)
                    network_mode = attrs.get("networkMode")
                    if vehicle and person and network_mode in _NETWORK_MODES:
                        # This event starts on a partial link; do NOT create a pending entry.
                        active[vehicle] = (network_mode, person, True)
                        person_vehicles[person].add(vehicle)
                    else:
                        quality["unsupported_network_mode_sessions"] += 1
                elif kind == "entered link":
                    link = attrs.get("link")
                    if vehicle in pending:
                        quality["interrupted_link_entries"] += 1
                        pending.pop(vehicle)
                    session = active.get(vehicle)
                    if link not in network:
                        quality["unknown_link_events"] += 1
                    elif session is None:
                        quality["unattributed_link_entries"] += 1
                    else:
                        network_mode, owner, _ = session
                        active[vehicle] = (network_mode, owner, False)
                        pending[vehicle] = (link, time, network_mode, owner)
                        if network_mode in modes and start <= time < end:
                            stats[link].entered += 1
                elif kind == "left link":
                    entry = pending.pop(vehicle, None)
                    session = active.get(vehicle)
                    if entry is None:
                        partial = bool(session and session[2])
                        quality["partial_departure_link_exits" if partial else "unmatched_link_exits"] += 1
                        if partial:
                            active[vehicle] = (session[0], session[1], False)
                    else:
                        link, entered, network_mode, owner = entry
                        if link != attrs.get("link") or time < entered:
                            quality["invalid_traversals"] += 1
                        else:
                            if network_mode in modes and start <= entered < end:
                                travel = time - entered
                                stats[link].complete += 1
                                stats[link].travel += travel
                                stats[link].delay += travel - network[link]["freeflow_s"]
                            # Selection is route membership over the whole trip, not the entry window.
                            if link in selected and index is not None:
                                key = index.at(owner, entered)
                                if key is None:
                                    quality["selected_traversals_without_trip"] += 1
                                else:
                                    hits.add(key)
                elem.clear()
                root.clear()
    except ET.ParseError:
        raise ValueError("Malformed events artifact") from None
    quality["incomplete_link_entries"] += len(pending)
    return stats, hits, completion, dict(quality)


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    lower = math.floor(index)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[math.ceil(index)] * weight


def _sample(values: list[float]) -> dict:
    return {"count": len(values), "mean_s": statistics.fmean(values) if values else None,
            "p95_s": _percentile(values, .95)}


def _trip_summary(baseline: _Trips, proposal: _Trips, start: float, end: float,
                  mode: str, selected: set[str], hits: set) -> dict:
    def eligible(key: tuple, trip: _Trip) -> bool:
        return (trip.departure is not None and start <= trip.departure < end
                and trip.mode is not None and (mode == "all" or trip.mode == mode)
                and (not selected or key in hits))

    cohort = {key: trip for key, trip in baseline.rows.items() if eligible(key, trip)}
    left, right, deltas = [], [], []
    missing = duplicate = invalid = 0
    switches = Counter()
    for key, before in cohort.items():
        if key not in proposal.keys:
            missing += 1
            continue
        after = proposal.rows.get(key)
        if after is None:
            duplicate += 1
            continue
        if None in (before.duration, after.duration, after.departure, after.mode):
            invalid += 1
            continue
        left.append(before.duration)
        right.append(after.duration)
        deltas.append(after.duration - before.duration)
        if before.mode != after.mode:
            switches[before.mode, after.mode] += 1
    proposal_only = sum(key not in baseline.keys and eligible(key, trip)
                        for key, trip in proposal.rows.items())
    return {
        "cohort_basis": "baseline departure in [start_s,end_s), baseline main_mode (or single modes value when empty); paired means use identical trip keys",
        "selection_basis": "complete traversal of any selected link in either run over the entire trip" if selected else "all trips",
        "cohort_count": len(cohort), "paired_count": len(deltas),
        "faster_count": sum(delta <= -1 for delta in deltas),
        "slower_count": sum(delta >= 1 for delta in deltas),
        "within_1s_count": sum(abs(delta) < 1 for delta in deltas),
        "delta_s": {"mean": statistics.fmean(deltas) if deltas else None,
                    "median": statistics.median(deltas) if deltas else None,
                    "p95": _percentile(deltas, .95)},
        "baseline": _sample(left), "proposal": _sample(right),
        "unmatched": {"baseline_missing_in_proposal": missing,
                      "proposal_only_in_own_window": proposal_only,
                      "proposal_duplicate_keys_in_cohort": duplicate,
                      "invalid_pairs_in_cohort": invalid},
        "quality": {"baseline": baseline.quality, "proposal": proposal.quality},
        "mode_switch_count": sum(switches.values()),
        "mode_switches": [{"baseline_mode": a, "proposal_mode": b, "count": count}
                          for (a, b), count in sorted(switches.items())],
    }


def _bin(delta: float | None) -> str:
    if delta is None:
        return "unavailable"
    for key, _, lower, upper, lower_inclusive, upper_inclusive in _BIN_RANGES[:-1]:
        above = lower is None or delta > lower or (lower_inclusive and delta == lower)
        below = upper is None or delta < upper or (upper_inclusive and delta == upper)
        if above and below:
            return key
    raise ValueError("Non-finite link delta cannot be classified")


def _same_geometry(before: dict, after: dict) -> bool:
    return all(before[key] == after[key] for key in ("from", "to", "x1", "y1", "x2", "y2", "length_m"))


def _subsegment(piece: dict, original: dict) -> bool:
    """Conservative geometric evidence of splitting; no dependence on link-ID spelling."""
    if not 0 < piece["length_m"] < original["length_m"]:
        return False
    dx, dy = original["x2"] - original["x1"], original["y2"] - original["y1"]
    norm = dx * dx + dy * dy
    if norm == 0:
        return False
    fractions = []
    for x, y in ((piece["x1"], piece["y1"]), (piece["x2"], piece["y2"])):
        fraction = ((x - original["x1"]) * dx + (y - original["y1"]) * dy) / norm
        error = math.hypot(x - original["x1"] - fraction * dx, y - original["y1"] - fraction * dy)
        if not 0 <= fraction <= 1 or error > 1e-6:
            return False
        fractions.append(fraction)
    return (fractions[1] > fractions[0]
            and math.isclose(piece["length_m"], original["length_m"] * (fractions[1] - fractions[0]),
                             rel_tol=1e-9, abs_tol=1e-6))


def _link_rows(before: dict, after: dict, base_stats: dict, prop_stats: dict,
               available: bool, selected: set[str]) -> list[dict]:
    rows = []
    split_originals = [geometry for key, geometry in before.items()
                       if key in after and not _same_geometry(geometry, after[key])
                       and _subsegment(after[key], geometry)]
    for key in sorted(before.keys() | after.keys()):
        a, b = before.get(key), after.get(key)
        stats_a = base_stats.get(key, _LinkStats()).output() if a and available else None
        stats_b = prop_stats.get(key, _LinkStats()).output() if b and available else None
        comparable = bool(available and a and b and _same_geometry(a, b)
                          and stats_a["complete_traversal_count"] and stats_b["complete_traversal_count"])
        if a is None:
            state = "split" if any(_subsegment(b, old) for old in split_originals) else "new"
            reason = "link_absent_in_baseline"
        elif b is None:
            state, reason = "removed", "link_absent_in_proposal"
        elif not _same_geometry(a, b):
            state = "split" if _subsegment(b, a) else "geometry_changed"
            reason = "length_or_endpoints_changed"
        elif not available:
            state, reason = "unavailable", "teleported_mode_has_no_network_traversals"
        elif not comparable:
            state, reason = "no_data", "complete_traversals_required_in_both_runs"
        else:
            state, reason = "comparable", None
        fields = ("entered_count", "complete_traversal_count", "mean_travel_time_s", "mean_delay_s")
        delta = {field: stats_b[field] - stats_a[field] if comparable else None for field in fields}
        bin_name = _bin(delta["mean_travel_time_s"])
        geometry = b or a
        rows.append({"id": key, **{field: geometry[field] for field in ("from", "to", "x1", "y1", "x2", "y2")},
                     "baseline_geometry": a, "proposal_geometry": b,
                     "selected": key in selected, "state": state, "comparable": comparable,
                     "unavailable_reason": reason, "baseline": stats_a, "proposal": stats_b,
                     "delta": delta, "bin": bin_name, "color": list(_COLORS[bin_name])})
    return rows


def _link_summary(rows: list[dict], label: str, available: bool) -> dict:
    def aggregate(side: str) -> dict | None:
        if not available:
            return None
        samples = [row[side] for row in rows if row[side] is not None]
        count = sum(row["complete_traversal_count"] for row in samples)
        return {"entered_count": sum(row["entered_count"] for row in samples),
                "complete_traversal_count": count,
                **{field: sum((row[field] or 0) * row["complete_traversal_count"] for row in samples) / count
                   if count else None for field in ("mean_travel_time_s", "mean_delay_s")}}

    comparable = [row for row in rows if row["comparable"]]
    return {"label": label, "link_count": len(rows), "comparable_link_count": len(comparable),
            "states": dict(Counter(row["state"] for row in rows)),
            "bins": dict(Counter(row["bin"] for row in rows)),
            "baseline": aggregate("baseline"), "proposal": aggregate("proposal"),
            "delta": {"mean_link_travel_time_s": statistics.fmean(row["delta"]["mean_travel_time_s"] for row in comparable) if comparable else None,
                      "mean_link_delay_s": statistics.fmean(row["delta"]["mean_delay_s"] for row in comparable) if comparable else None},
            "aggregation": "side means weighted by complete traversals; deltas are unweighted means over comparable links only"}


def _artifacts(assets: dict) -> dict[str, Path]:
    sim_dir = Path(assets["sim_dir"])
    paths = {"plans": Path(assets["plans_file"]), "input_network": Path(assets["network_file"]),
             "config": sim_dir / "output_config.xml", "trips": sim_dir / "output_trips.csv.gz",
             "events": sim_dir / "output_events.xml.gz", "network": sim_dir / "output_network.xml.gz"}
    if not paths["network"].is_file():
        paths["network"] = sim_dir / "output_network.xml"
    if assets.get("record_path"):
        paths["record"] = Path(assets["record_path"])
    for path in paths.values():
        if not path.is_file():
            raise FileNotFoundError(f"Required impact artifact missing: {path.name}")
    return paths


def analyze_impact(baseline_run: str, proposal_run: str, start_s: float = 0,
                   end_s: float = 108000, mode: str = "car",
                   link_ids: list[str] | None = None) -> dict:
    """Compare evidence-checked runs. All signed deltas are proposal minus baseline.

    Window: finite 0 <= start < end <= 172800 seconds, half-open. Modes are
    car/bike/walk/pt/all. Up to 100 unique selected IDs must exist in either output
    network. Selection restricts trip and link summaries, never the map rows.
    Null means unavailable, never zero travel time or a fabricated improvement.
    """
    try:
        start, end = _number(start_s), _number(end_s)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Time window must contain finite seconds") from None
    if not 0 <= start < end <= 172800:
        raise ValueError("Require 0 <= start_s < end_s <= 172800")
    if not isinstance(mode, str) or mode not in _MODES:
        raise ValueError("Mode must be car, bike, walk, pt, or all")
    if link_ids is not None and (not isinstance(link_ids, list) or len(link_ids) > 100
                                or any(not isinstance(key, str) or not key for key in link_ids)):
        raise ValueError("link_ids must be a list of at most 100 nonempty link IDs")
    selected = set(link_ids or [])
    if len(selected) != len(link_ids or []):
        raise ValueError("Selected link IDs must be unique")
    if not isinstance(baseline_run, str) or not isinstance(proposal_run, str):
        raise ValueError("Run IDs must be strings")
    assets = {"baseline": resolve_run_assets(baseline_run), "proposal": resolve_run_assets(proposal_run)}
    paths = {side: _artifacts(value) for side, value in assets.items()}
    stamps = {path: (path.stat().st_size, path.stat().st_mtime_ns) for files in paths.values() for path in files.values()}
    configs = {side: _config(files["config"]) for side, files in paths.items()}
    if configs["baseline"][0] != configs["proposal"][0]:
        raise ValueError("Runs are not comparable: actual output configs differ beyond network input/output directory")
    for side, (_, params) in configs.items():
        sim_dir = Path(assets[side]["sim_dir"])
        _verify_input_path(params["plans", "inputPlansFile"], paths[side]["plans"], sim_dir)
        _verify_input_path(params["network", "inputNetworkFile"], paths[side]["input_network"], sim_dir)
    sources = {side: {name: file_evidence(path, checksum=True) for name, path in files.items()}
               for side, files in paths.items()}
    if sources["baseline"]["plans"]["sha256"] != sources["proposal"]["plans"]["sha256"]:
        raise ValueError("Runs are not comparable: actual input plans SHA-256 differs")
    networks = {side: _network(files["network"]) for side, files in paths.items()}
    if selected - (networks["baseline"].keys() | networks["proposal"].keys()):
        raise ValueError("Selected link IDs must exist in the baseline/proposal network union")
    trips = {side: _trips(files["trips"]) for side, files in paths.items()}
    network_modes = _NETWORK_MODES if mode == "all" else ({mode} & _NETWORK_MODES)
    events = {side: _events(files["events"], networks[side], trips[side], selected, network_modes, start, end)
              for side, files in paths.items()}
    trip_summary = _trip_summary(trips["baseline"], trips["proposal"], start, end, mode,
                                 selected, events["baseline"][1] | events["proposal"][1])
    available = bool(network_modes)
    rows = _link_rows(networks["baseline"], networks["proposal"], events["baseline"][0],
                      events["proposal"][0], available, selected)
    scope = [row for row in rows if not selected or row["selected"]]
    outside = [row for row in rows if selected and not row["selected"]]
    params = configs["baseline"][1]
    controller = "controler" if ("controler", "lastIteration") in params else "controller"
    normalized_sha = hashlib.sha256(
        json.dumps(configs["baseline"][0], ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()
    for path, stamp in stamps.items():
        if (path.stat().st_size, path.stat().st_mtime_ns) != stamp:
            raise ValueError("Run artifacts changed during impact analysis; retry with immutable completed runs")
    return {
        "schema_version": 1, "baseline_run": baseline_run, "proposal_run": proposal_run,
        "filters": {"start_s": start, "end_s": end, "mode": mode, "link_ids": sorted(selected)},
        "comparability": {"plans_sha256_equal": True, "normalized_config_equal": True,
                          "normalized_config_sha256": normalized_sha,
                          "ignored_config_parameters": ["network.inputNetworkFile", f"{controller}.outputDirectory"],
                          "random_seed": int(params["global", "randomSeed"]),
                          "first_iteration": int(params[controller, "firstIteration"]),
                          "last_iteration": int(params[controller, "lastIteration"])},
        "trips": trip_summary,
        "network": {"available": available, "modes": sorted(network_modes),
                    "label": "car + bike network traversals only" if mode == "all" else f"{mode} network traversals",
                    "unavailable_reason": None if available else "walk/pt are teleported; network link measures are unavailable",
                    "coordinate_system": params.get(("global", "coordinateSystem")), "coordinate_units": "network planar units (normally metres)",
                    "window_basis": "entered link time in [start_s,end_s); exit may be after end_s",
                    "delay_reference": "travel time minus length/freespeed from each run's actual output network; signed, not clipped",
                    "summary": _link_summary(scope, "selected links" if selected else "all links", available),
                    "outside_selection": _link_summary(outside, "outside selection", available),
                    "links": rows, "quality": {side: data[3] for side, data in events.items()}},
        "completion": {**{side: data[2] for side, data in events.items()},
                       "basis": "event times in [start_s,end_s), all people and all links; leg-event counts, not paired trip completion rates"},
        "sources": {side: {**data, "trip_headers": trips[side].headers} for side, data in sources.items()},
        "legend": [{"id": key, "label": label, "color": list(_COLORS[key]), "unit": "seconds",
                    "lower_s": lower, "upper_s": upper,
                    "lower_inclusive": lower_inclusive, "upper_inclusive": upper_inclusive,
                    "metric": "proposal minus baseline mean link travel time"}
                   for key, label, lower, upper, lower_inclusive, upper_inclusive in _BIN_RANGES],
        "limitations": [
            "Option screening of these simulation runs only; no calibration, causal forecast, or statistical confidence claim.",
            "Same input plans and configuration do not guarantee identical replanning outcomes or convergence; one seed pair is not uncertainty analysis.",
            "Paired trip keys use person + trip_number, not identical OD or routes; mode switches are retained and reported.",
            "Trips use baseline departure/main mode; proposal-only counts use their own window because no baseline departure exists.",
            "Invalid and duplicate trips are excluded, never assigned zero duration; table quality counts describe whole source files.",
            "Selected-link membership requires an observed complete car/bike traversal attributable to a trip interval in either run; unobserved/teleported routes cannot establish membership.",
            "Network statistics exclude departure/arrival partial links, unfinished traversals and parked gaps; entry counts can exceed complete traversals.",
            "Link deltas require identical IDs, lengths and directed endpoints, with complete traversals on both sides; geometry changes and absent observations have null deltas.",
            "Link delay uses each run's own length/freespeed, so a speed-limit change alters the reference; negative values may occur and this is not a measured congestion-only delay.",
            "All-mode network metrics include car and bike only; walk/pt network metrics are unavailable in this teleported-mode scenario.",
            "Outside selection means other links, not residential streets; no land-use exposure, emissions, safety, equity, or economic benefit is inferred.",
            "Mean link differences compare observed traversal populations, not paired drivers; p95 uses linear interpolation and zero-count statistics are null.",
        ],
    }
