"""Turns MATSim's own output (output_events.xml.gz + output_network.xml.gz,
both already written by `simulate` into output/<sim>/) into a JSON scene for
an interactive 3D "city" viewer: roads are the literal skeleton (real
geometry, colored by actual congestion like a navigation app - green through
yellow/red/purple/black), with real landmarks (parks/libraries/tram lines)
and the ground itself following Melbourne's real terrain
(data/dem/fabdem_melbourne.tif, a bare-earth elevation model - see note
below on why not the more obvious Copernicus DEM). Pure stdlib plus rasterio
for the elevation lookup - the actual 3D rendering happens client-side via
three.js, see wrapper/static/index.html.

Buildings are real OSM footprints (extruded to their real OSM height/levels,
or a plain default when OSM has neither - see scripts/extract_landmarks.py),
not the abstract traffic-volume-driven bar chart an earlier version used -
that version was removed once real per-vehicle car animation replaced
height-as-volume as the actual "how busy" signal, and was reintroduced in
its current real-footprint form once the user asked for genuine Melbourne
buildings back rather than the abstract proxy.

Elevation data note: Copernicus GLO-30 is a *surface* model (includes
buildings/trees), which made a random CBD test point read as 75m - a
building rooftop, not real ground height. FABDEM (data.bris.ac.uk /
huggingface.co/datasets/links-ads/fabdem-v12) strips buildings/vegetation
back out of the same Copernicus data, giving genuine bare-earth elevation -
confirmed against known Melbourne geography (Fitzroy/Carlton sit ~30-45m up,
Docklands/Southbank near the Yarra sit ~1-7m) before trusting it here.
"""

import gzip
import hashlib
import json
import math
import statistics
from pathlib import Path
from xml.etree import ElementTree as ET

import rasterio
from rasterio.warp import transform as warp_transform

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
DEM_PATH = PROJECT_ROOT / "data" / "dem" / "fabdem_melbourne.tif"
LANDMARKS_DIR = PROJECT_ROOT / "data" / "landmarks"
NETWORK_CRS = "EPSG:7899"  # GDA2020 / Vicgrid - what network.xml coordinates are in

SCENE_SPAN = 400.0  # scene units the network's wider axis is scaled to fit
ROAD_MIN_WIDTH = 1.8
ROAD_MAX_WIDTH = 7.2
TERRAIN_GRID_SIZE = 44  # vertices per side of the ground mesh
VERTICAL_EXAGGERATION = 3.5  # real Melbourne relief is gentle; needs exaggeration to read in a compact scene
MAX_BUILDINGS = 3000  # safety cap so a very dense area can't overwhelm the browser
LANDMARK_LABEL_MIN_HEIGHT_M = 20.0  # only label buildings tall/significant enough to actually serve as a wayfinding landmark
MAX_LANDMARK_LABELS = 10  # game-style map labels: recognizable, never a wall of text
WAYFINDING_LANDMARK_TERMS = (
    "melbourne central", "flinders street railway station", "flinders street station",
    "state library victoria", "royal exhibition building", "eureka tower",
    "rialto towers", "101 collins street", "queen victoria market", "parliament house",
)

# These are intentionally a visual zoning palette, not a claim that every
# sparse OSM ``building=yes`` record has a known cadastral use.  Explicit OSM
# categories are kept; uncategorised footprints are assigned a deterministic
# plausible style from height/name so the city remains readable at a glance.
BUILDING_PALETTES = {
    "residential": ("#aa6f5c", "#bd8065", "#c89570", "#986858", "#d0a17e"),
    "office": ("#4f7588", "#63899a", "#3f657b", "#7697a1", "#547d91"),
    "retail": ("#c28b42", "#d19f50", "#ad743b", "#d4ae64", "#b9854f"),
    "civic": ("#a99773", "#b9a47c", "#938467", "#c2ad86", "#9d8969"),
    "industrial": ("#687972", "#7f8b80", "#5e706b", "#8b9488", "#70817a"),
}


