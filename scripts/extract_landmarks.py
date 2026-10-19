"""One-off data-prep script: pulls real landmarks (parks, libraries, tram
lines, commercial/retail zones, building footprints) out of the cached
Victoria OSM extract (data/geofabrik_victoria-latest.osm.pbf) for a given
region's bounding box, and caches the result to data/landmarks/v2/<region_key>.json.
Closed ways and multipolygon relations include interior rings; water is included.

Run manually whenever a new region needs landmarks - NOT run automatically
by the pipeline (building the node-location index for the 236MB PBF can take
many minutes even with a bbox filter, which is too slow to redo on every
simulation run for data that rarely changes between runs of the same region).

Usage:
    python3 scripts/extract_landmarks.py --all

or for one custom bounding box:
    python3 scripts/extract_landmarks.py cbd 144.945 144.978 -37.832 -37.802
                                          ^region_key  ^min_lon ^max_lon ^min_lat ^max_lat

For an expanded displayed network (keeps old v2 caches intact):
    python3 scripts/extract_landmarks.py --scene RUN_sim --region cbd
Bounds come from that scene's full terrain extent, not the old population bbox.
"""

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import osmium

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PBF_PATH = PROJECT_ROOT / "data" / "geofabrik_victoria-latest.osm.pbf"
LANDMARKS_DIR = PROJECT_ROOT / "data" / "landmarks"
# Keep legacy caches intact. Only a successful extraction publishes v2 caches.
LANDMARKS_DIR = LANDMARKS_DIR / "v2"
sys.path.insert(0, str(PROJECT_ROOT))
from wrapper.landmark_geometry import project_clip_areas
from shapely.geometry import LineString, box

PRESET_REGION_FILES = {
    "cbd": "sample_region.geojson",
    "inner_north": "region_inner_north.geojson",
    "inner_east": "region_inner_east.geojson",
    "inner_south": "region_inner_south.geojson",
    "inner_northeast": "region_inner_northeast.geojson",
    "inner_southeast": "region_inner_southeast.geojson",
}
REGION_PADDING_DEGREES = 0.01  # roughly 1 km around each displayed network

DEFAULT_BUILDING_HEIGHT_M = 9.0  # ~3 storeys, used when OSM has no height/levels tag

# Real-world building-material palettes, grouped by OSM's own `building`
# type tag (residential/office/retail/civic/industrial) so every building
# gets a plausible, real-architecture tone even when OSM has no explicit
# building:colour tag (which is most buildings) - a single flat color per
# type read as "only the special-cased buildings have color"; picking a
# *varied* tone per building within its type's realistic palette (brick
# reds/terracotta for houses, blue glass for offices, amber/gold shopfronts
# for retail, sandstone for civic buildings) reads as an actual mixed
# streetscape instead. Each type also gets a clearly different HUE (not just
# a different shade of the same beige-gray), and more saturated than a first
# attempt at this - a first pass used muted tones that were too close in hue
# and lightness to read as distinct from typical aerial/orbit distance.
RESIDENTIAL_COLORS = ["#b9846f", "#c59a7b", "#a97868", "#cfb092", "#9f7c6e", "#bd8b72"]
OFFICE_COLORS = ["#6f8795", "#7e99a3", "#5f7887", "#8da6ab", "#708d9d", "#80959d"]
RETAIL_COLORS = ["#c6a46d", "#d0b582", "#b99064", "#d2aa72", "#b99a70"]
CIVIC_COLORS = ["#b7aa91", "#c4b79f", "#a99c84", "#c9bea8", "#aa9678"]
INDUSTRIAL_COLORS = ["#89918a", "#78837d", "#98a099", "#7f8886", "#929c96"]
# Real streetscapes mix all of the above even among "plain" buildings (OSM's
# generic building=yes tag, which is most of them) - so the fallback palette
# spans the same real materials rather than being its own flat tone.
GENERIC_COLORS = RESIDENTIAL_COLORS + OFFICE_COLORS + RETAIL_COLORS + CIVIC_COLORS

KIND_PALETTES = {
    "residential": RESIDENTIAL_COLORS,
    "office": OFFICE_COLORS,
    "retail": RETAIL_COLORS,
    "civic": CIVIC_COLORS,
    "industrial": INDUSTRIAL_COLORS,
    "generic": GENERIC_COLORS,
}

