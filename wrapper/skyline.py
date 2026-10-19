"""Turns MATSim's own output (output_events.xml.gz + output_network.xml.gz,
both already written by `simulate` into output/<sim>/) into a JSON scene for
an interactive 3D "city" viewer: roads are the literal skeleton (real
geometry, colored by actual congestion like a navigation app - green through
yellow/red/purple/black), with real landmarks (parks/libraries/tram lines)
and the ground itself following Melbourne's real terrain
(data/dem/fabdem_melbourne.tif, a bare-earth elevation model - see note
below on why not the more obvious Copernicus DEM). Uses rasterio for elevation
and projection, Shapely for polygon validation/clipping; rendering happens via
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
from rasterio.warp import transform as warp_transform, transform_bounds
from wrapper.landmark_geometry import project_clip_areas
from wrapper.building_geometry import prepare_buildings

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


def _absolute_severity(ratio: float) -> float:
    """Fixed display scale, not a traffic-engineering service-level standard."""
    stops = [(1, 0), (1.2, .35), (1.5, .55), (2, .72), (3, .88), (5, 1)]
    for (a, sa), (b, sb) in zip(stops, stops[1:]):
        if ratio <= b:
            return sa + max(0, (ratio-a)/(b-a)) * (sb-sa)
    return 1.0


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
                    "height_from_m": float(elem.findtext("attributes/attribute[@name='ifline:height_from']", '0')),
                    "height_to_m": float(elem.findtext("attributes/attribute[@name='ifline:height_to']", '0')),
                    "physical_width_m": float(elem.findtext("attributes/attribute[@name='ifline:width_m']", '0')),
                }
            # Custom link attributes must survive until their enclosing link
            # is read. Clearing every end event erased elevated-road metadata.
            if elem.tag in ('node','link'):
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


def landmark_cache_path(region_key: str, directory: Path | None = None) -> Path:
    directory = directory if directory is not None else LANDMARKS_DIR
    expanded = directory / "expanded" / f"{region_key}.json"
    if expanded.is_file():
        return expanded
    candidate = directory / "v2" / f"{region_key}.json"
    return candidate if candidate.is_file() else directory / f"{region_key}.json"


def _load_landmarks(region_key: str | None) -> dict | None:
    """Real OSM landmarks (parks/libraries/tram lines) for a region, pre-extracted
    once from the cached Victoria OSM PBF via scripts/extract_landmarks.py and
    cached to data/landmarks/expanded/<region_key>.json when available, then v2
    or legacy fallback - NOT re-scanned on every pipeline
    run (building its node-location index can take many minutes)."""
    if not region_key:
        return None
    path = landmark_cache_path(region_key)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def scene_native_bounds(coordinate_transform, terrain):
    """Authoritative displayed extent, including the terrain padding, in native CRS."""
    cx, cy = coordinate_transform['center_x'], coordinate_transform['center_y']
    scale = coordinate_transform['scene_units_per_metre']
    if not all(math.isfinite(v) for v in (cx, cy, scale)) or scale <= 0:
        raise ValueError('Invalid scene coordinate transform')
    bounds = (cx + terrain['min_x']/scale, cy + terrain['min_z']/scale,
              cx + terrain['max_x']/scale, cy + terrain['max_z']/scale)
    if not all(math.isfinite(v) for v in bounds) or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        raise ValueError('Invalid scene terrain extent')
    return bounds


def scene_geographic_bounds(coordinate_transform, terrain):
    """Return W/E/S/N, the cache/extractor convention (not GIS x0/y0/x1/y1)."""
    west, south, east, north = transform_bounds(
        coordinate_transform['network_crs'], 'EPSG:4326',
        *scene_native_bounds(coordinate_transform, terrain), densify_pts=21)
    return [west, east, south, north]


def landmark_coverage(raw, coordinate_transform, terrain):
    """Source *extent* coverage only; complete does not mean every building is mapped."""
    required = scene_geographic_bounds(coordinate_transform, terrain)
    metadata = raw.get('metadata')
    bounds = metadata.get('bounds') if isinstance(metadata, dict) else None
    valid = (isinstance(bounds, (list, tuple)) and len(bounds) == 4
             and all(isinstance(v, (int, float)) and math.isfinite(v) for v in bounds)
             and -180 <= bounds[0] < bounds[1] <= 180
             and -90 <= bounds[2] < bounds[3] <= 90)
    complete = valid and (bounds[0] <= required[0]+1e-9 and bounds[1] >= required[1]-1e-9
                         and bounds[2] <= required[2]+1e-9 and bounds[3] >= required[3]-1e-9)
    return {'status': 'complete' if complete else ('partial' if valid else 'unknown'),
            'source_bounds_wesn': bounds if valid else None,
            'required_bounds_wesn': required,
            'meaning': 'source extraction extent, not completeness or accuracy of OSM buildings'}


def _terrain_height(terrain, x, z):
    """Height on the exported terrain triangles (not a separate elevation)."""
    nx, nz = terrain["nx"], terrain["nz"]
    fx = max(0, min(nx - 1, (x - terrain["min_x"]) / (terrain["max_x"] - terrain["min_x"]) * (nx - 1)))
    fz = max(0, min(nz - 1, (z - terrain["min_z"]) / (terrain["max_z"] - terrain["min_z"]) * (nz - 1)))
    ix, iz = min(nx - 2, int(fx)), min(nz - 2, int(fz))
    tx, tz = fx - ix, fz - iz
    hs = terrain["heights"]
    a, b, c, d = hs[iz*nx+ix], hs[iz*nx+ix+1], hs[(iz+1)*nx+ix], hs[(iz+1)*nx+ix+1]
    return (a*(1-tx-tz)+b*tx+c*tz) if tx+tz <= 1 else (b*(1-tz)+c*(1-tx)+d*(tx+tz-1))


def scene_area_layers(raw, coordinate_transform, terrain):
    """Rebuild only visual polygons. Does not read/modify MATSim outputs.

    Also used by the explicit existing-replay refresh command, so old runs
    can get correct land polygons without recomputing any traffic metric.
    """
    raw = raw or {}
    cx, cy = coordinate_transform["center_x"], coordinate_transform["center_y"]
    scale = coordinate_transform["scene_units_per_metre"]
    bounds = scene_native_bounds(coordinate_transform, terrain)
    def convert(ring):
        # Preserve narrow rings/holes; the old 0.1-unit rounding could merge
        # neighbouring vertices and create self-intersections after repair.
        return [[round((x-cx)*scale, 5), round((y-cy)*scale, 5)] for x, y in ring.coords]
    layers, diagnostics = {}, {'coverage': landmark_coverage(raw, coordinate_transform, terrain)}
    for category, target in (("parks", "parks"), ("commercial", "commercial_zones"),
                             ("water", "water"), ("buildings", "buildings")):
        parts, stats = project_clip_areas(raw.get(category, []), bounds, "EPSG:4326",
                                          coordinate_transform["network_crs"])
        # Keep every valid footprint. A height-ranked global cap erased whole
        # low-rise neighbourhoods; renderer batching, not missing data, bounds draws.
        stats["omitted_by_limit"] = 0
        out = []
        for source, polygon, clipped in parts:
            point = polygon.representative_point()
            sx, sz = (point.x-cx)*scale, (point.y-cy)*scale
            item = {"points": convert(polygon.exterior),
                    "holes": [convert(ring) for ring in polygon.interiors],
                    "name": source.get("name", ""), "osm_id": source.get("osm_id"),
                    "clipped": clipped, "y": round(_terrain_height(terrain, sx, sz), 3)}
            if category == "buildings":
                kind, color = _visual_building_style(source)
                height = float(source.get("height", 9))
                if not math.isfinite(height) or height <= 0:
                    height = 9
                item.update(height=round(height*scale, 2), height_m=round(height, 1),
                            kind=kind, color=color, roof=source.get("roof", "flat"),
                            material=source.get("material", ""), heritage=bool(source.get("heritage")))
            out.append(item)
        layers[target] = out
        diagnostics[category] = stats
    return layers, diagnostics


def _area_labels(buildings):
    candidates = []
    for b in buildings:
        name = b["name"]
        normalized = " ".join(name.lower().split())
        important = bool(name and "car park" not in normalized and
                         any(term in normalized for term in WAYFINDING_LANDMARK_TERMS))
        if not name or (b["height_m"] < LANDMARK_LABEL_MIN_HEIGHT_M and not important):
            continue
        family = next((term for term in ("melbourne central", "eureka tower", "rialto",
            "101 collins", "flinders street station", "state library", "queen victoria market", "parliament")
            if term in normalized), normalized)
        candidates.append((important, b["height_m"], family, b))
    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    labels, seen = [], set()
    for _, _, family, b in candidates:
        if family in seen:
            continue
        seen.add(family)
        labels.append({"name": b["name"], "x": statistics.mean(p[0] for p in b["points"]),
                       "z": statistics.mean(p[1] for p in b["points"]), "y": b["y"] + b["height"]})
        if len(labels) >= MAX_LANDMARK_LABELS:
            break
    return labels


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
    # Fixed values across runs. A lightly loaded network may correctly have
    # no red roads; never stretch a rank to manufacture congestion.
    ratios: dict[str, float] = {}
    for link_id, times in travel_times.items():
        link = links.get(link_id)
        if not link or link["length"] <= 0 or link["freespeed"] <= 0:
            continue
        freeflow_time = link["length"] / link["freespeed"]
        if freeflow_time <= 0:
            continue
        ratios[link_id] = max(1.0, statistics.mean(times) / freeflow_time)

    severity_by_link = {key: _absolute_severity(value) for key, value in ratios.items()}

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
        modes = sorted(
            mode.strip() for mode in str(link.get("modes", "")).split(",")
            if mode.strip()
        )
        roads.append({
            "link_id": link_id,
            "x1": round(sx1, 1), "z1": round(sz1, 1),
            "x2": round(sx2, 1), "z2": round(sz2, 1),
            "y1": elev_to_scene_y(node_elev.get(link["from"], min_elev)),
            "y2": elev_to_scene_y(node_elev.get(link["to"], min_elev)),
            "width": round(width, 2),
            "height_from_m": link.get('height_from_m',0),
            "height_to_m": link.get('height_to_m',0),
            "physical_width_m": link.get('physical_width_m',0),
            "color": [round(c, 3) for c in color],
            "glow": round(glow, 2),
            "severity": None if sev is None else round(sev, 3),
            "travel_time_ratio": ratios.get(link_id),
            "volume": vol,
            "lanes": round(link["lanes"], 1),
            "oneway": link["oneway"],
            "modes": modes,
            "car_editable": "car" in modes,
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
                    keyframes.append([round(t0, 1), round(sx1, 1), round(y1, 2), round(sz1, 1), link.get('height_from_m',0)])
                keyframes.append([round(t1, 1), round(sx2, 1), round(y2, 2), round(sz2, 1), link.get('height_to_m',0)])
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

    # Polygon layers and line/point layers deliberately use separate paths.
    # Polygon intersection preserves enclosing/cross-boundary areas and holes.
    landmarks_raw = _load_landmarks(region_key) or {}
    transform = {"network_crs": NETWORK_CRS, "center_x": cx, "center_y": cy,
                 "scene_units_per_metre": scale}
    terrain = {"nx": TERRAIN_GRID_SIZE, "nz": TERRAIN_GRID_SIZE,
               "min_x": round(tsx0, 1), "max_x": round(tsx1, 1),
               "min_z": round(tsz0, 1), "max_z": round(tsz1, 1),
               "heights": terrain_heights}
    area_layers, area_diagnostics = scene_area_layers(landmarks_raw, transform, terrain)
    libraries_out, tram_lines_out = [], []
    lib_entries = landmarks_raw.get("libraries", [])
    tram_entries = landmarks_raw.get("tram_ways", [])
    coordinates = [(lib["lon"], lib["lat"]) for lib in lib_entries]
    coordinates += [tuple(c) for t in tram_entries for c in t["coords"]]
    if coordinates:
        native_xs, native_ys = warp_transform("EPSG:4326", NETWORK_CRS, *zip(*coordinates))
        elevations = _sample_elevations(native_xs, native_ys)
        def inside(i):
            return gx0 <= native_xs[i] <= gx1 and gy0 <= native_ys[i] <= gy1
        def point(i):
            sx, sz = to_scene(native_xs[i], native_ys[i])
            return round(sx, 1), round(sz, 1), elev_to_scene_y(elevations[i])
        for i, lib in enumerate(lib_entries):
            if inside(i):
                sx, sz, sy = point(i)
                libraries_out.append({"x": sx, "z": sz, "y": sy, "name": lib.get("name") or "图书馆"})
        offset = len(lib_entries)
        for t in tram_entries:
            for i in range(offset, offset + len(t["coords"]) - 1):
                if inside(i) and inside(i + 1):
                    x1, z1, y1 = point(i)
                    x2, z2, y2 = point(i + 1)
                    tram_lines_out.append(dict(x1=x1, z1=z1, y1=y1, x2=x2, z2=z2, y2=y2))
            offset += len(t["coords"])
    parks_out = area_layers["parks"]
    commercial_out = area_layers["commercial_zones"]
    buildings_out, building_diagnostics = prepare_buildings(area_layers["buildings"])
    landmark_labels = _area_labels(buildings_out)

    scene = {
        "traffic_metric": {"version": 2, "type": "fixed_travel_time_ratio",
                           "scope": "whole-run network traversals; car and bike combined",
                           "ratio_stops": [1, 1.2, 1.5, 2, 3, 5]},
        "coordinate_transform": {
            "network_crs": NETWORK_CRS,
            "center_x": cx,
            "center_y": cy,
            "scene_units_per_metre": scale,
        },
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
            "water": area_layers["water"],
            "libraries": libraries_out,
            "tram_lines": tram_lines_out,
            "commercial_zones": commercial_out,
            "buildings": buildings_out,
            "labels": landmark_labels,
        },
        "landmark_geometry_version": 2,
        "landmark_diagnostics": area_diagnostics,
        "building_geometry_version": 1,
        "building_diagnostics": building_diagnostics,
        "vehicles": vehicles_out,
        "sim_time_range": [min(all_times), max(all_times)] if all_times else [0, 86400],
        "sim_focus_time": sim_focus_time,
        "peak_active_vehicles": peak_active_vehicles,
        "total_volume": sum(volumes.values()),
    }
    scene_path = sim_dir / "skyline_scene.json"
    scene_path.write_text(json.dumps(scene))
    return scene_path