def _stable_building_fraction(coords: list[list[float]] | list[tuple[float, float]], salt: str = "") -> float:
    if not coords:
        return 0.0
    key = f"{coords[0][0]:.6f},{coords[0][1]:.6f}:{salt}"
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def _visual_building_style(building: dict) -> tuple[str, str]:
    """Return a legible game-style use category and colour.

    OSM has useful tags for only a minority of footprints.  The remaining
    generic footprints are deliberately *visually inferred* rather than all
    rendered as one anonymous beige mass.  This is presentation metadata;
    footprint and height still come from the real source data.
    """
    kind = building.get("kind", "generic")
    height_m = float(building.get("height", 9) or 9)
    name = building.get("name", "").lower()
    coords = building.get("coords", [])

    if kind == "generic":
        if any(term in name for term in (
                "library", "university", "school", "church", "cathedral",
                "station", "museum", "theatre", "parliament", "hospital")):
            kind = "civic"
        elif any(term in name for term in ("market", "mall", "arcade", "centre", "center")):
            kind = "retail"
        elif height_m >= 36:
            kind = "office"
        else:
            roll = _stable_building_fraction(coords, "use")
            if height_m >= 18:
                kind = "office" if roll < 0.58 else ("residential" if roll < 0.84 else "retail")
            else:
                kind = "residential" if roll < 0.56 else ("retail" if roll < 0.78 else "office")

    palette = BUILDING_PALETTES.get(kind, BUILDING_PALETTES["residential"])
    index = min(len(palette) - 1, int(_stable_building_fraction(coords, "colour") * len(palette)))
    return kind, palette[index]

# Congestion color ramp: free-flowing (near-white, like a plain map road) ->
# slow (yellow/orange) -> jammed (red) -> gridlocked (purple/black), same
# visual language as everyday navigation apps. Free-flow was originally
# green, but that reads with too little contrast against the (also green)
# terrain, and forcing every ordinary road to a saturated color made the
# whole scene look busier/less trustworthy than the actual (usually mild)
# congestion data - white is the honest "nothing to see here" neutral.
# Colors are muted/desaturated (blended toward neutral gray) rather than
# fully saturated - full saturation next to white/light-gray roads and a
# light terrain read as gaudy rather than like a real map.
COLOR_STOPS = [
    (0.00, (0.24, 0.68, 0.35)),   # navigation green - free flow
    (0.35, (0.90, 0.72, 0.16)),   # clear yellow - slow
    (0.55, (0.93, 0.45, 0.14)),   # orange
    (0.72, (0.84, 0.19, 0.21)),   # red
    (0.88, (0.48, 0.18, 0.58)),   # purple
    (1.00, (0.12, 0.08, 0.12)),   # charcoal-maroon - gridlock (kept away
                                  # from true black, which would vanish
                                  # against the scene's dark background/fog)
]
UNUSED_COLOR = (0.63, 0.65, 0.64)  # neutral gray: the road exists but carries no simulated car


def _congestion_color(severity: float) -> tuple[float, float, float]:
    severity = max(0.0, min(1.0, severity))
    for (s0, c0), (s1, c1) in zip(COLOR_STOPS, COLOR_STOPS[1:]):
        if severity <= s1:
            t = (severity - s0) / (s1 - s0) if s1 > s0 else 0.0
            return tuple(round(c0[i] + (c1[i] - c0[i]) * t, 3) for i in range(3))
    return COLOR_STOPS[-1][1]