RESIDENTIAL_TYPES = {"apartments", "residential", "house", "terrace", "detached", "semidetached_house", "bungalow", "dormitory"}
OFFICE_TYPES = {"commercial", "office", "hotel"}
RETAIL_TYPES = {"retail", "supermarket", "kiosk"}
CIVIC_TYPES = {"university", "college", "school", "church", "cathedral", "hospital", "train_station", "civic", "public"}
INDUSTRIAL_TYPES = {"industrial", "warehouse", "parking", "shed", "roof", "garage", "garages", "service"}


def _building_height(tags: dict) -> float:
    if "height" in tags:
        try:
            height = float(tags["height"].rstrip("m").strip())
            if height > 0:
                return height
        except ValueError:
            pass
    if "building:levels" in tags:
        try:
            height = float(tags["building:levels"]) * 3.0
            if height > 0:
                return height
        except ValueError:
            pass
    return DEFAULT_BUILDING_HEIGHT_M


def _palette_pick(palette: list[str], coords: list[tuple[float, float]]) -> str:
    """Deterministic (not random-per-run) pick from a palette, keyed off the
    building's own footprint geometry - so the same building always gets the
    same color across re-extractions without needing to track OSM IDs."""
    key = f"{coords[0][0]:.6f},{coords[0][1]:.6f}"
    h = int(hashlib.md5(key.encode()).hexdigest(), 16)
    return palette[h % len(palette)]


def _building_kind(tags: dict) -> str:
    """Collapse sparse OSM tags into a small, legible zoning vocabulary.

    The viewer deliberately uses these categories as visual communication,
    not as a claim that every OSM record is a perfect cadastral land-use
    classification.  Explicit use tags win; otherwise building type and a
    handful of common amenity/office/shop tags provide a useful fallback.
    """
    building_type = tags.get("building", "yes").lower()
    amenity = tags.get("amenity", "").lower()
    landuse = tags.get("landuse", "").lower()

    if "shop" in tags or building_type in RETAIL_TYPES or landuse == "retail":
        return "retail"
    if "office" in tags or building_type in OFFICE_TYPES or landuse == "commercial":
        return "office"
    if (building_type in CIVIC_TYPES or amenity in {
            "library", "school", "college", "university", "hospital",
            "place_of_worship", "townhall", "arts_centre", "theatre",
        } or "historic" in tags):
        return "civic"
    if building_type in INDUSTRIAL_TYPES or landuse in {"industrial", "railway"}:
        return "industrial"
    if building_type in RESIDENTIAL_TYPES:
        return "residential"
    return "generic"


def _building_color(tags: dict, coords: list[tuple[float, float]], kind: str) -> str:
    colour = tags.get("building:colour")
    if colour:
        hexval = colour if colour.startswith("#") else f"#{colour}"
        if len(hexval) == 7:
            try:
                int(hexval[1:], 16)
                return hexval
            except ValueError:
                pass
    palette = KIND_PALETTES[kind]
    return _palette_pick(palette, coords)


