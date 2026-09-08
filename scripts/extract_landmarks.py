"""One-off data-prep script: pulls real landmarks (parks, libraries, tram
lines, commercial/retail zones, building footprints) out of the cached
Victoria OSM extract (data/geofabrik_victoria-latest.osm.pbf) for a given
region's bounding box, and caches the result to data/landmarks/<region_key>.json.

Run manually whenever a new region needs landmarks - NOT run automatically
by the pipeline (building the node-location index for the 236MB PBF can take
many minutes even with a bbox filter, which is too slow to redo on every
simulation run for data that rarely changes between runs of the same region).

Usage:
    python3 scripts/extract_landmarks.py --all

or for one custom bounding box:
    python3 scripts/extract_landmarks.py cbd 144.945 144.978 -37.832 -37.802
                                          ^region_key  ^min_lon ^max_lon ^min_lat ^max_lat
"""

import hashlib
import json
import sys
from pathlib import Path

import osmium

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PBF_PATH = PROJECT_ROOT / "data" / "geofabrik_victoria-latest.osm.pbf"
LANDMARKS_DIR = PROJECT_ROOT / "data" / "landmarks"

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
        is_park = tags.get("leisure") in ("park", "garden")
        is_tram = tags.get("railway") == "tram"
        is_commercial = tags.get("landuse") in ("commercial", "retail")
        is_library = tags.get("amenity") == "library"
        is_building = "building" in tags and tags["building"] != "no"
        if not (is_park or is_tram or is_commercial or is_library or is_building):
            return
        coords = []
        try:
            for n in w.nodes:
                if n.location.valid():
                    coords.append((n.location.lon, n.location.lat))
        except osmium.InvalidLocationError:
            return
        if not coords or not any(self._in_bbox(lon, lat) for lon, lat in coords):
            return
        entry = {"coords": coords, "name": tags.get("name", "")}
        if is_park:
            self.parks.append(entry)
        if is_tram:
            self.tram_ways.append(entry)
        if is_commercial:
            self.commercial.append(entry)
        if is_library:
            self.libraries.append({"lon": coords[0][0], "lat": coords[0][1], "name": tags.get("name", "")})
        if is_building:
            # Building footprints are closed ways (first/last node coincide);
            # a non-closed way tagged building=* is usually a data error or
            # a fragment of a multipolygon relation we're not handling here -
            # skip it rather than render a broken/open shape.
            if len(coords) >= 4 and coords[0] == coords[-1]:
                kind = _building_kind(tags)
                self.buildings.append({
                    "coords": coords,
                    "height": _building_height(tags),
                    "color": _building_color(tags, coords, kind),
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


def _entry_in_bounds(entry: dict, bounds: tuple[float, float, float, float]) -> bool:
    min_lon, max_lon, min_lat, max_lat = bounds
    if entry.get("coords"):
        return any(min_lon <= lon <= max_lon and min_lat <= lat <= max_lat
                   for lon, lat in entry["coords"])
    lon, lat = entry.get("lon"), entry.get("lat")
    return lon is not None and lat is not None and min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def _write_cache(region_key: str, h: LandmarkHandler,
                 bounds: tuple[float, float, float, float]) -> Path:
    payload = {
        "parks": [x for x in h.parks if _entry_in_bounds(x, bounds)],
        "libraries": [x for x in h.libraries if _entry_in_bounds(x, bounds)],
        "shops": [x for x in h.shops if _entry_in_bounds(x, bounds)],
        "tram_ways": [x for x in h.tram_ways if _entry_in_bounds(x, bounds)],
        "commercial": [x for x in h.commercial if _entry_in_bounds(x, bounds)],
        "buildings": [x for x in h.buildings if _entry_in_bounds(x, bounds)],
    }
    LANDMARKS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = LANDMARKS_DIR / f"{region_key}.json"
    out_path.write_text(json.dumps(payload))
    print(f"{region_key}: parks={len(payload['parks'])} libraries={len(payload['libraries'])} "
          f"shops={len(payload['shops'])} tram_ways={len(payload['tram_ways'])} "
          f"commercial={len(payload['commercial'])} buildings={len(payload['buildings'])}")
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

    if sys.argv[1:] == ["--all"]:
        # Scan Victoria once, then split the collected features into all six
        # overlapping regional caches.  The previous implementation scanned
        # the same 236MB PBF six separate times and could take half an hour.
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
        print("Scanning Victoria OSM once for all preset regions...")
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