def _parse_events(sim_dir: Path) -> tuple[dict[str, int], dict[str, list[float]]]:
    """Single pass over output_events.xml.gz: counts "entered link" per link
    (volume, drives building height) and pairs entered/left link events per
    vehicle to get actual per-traversal travel times (drives congestion).

    A vehicle that arrives and parks on a link (ends its trip there, e.g. to
    do an activity) gets "entered link" + "vehicle leaves traffic" but NO
    matching "left link" for that arrival - the real "left link" only fires
    much later when the *next* trip actually drives away from that same
    link. Without clearing the pending entry on "vehicle leaves traffic",
    that later "left link" would wrongly pair with the stale entry-time from
    hours earlier, reading as a multi-hour "congested" traversal that's
    really just the parked/activity duration. Confirmed by inspecting a
    demo run's raw events: a ~44m link showed a 6275s "travel time" that was
    actually a work-activity gap between two unrelated trips."""
    volumes: dict[str, int] = {}
    travel_times: dict[str, list[float]] = {}
    pending: dict[str, tuple[str, float]] = {}  # vehicle -> (link, entry_time)

    with gzip.open(sim_dir / "output_events.xml.gz", "rt") as f:
        for _, elem in ET.iterparse(f, events=("end",)):
            if elem.tag != "event":
                elem.clear()
                continue
            etype = elem.get("type")
            if etype == "entered link":
                link_id = elem.get("link")
                vehicle = elem.get("vehicle")
                volumes[link_id] = volumes.get(link_id, 0) + 1
                pending[vehicle] = (link_id, float(elem.get("time")))
            elif etype == "left link":
                vehicle = elem.get("vehicle")
                entry = pending.pop(vehicle, None)
                if entry is not None and entry[0] == elem.get("link"):
                    duration = float(elem.get("time")) - entry[1]
                    if duration > 0:
                        travel_times.setdefault(entry[0], []).append(duration)
            elif etype == "vehicle leaves traffic":
                pending.pop(elem.get("vehicle"), None)
            elif etype == "vehicle enters traffic":
                # Establishes a fresh baseline for this link (the vehicle was
                # already parked here) so the next "left link" measures the
                # real, short handoff rather than reaching back to a stale entry.
                pending[elem.get("vehicle")] = (elem.get("link"), float(elem.get("time")))
            elem.clear()

    return volumes, travel_times


def _vehicle_trip_segments(sim_dir: Path) -> dict[str, list[list[tuple[float, str]]]]:
    """Per car vehicle (networkMode == "car" only - bikes/pt use the same
    network events but the user specifically asked for car models), the
    list of real driven trips; each trip is an ordered list of (time,
    link_id) samples marking when the vehicle started traversing each link
    ("vehicle enters traffic" then each "entered link"), ending with the
    "vehicle leaves traffic" sample. A new trip starts after every park -
    keeps a parked gap (which can be hours, see _parse_events' docstring)
    from being animated as if the car were continuously driving through it."""
    trips: dict[str, list[list[tuple[float, str]]]] = {}
    current: dict[str, list[tuple[float, str]]] = {}
    is_car: dict[str, bool] = {}

    with gzip.open(sim_dir / "output_events.xml.gz", "rt") as f:
        for _, elem in ET.iterparse(f, events=("end",)):
            if elem.tag != "event":
                elem.clear()
                continue
            etype = elem.get("type")
            vehicle = elem.get("vehicle")
            if etype == "vehicle enters traffic":
                is_car[vehicle] = elem.get("networkMode") == "car"
                if is_car[vehicle]:
                    current[vehicle] = [(float(elem.get("time")), elem.get("link"))]
            elif etype == "entered link" and vehicle in current:
                current[vehicle].append((float(elem.get("time")), elem.get("link")))
            elif etype == "vehicle leaves traffic" and vehicle in current:
                current[vehicle].append((float(elem.get("time")), elem.get("link")))
                trip = current.pop(vehicle)
                if len(trip) >= 2:
                    trips.setdefault(vehicle, []).append(trip)
            elem.clear()

    return trips


def _network_data(sim_dir: Path) -> tuple[dict[str, tuple[float, float]], dict[str, dict]]:
    """MATSim writes a copy of the network it actually simulated on into the
    sim output dir, so we don't need a separate path to the network/ output.
    Returns node coordinates plus the physical link fields needed to draw a
    stable road hierarchy.  Road width must come from lanes/capacity, not from
    congestion: traffic is a changing overlay, while the street itself is not.
    """
    nodes: dict[str, tuple[float, float]] = {}
    raw_links: dict[str, dict] = {}
    with gzip.open(sim_dir / "output_network.xml.gz", "rt") as f:
        for _, elem in ET.iterparse(f, events=("end",)):
            if elem.tag == "node":
                nodes[elem.get("id")] = (float(elem.get("x")), float(elem.get("y")))
            elif elem.tag == "link":
                raw_links[elem.get("id")] = {
                    "from": elem.get("from"),
                    "to": elem.get("to"),
                    "length": float(elem.get("length", 0) or 0),
                    "freespeed": float(elem.get("freespeed", 0) or 0),
                    "capacity": float(elem.get("capacity", 0) or 0),
                    "lanes": float(elem.get("permlanes", 1) or 1),
                    "oneway": elem.get("oneway", "1") == "1",
                    "modes": elem.get("modes", ""),
                }
            elem.clear()

    links = {}
    for link_id, attrs in raw_links.items():
        if attrs["from"] in nodes and attrs["to"] in nodes:
            x1, y1 = nodes[attrs["from"]]
            x2, y2 = nodes[attrs["to"]]
            links[link_id] = {**attrs, "x1": x1, "y1": y1, "x2": x2, "y2": y2}
    return nodes, links