class LandmarkHandler(osmium.SimpleHandler):
    def __init__(self, min_lon, max_lon, min_lat, max_lat):
        super().__init__()
        self.bounds = (min_lon, max_lon, min_lat, max_lat)
        self.parks = []
        self.libraries = []
        self.shops = []
        self.tram_ways = []
        self.commercial = []
        self.buildings = []
        self.water = []
        self.diagnostics = Counter()

    def _in_bbox(self, lon, lat):
        min_lon, max_lon, min_lat, max_lat = self.bounds
        return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat

    def node(self, n):
        if not n.location.valid():
            return
        lon, lat = n.location.lon, n.location.lat
        if not self._in_bbox(lon, lat):
            return
        tags = dict(n.tags)
        if tags.get("amenity") == "library":
            self.libraries.append({"lon": lon, "lat": lat, "name": tags.get("name", "")})
        if "shop" in tags:
            self.shops.append({"lon": lon, "lat": lat, "shop": tags["shop"], "name": tags.get("name", "")})

    def way(self, w):
        tags = dict(w.tags)
        is_tram = tags.get("railway") == "tram"
        # Areas are assembled in area(), including relations. Do not also
        # emit the member ways as independent, duplicate filled polygons.
        if not is_tram:
            return
        coords = []
        try:
            for n in w.nodes:
                if not n.location.valid():
                    self.diagnostics["incomplete_tram"] += 1
                    return
                coords.append((n.location.lon, n.location.lat))
        except osmium.InvalidLocationError:
            return
        if len(coords) < 2 or not _entry_in_bounds({"coords": coords}, self.bounds, area=False):
            return
        self.tram_ways.append({"coords": coords, "name": tags.get("name", ""), "osm_id": f"way/{w.id}"})

    def area(self, a):
        tags = dict(a.tags)
        is_park = tags.get("leisure") in ("park", "garden")
        is_commercial = tags.get("landuse") in ("commercial", "retail")
        is_library = tags.get("amenity") == "library"
        is_building = tags.get("building", "no") != "no"
        is_water = tags.get("natural") == "water" or tags.get("waterway") == "riverbank"
        if not (is_park or is_commercial or is_library or is_building or is_water):
            return
        source_id = f"{'way' if a.from_way() else 'relation'}/{a.orig_id()}"
        for outer in a.outer_rings():
            try:
                rings = [[(n.lon, n.lat) for n in ring] for ring in [outer, *a.inner_rings(outer)]]
            except osmium.InvalidLocationError:
                self.diagnostics["incomplete_area"] += 1
                continue
            entry = {"coords": rings[0], "holes": rings[1:],
                     "name": tags.get("name", ""), "osm_id": source_id}
            # Bounding-box intersection also keeps areas enclosing the view.
            # Retain complete rings here; exact clipping belongs to export.
            if not _entry_in_bounds(entry, self.bounds):
                continue
            if is_park: self.parks.append(entry)
            if is_commercial: self.commercial.append(entry)
            if is_water: self.water.append(entry)
            if is_library:
                parts, _ = project_clip_areas([entry], _xy_bounds(self.bounds))
                if parts:
                    pt = parts[0][1].representative_point()
                    self.libraries.append({"lon": pt.x, "lat": pt.y, "name": entry["name"]})
            if is_building:
                kind = _building_kind(tags)
                self.buildings.append({
                    **entry,
                    "height": _building_height(tags),
                    "color": _building_color(tags, rings[0], kind),
                    "kind": kind,
                    "roof": tags.get("roof:shape", "flat"),
                    "material": tags.get("building:material", ""),
                    "heritage": bool(tags.get("heritage") or tags.get("historic")),
                    "name": tags.get("name", ""),
                })


def _walk_coordinates(value, out):
    if (isinstance(value, list) and len(value) >= 2
            and isinstance(value[0], (int, float)) and isinstance(value[1], (int, float))):
        out.append((float(value[0]), float(value[1])))
    elif isinstance(value, list):
        for child in value:
            _walk_coordinates(child, out)


def _geojson_bounds(path: Path) -> tuple[float, float, float, float]:
    data = json.loads(path.read_text())
    coords = []
    for feature in data.get("features", []):
        _walk_coordinates(feature.get("geometry", {}).get("coordinates", []), coords)
    if not coords:
        raise ValueError(f"No polygon coordinates in {path}")
    lons, lats = zip(*coords)
    return (
        min(lons) - REGION_PADDING_DEGREES,
        max(lons) + REGION_PADDING_DEGREES,
        min(lats) - REGION_PADDING_DEGREES,
        max(lats) + REGION_PADDING_DEGREES,
    )


def _xy_bounds(bounds):
    return (bounds[0], bounds[2], bounds[1], bounds[3])


def _entry_in_bounds(entry: dict, bounds: tuple[float, float, float, float], area=True) -> bool:
    min_lon, max_lon, min_lat, max_lat = bounds
    if entry.get("coords"):
        coords = entry["coords"]
        xs, ys = zip(*coords)
        if max(xs) < min_lon or min(xs) > max_lon or max(ys) < min_lat or min(ys) > max_lat:
            return False
        if not area:
            return LineString(coords).intersects(box(*_xy_bounds(bounds)))
        parts, _ = project_clip_areas([entry], _xy_bounds(bounds))
        return bool(parts)
    lon, lat = entry.get("lon"), entry.get("lat")
    return lon is not None and lat is not None and min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def _write_cache(region_key: str, h: LandmarkHandler,
                 bounds: tuple[float, float, float, float], *, directory=None, evidence=None) -> Path:
    payload = {
        "parks": [x for x in h.parks if _entry_in_bounds(x, bounds)],
        "libraries": [x for x in h.libraries if _entry_in_bounds(x, bounds)],
        "shops": [x for x in h.shops if _entry_in_bounds(x, bounds)],
        "tram_ways": [x for x in h.tram_ways if _entry_in_bounds(x, bounds, area=False)],
        "commercial": [x for x in h.commercial if _entry_in_bounds(x, bounds)],
        "buildings": [x for x in h.buildings if _entry_in_bounds(x, bounds)],
        "water": [x for x in h.water if _entry_in_bounds(x, bounds)],
        "metadata": {"schema_version": 2, "source": PBF_PATH.name,
                     "bounds": bounds, "diagnostics": dict(h.diagnostics),
                     "area_handling": "OSM closed ways + multipolygon relations, with inner rings",
                     **(evidence or {})},
    }
    directory = directory if directory is not None else LANDMARKS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    out_path = directory / f"{region_key}.json"
    temp = out_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload))
    temp.replace(out_path)
    print(f"{region_key}: parks={len(payload['parks'])} libraries={len(payload['libraries'])} "
          f"shops={len(payload['shops'])} tram_ways={len(payload['tram_ways'])} "
          f"commercial={len(payload['commercial'])} buildings={len(payload['buildings'])} "
          f"water={len(payload['water'])}")
    print(f"written to {out_path}")
    return out_path