def _sample_elevations(xs_native: list[float], ys_native: list[float]) -> list[float]:
    """Bare-earth elevation (meters, AHD) for a batch of native-CRS points."""
    lons, lats = warp_transform(NETWORK_CRS, "EPSG:4326", xs_native, ys_native)
    with rasterio.open(DEM_PATH) as src:
        return [float(v[0]) for v in src.sample(zip(lons, lats))]


def _load_landmarks(region_key: str | None) -> dict | None:
    """Real OSM landmarks (parks/libraries/tram lines) for a region, pre-extracted
    once from the cached Victoria OSM PBF via scripts/extract_landmarks.py and
    cached to data/landmarks/<region_key>.json - NOT re-scanned on every pipeline
    run (building its node-location index can take many minutes)."""
    if not region_key:
        return None
    path = LANDMARKS_DIR / f"{region_key}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def render_skyline_scene(sim_output_subdir: str, region_key: str | None = None) -> Path:
    sim_dir = OUTPUT_DIR / sim_output_subdir
    volumes, travel_times = _parse_events(sim_dir)
    nodes, links = _network_data(sim_dir)

    xs = [c for l in links.values() for c in (l["x1"], l["x2"])]
    ys = [c for l in links.values() for c in (l["y1"], l["y2"])]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span = max(max_x - min_x, max_y - min_y) or 1.0
    scale = SCENE_SPAN / span
    cx, cy = (min_x + max_x) / 2, (min_y + max_y) / 2

    def to_scene(x: float, y: float) -> tuple[float, float]:
        # network x/y -> scene x/z (three.js convention: y is up, ground is x/z)
        return (x - cx) * scale, (y - cy) * scale

    # --- real terrain -------------------------------------------------
    node_ids = list(nodes.keys())
    node_elevs_raw = _sample_elevations([nodes[n][0] for n in node_ids], [nodes[n][1] for n in node_ids])
    node_elev = dict(zip(node_ids, node_elevs_raw))
    valid_elevs = [e for e in node_elev.values() if e > -1000]  # DEM nodata sentinel guard
    min_elev = min(valid_elevs) if valid_elevs else 0.0

    def elev_to_scene_y(e: float) -> float:
        if e <= -1000:  # nodata - treat as sea-level-ish rather than a deep pit
            e = min_elev
        return round((e - min_elev) * scale * VERTICAL_EXAGGERATION, 2)

    pad = span * 0.08
    gx0, gx1 = min_x - pad, max_x + pad
    gy0, gy1 = min_y - pad, max_y + pad
    grid_xs = [gx0 + i * (gx1 - gx0) / (TERRAIN_GRID_SIZE - 1) for i in range(TERRAIN_GRID_SIZE)]
    grid_ys = [gy0 + j * (gy1 - gy0) / (TERRAIN_GRID_SIZE - 1) for j in range(TERRAIN_GRID_SIZE)]
    flat_xs = [x for _ in grid_ys for x in grid_xs]
    flat_ys = [y for y in grid_ys for _ in grid_xs]
    terrain_elevs_raw = _sample_elevations(flat_xs, flat_ys)
    terrain_heights = [elev_to_scene_y(e) for e in terrain_elevs_raw]
    tsx0, tsz0 = to_scene(gx0, gy0)
    tsx1, tsz1 = to_scene(gx1, gy1)

    # --- congestion -----------------------------------------------------
    # Actual avg travel time vs free-flow time, for the subset of links that
    # actually carry through-traffic (most links in a small demo carry none
    # at all - that's real, not a bug: see below).
    #
    # Severity is a *rank-based* stratification: sort all links that carry
    # any traffic by their ratio and spread them evenly across the full 0-1
    # severity range by rank, not by raw value. A min-max *value* stretch
    # (previous version) preserves the shape of the underlying distribution -
    # when most ratios cluster tightly near the low end with one or two far
    # outliers (typical for a lightly-loaded demo), that leaves nearly every
    # link crammed near severity 0 and only a literal handful of links ever
    # reaching yellow/red/purple, which is too faint/rare to actually see on
    # the map. Rank-based spreading guarantees every color band gets a
    # visible, meaningful share of roads regardless of the underlying value
    # distribution - this is explicitly a *relative* "busier than other
    # streets in this same run" indicator, not an absolute engineering
    # severity threshold (documented here since that's a real, deliberate
    # tradeoff, not an oversight).
    ratios: dict[str, float] = {}
    for link_id, times in travel_times.items():
        link = links.get(link_id)
        if not link or link["length"] <= 0 or link["freespeed"] <= 0:
            continue
        freeflow_time = link["length"] / link["freespeed"]
        if freeflow_time <= 0:
            continue
        ratios[link_id] = max(1.0, statistics.mean(times) / freeflow_time)

    severity_by_link: dict[str, float] = {}
    if ratios:
        ranked = sorted(ratios.items(), key=lambda kv: kv[1])
        n = len(ranked)
        for i, (link_id, _) in enumerate(ranked):
            severity_by_link[link_id] = i / (n - 1) if n > 1 else 0.0

    def severity_of(link_id: str) -> float | None:
        return severity_by_link.get(link_id) if link_id in ratios else None

    # --- roads: the literal skeleton --------------------------------
    roads = []
    for link_id, link in links.items():
        sx1, sz1 = to_scene(link["x1"], link["y1"])
        sx2, sz2 = to_scene(link["x2"], link["y2"])
        vol = volumes.get(link_id, 0)
        sev = severity_of(link_id)
        color = UNUSED_COLOR if sev is None else _congestion_color(sev)
        glow = 0.0 if sev is None else 0.14 + max(0.0, min(1.0, sev)) * 0.24
        # Physical road hierarchy is stable.  Congestion is rendered by the
        # frontend as a separate narrow navigation-style ribbon on top.
        lane_fraction = min(1.0, max(0.0, (link["lanes"] - 0.5) / 3.5))
        capacity_fraction = min(1.0, link["capacity"] / 6000.0)
        hierarchy = min(1.0, lane_fraction * 0.78 + capacity_fraction * 0.22)
        width = ROAD_MIN_WIDTH + hierarchy * (ROAD_MAX_WIDTH - ROAD_MIN_WIDTH)
        roads.append({
            "x1": round(sx1, 1), "z1": round(sz1, 1),
            "x2": round(sx2, 1), "z2": round(sz2, 1),
            "y1": elev_to_scene_y(node_elev.get(link["from"], min_elev)),
            "y2": elev_to_scene_y(node_elev.get(link["to"], min_elev)),
            "width": round(width, 2),
            "color": [round(c, 3) for c in color],
            "glow": round(glow, 2),
            "severity": None if sev is None else round(sev, 3),
            "volume": vol,
            "lanes": round(link["lanes"], 1),
            "oneway": link["oneway"],
        })

    # --- real car trajectories, for playback-driven animation ------------
    # Real MATSim-simulated positions over time, not a decorative loop - the
    # frontend interpolates each vehicle's position between these keyframes
    # at whatever the current playback time is, and simply doesn't render a
    # vehicle whose current trip doesn't cover that time (parked/inactive).
    vehicle_trips = _vehicle_trip_segments(sim_dir)
    vehicles_out = []
    all_times = []
    vehicle_activity_edges = []
    for vehicle, trip_list in vehicle_trips.items():
        trips_out = []
        for trip in trip_list:
            keyframes = []
            for i in range(len(trip) - 1):
                t0, link_id = trip[i]
                t1, _ = trip[i + 1]
                link = links.get(link_id)
                if not link:
                    continue
                sx1, sz1 = to_scene(link["x1"], link["y1"])
                sx2, sz2 = to_scene(link["x2"], link["y2"])
                y1 = elev_to_scene_y(node_elev.get(link["from"], min_elev))
                y2 = elev_to_scene_y(node_elev.get(link["to"], min_elev))
                if not keyframes:
                    keyframes.append([round(t0, 1), round(sx1, 1), round(y1, 2), round(sz1, 1)])
                keyframes.append([round(t1, 1), round(sx2, 1), round(y2, 2), round(sz2, 1)])
            if len(keyframes) >= 2:
                trips_out.append(keyframes)
                all_times.append(keyframes[0][0])
                all_times.append(keyframes[-1][0])
                vehicle_activity_edges.append((keyframes[0][0], 1))
                vehicle_activity_edges.append((keyframes[-1][0], -1))
        if trips_out:
            vehicles_out.append({"trips": trips_out})

    active_vehicles = peak_active_vehicles = 0
    sim_focus_time = min(all_times) if all_times else 0
    # Starts are processed before finishes at the same timestamp so a short
    # real trip is still visible at its departure instant.
    for event_time, delta in sorted(vehicle_activity_edges, key=lambda edge: (edge[0], -edge[1])):
        active_vehicles += delta
        if active_vehicles > peak_active_vehicles:
            peak_active_vehicles = active_vehicles
            sim_focus_time = event_time

    # --- real landmarks (parks / libraries / tram lines) -----------------
    # Genuine OSM features, not invented - see _load_landmarks()'s docstring
    # for how/where this was extracted from.
    landmarks_raw = _load_landmarks(region_key)
    parks_out, libraries_out, tram_lines_out, commercial_out = [], [], [], []
    if landmarks_raw:
        lons_all, lats_all = [], []
        for p in landmarks_raw.get("parks", []):
            lons_all.extend(c[0] for c in p["coords"])
            lats_all.extend(c[1] for c in p["coords"])
        for lib in landmarks_raw.get("libraries", []):
            lons_all.append(lib["lon"])
            lats_all.append(lib["lat"])
        for t in landmarks_raw.get("tram_ways", []):
            lons_all.extend(c[0] for c in t["coords"])
            lats_all.extend(c[1] for c in t["coords"])
        for zone in landmarks_raw.get("commercial", []):
            lons_all.extend(c[0] for c in zone["coords"])
            lats_all.extend(c[1] for c in zone["coords"])

        if lons_all:
            native_xs, native_ys = warp_transform("EPSG:4326", NETWORK_CRS, lons_all, lats_all)
            i = 0

            def next_native(count: int) -> list[tuple[float, float]]:
                nonlocal i
                pts = list(zip(native_xs[i:i + count], native_ys[i:i + count]))
                i += count
                return pts

            def in_bounds(x: float, y: float) -> bool:
                return gx0 <= x <= gx1 and gy0 <= y <= gy1

            # Two-pass: first work out which features are in-bounds and what
            # points need elevation, then do exactly ONE _sample_elevations
            # call for all of them (each call reopens+reads the DEM file -
            # doing that per-feature for hundreds of tram vertices would be
            # needlessly slow).
            #
            # Real Melbourne tram routes run for many km, far outside this
            # small CBD scene - a way that just barely clips the region
            # still has most of its points many km away. Including such a
            # way *wholesale* (the original "any point in bounds" check)
            # meant those far-away points got converted to scene coordinates
            # and elevations using this scene's local scale/exaggeration,
            # producing absurd stretched lines shooting far outside (and,
            # since elevation differences also get scaled up, sometimes
            # straight up into the sky). Fixed by requiring BOTH endpoints
            # of each individual line *segment* to be in-bounds, not just
            # "the way touches the box somewhere" - this naturally clips a
            # long route down to just its portion actually inside the scene.
            park_pts_list, lib_pts = [], []
            for p in landmarks_raw.get("parks", []):
                pts = next_native(len(p["coords"]))
                if all(in_bounds(x, y) for x, y in pts):
                    park_pts_list.append(pts)
            for lib in landmarks_raw.get("libraries", []):
                (pt,) = next_native(1)
                if in_bounds(*pt):
                    lib_pts.append((pt, lib.get("name") or "图书馆"))
            tram_segments = []  # list of (x1,y1,x2,y2) native-CRS pairs, pre-clipped
            for t in landmarks_raw.get("tram_ways", []):
                pts = next_native(len(t["coords"]))
                for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                    if in_bounds(x1, y1) and in_bounds(x2, y2):
                        tram_segments.append((x1, y1, x2, y2))
            commercial_pts_list = []
            for zone in landmarks_raw.get("commercial", []):
                pts = next_native(len(zone["coords"]))
                if len(pts) >= 3 and all(in_bounds(x, y) for x, y in pts):
                    commercial_pts_list.append(pts)

            elev_query_xs, elev_query_ys = [], []
            for pts in park_pts_list:
                cx_p, cy_p = statistics.mean(x for x, _ in pts), statistics.mean(y for _, y in pts)
                elev_query_xs.append(cx_p)
                elev_query_ys.append(cy_p)
            for pt, _ in lib_pts:
                elev_query_xs.append(pt[0])
                elev_query_ys.append(pt[1])
            for x1, y1, x2, y2 in tram_segments:
                elev_query_xs.extend([x1, x2])
                elev_query_ys.extend([y1, y2])

            all_elevs = _sample_elevations(elev_query_xs, elev_query_ys) if elev_query_xs else []
            ei = 0

            for pts in park_pts_list:
                base_y = elev_to_scene_y(all_elevs[ei]); ei += 1
                parks_out.append({
                    "points": [[round(v, 1) for v in to_scene(x, y)] for x, y in pts],
                    "y": base_y + 0.3,
                })

            for pt, name in lib_pts:
                sx, sz = to_scene(*pt)
                base_y = elev_to_scene_y(all_elevs[ei]); ei += 1
                libraries_out.append({"x": round(sx, 1), "z": round(sz, 1), "y": base_y, "name": name})

            for x1, y1, x2, y2 in tram_segments:
                e1, e2 = all_elevs[ei], all_elevs[ei + 1]
                ei += 2
                sx1, sz1 = to_scene(x1, y1)
                sx2, sz2 = to_scene(x2, y2)
                tram_lines_out.append({
                    "x1": round(sx1, 1), "z1": round(sz1, 1), "y1": elev_to_scene_y(e1),
                    "x2": round(sx2, 1), "z2": round(sz2, 1), "y2": elev_to_scene_y(e2),
                })

            for pts in commercial_pts_list:
                commercial_out.append({
                    "points": [[round(v, 1) for v in to_scene(x, y)] for x, y in pts],
                })

    # --- real building footprints -----------------------------------------
    # Genuine OSM building outlines/heights (scripts/extract_landmarks.py),
    # not the abstract traffic-volume bar chart an earlier version used.
    buildings_out = []
    landmark_labels = []
    if landmarks_raw:
        building_entries = landmarks_raw.get("buildings", [])
        if building_entries:
            bd_lons, bd_lats = [], []
            for b in building_entries:
                bd_lons.extend(c[0] for c in b["coords"])
                bd_lats.extend(c[1] for c in b["coords"])
            bd_native_xs, bd_native_ys = warp_transform("EPSG:4326", NETWORK_CRS, bd_lons, bd_lats)
            bd_i = 0
            candidates = []  # (native_pts, height_m, color_hex, name, kind, roof, material, heritage)
            for b in building_entries:
                n = len(b["coords"])
                pts = list(zip(bd_native_xs[bd_i:bd_i + n], bd_native_ys[bd_i:bd_i + n]))
                bd_i += n
                # Same "fully in-bounds" rule as parks: a footprint cropped at
                # the scene edge would render as a broken partial shape.
                if all(gx0 <= x <= gx1 and gy0 <= y <= gy1 for x, y in pts):
                    visual_kind, visual_color = _visual_building_style(b)
                    candidates.append((
                        pts, b["height"], visual_color, b.get("name", ""),
                        visual_kind, b.get("roof", "flat"),
                        b.get("material", ""), bool(b.get("heritage", False)),
                    ))

            if len(candidates) > MAX_BUILDINGS:
                # Prefer keeping the tallest buildings over the largest
                # footprints - a real skyline reads by height, and ranking
                # by footprint area instead would keep sprawling low sheds
                # (e.g. market buildings) over genuine towers.
                candidates.sort(key=lambda item: item[1], reverse=True)
                candidates = candidates[:MAX_BUILDINGS]

            bd_elev_xs, bd_elev_ys = [], []
            for pts, *_ in candidates:
                bd_elev_xs.append(statistics.mean(x for x, _ in pts))
                bd_elev_ys.append(statistics.mean(y for _, y in pts))
            bd_elevs = _sample_elevations(bd_elev_xs, bd_elev_ys) if bd_elev_xs else []

            # Real named landmarks (e.g. "Melbourne Central office tower")
            # tall enough to actually serve as a wayfinding reference - a
            # user orbiting the scene has no other way to tell which
            # building is which real place, so the tallest/most-recognizable
            # ones get a floating name label client-side (capped so this
            # doesn't turn into a name for every single building).
            label_candidates = []  # (important, height_m, name, scene_x, scene_z, top_y)
            for (pts, height_m, color, name, kind, roof, material, heritage), elev in zip(candidates, bd_elevs):
                scene_pts = [[round(v, 1) for v in to_scene(x, y)] for x, y in pts]
                height_scene = round(height_m * scale, 2)
                base_y = elev_to_scene_y(elev)
                buildings_out.append({
                    "points": scene_pts,
                    # Real height at the scene's own horizontal scale, no
                    # vertical exaggeration - unlike terrain relief (too
                    # gentle to read without it), building heights are
                    # already visually significant at true proportions.
                    "height": height_scene,
                    # Real, unscaled meters - lets the frontend pick
                    # architectural detail (tiered crowns, spires) by actual
                    # real-world height rather than a scene-scale-dependent
                    # threshold, which wouldn't be portable across regions
                    # with different scale factors.
                    "height_m": round(height_m, 1),
                    "y": base_y,
                    # Real OSM building:colour tag, RMIT's actual brand red for
                    # RMIT-operated buildings, or a real-building-type-driven
                    # tone (office/retail/residential/etc) - see
                    # scripts/extract_landmarks.py's _building_color().
                    "color": color,
                    "kind": kind,
                    "roof": roof,
                    "material": material,
                    "heritage": heritage,
                    "name": name,
                })
                important = bool(
                    name and "car park" not in name.lower()
                    and any(term in name.lower() for term in WAYFINDING_LANDMARK_TERMS)
                )
                if name and (height_m >= LANDMARK_LABEL_MIN_HEIGHT_M or important):
                    # NOTE: deliberately not named cx/cz - render_skyline_scene's
                    # own `cx`/`cy` (the scene-center offset) are captured by
                    # the `to_scene()` closure used everywhere in this
                    # function; reassigning those names here silently corrupts
                    # every to_scene() call for the rest of the function (this
                    # was a real bug, caught by noticing building coordinates
                    # after this point ranged up to ~470000 instead of the
                    # expected -200..200 scene span).
                    label_x = statistics.mean(p[0] for p in scene_pts)
                    label_z = statistics.mean(p[1] for p in scene_pts)
                    label_candidates.append((important, height_m, name, label_x, label_z, base_y + height_scene))

            label_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
            seen_names = set()
            seen_families = set()
            for _, _, name, lx, lz, top_y in label_candidates:
                normalized = " ".join(name.lower().split())
                family = normalized
                for landmark_family in (
                        "melbourne central", "eureka tower", "rialto",
                        "101 collins", "flinders street station",
                        "state library", "queen victoria market", "parliament"):
                    if landmark_family in normalized:
                        family = landmark_family
                        break
                if normalized in seen_names or family in seen_families or "car park" in normalized:
                    continue
                seen_names.add(normalized)
                seen_families.add(family)
                landmark_labels.append({
                    "name": name, "x": lx, "z": lz, "y": round(top_y, 2),
                })
                if len(landmark_labels) >= MAX_LANDMARK_LABELS:
                    break

    scene = {
        "roads": roads,
        "terrain": {
            "nx": TERRAIN_GRID_SIZE,
            "nz": TERRAIN_GRID_SIZE,
            "min_x": round(tsx0, 1), "max_x": round(tsx1, 1),
            "min_z": round(tsz0, 1), "max_z": round(tsz1, 1),
            "heights": terrain_heights,
        },
        "landmarks": {
            "parks": parks_out,
            "libraries": libraries_out,
            "tram_lines": tram_lines_out,
            "commercial_zones": commercial_out,
            "buildings": buildings_out,
            "labels": landmark_labels,
        },
        "vehicles": vehicles_out,
        "sim_time_range": [min(all_times), max(all_times)] if all_times else [0, 86400],
        "sim_focus_time": sim_focus_time,
        "peak_active_vehicles": peak_active_vehicles,
        "total_volume": sum(volumes.values()),
    }
    scene_path = sim_dir / "skyline_scene.json"
    scene_path.write_text(json.dumps(scene))
    return scene_path