def extract(region_key: str, min_lon: float, max_lon: float,
            min_lat: float, max_lat: float) -> Path:
    bounds = (float(min_lon), float(max_lon), float(min_lat), float(max_lat))
    h = LandmarkHandler(*bounds)
    h.apply_file(str(PBF_PATH), locations=True)
    return _write_cache(region_key, h, bounds)


def main():
    if not PBF_PATH.is_file():
        print(f"Missing {PBF_PATH}. Run a network build once to download the Victoria OSM extract.")
        sys.exit(1)

    if '--scene' in sys.argv[1:]:
        import argparse
        from wrapper.skyline import scene_geographic_bounds
        from wrapper.runs import validate_run_name
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--scene', required=True)
        parser.add_argument('--region', required=True)
        args = parser.parse_args()
        run, region = validate_run_name(args.scene), validate_run_name(args.region)
        source = PROJECT_ROOT / 'output' / run / 'skyline_scene.json'
        source_bytes = source.read_bytes()
        scene = json.loads(source_bytes)
        west, east, south, north = scene_geographic_bounds(scene['coordinate_transform'], scene['terrain'])
        # A small round-off margin, not an independently guessed region buffer.
        bounds = (west-0.00001, east+0.00001, south-0.00001, north+0.00001)
        directory = LANDMARKS_DIR.parent / 'expanded'
        previous = directory / f'{region}.json'
        if previous.is_file():
            old = json.loads(previous.read_text())['metadata']['bounds']
            bounds = (min(bounds[0],old[0]), max(bounds[1],old[1]),
                      min(bounds[2],old[2]), max(bounds[3],old[3]))
        print(f'Assembling local OSM for scene {run}, W/E/S/N={bounds}', flush=True)
        h = LandmarkHandler(*bounds)
        h.apply_file(str(PBF_PATH), locations=True)
        _write_cache(region, h, bounds, directory=directory, evidence={
            'extent_source_scene':run, 'extent_source_sha256':hashlib.sha256(source_bytes).hexdigest(),
            'extent_rule':'full displayed terrain extent, union with previous expanded extent'})
        return

    if sys.argv[1:] == ["--all"]:
        # Share one area-assembly job across all six regional caches. Osmium
        # internally reads twice to assemble multipolygon relations.
        region_bounds = {
            region_key: _geojson_bounds(PROJECT_ROOT / "data" / filename)
            for region_key, filename in PRESET_REGION_FILES.items()
        }
        union_bounds = (
            min(b[0] for b in region_bounds.values()),
            max(b[1] for b in region_bounds.values()),
            min(b[2] for b in region_bounds.values()),
            max(b[3] for b in region_bounds.values()),
        )
        print("Assembling Victoria OSM areas for all preset regions (two-pass area reader)...")
        h = LandmarkHandler(*union_bounds)
        h.apply_file(str(PBF_PATH), locations=True)
        for region_key, bounds in region_bounds.items():
            _write_cache(region_key, h, bounds)
        return

    if len(sys.argv) != 6:
        print(__doc__)
        sys.exit(1)
    region_key, min_lon, max_lon, min_lat, max_lat = sys.argv[1:6]
    extract(region_key, float(min_lon), float(max_lon), float(min_lat), float(max_lat))


if __name__ == "__main__":
    main()
