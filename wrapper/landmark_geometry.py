"""Polygon repair and true intersection, shared by OSM prep and scene export.

An entry holds one outer ``coords`` ring plus zero or more ``holes``. An OSM
multipolygon is split into such entries, with its osm_id preserved on each.
No hulls, invented connecting edges, or minimum area/bbox-fill filters.
"""
import math

from rasterio.warp import transform as warp_transform
from shapely import make_valid
from shapely.geometry import Polygon, box
from shapely.errors import GEOSException


def polygon_parts(geometry):
    if geometry.is_empty:
        return
    if geometry.geom_type == "Polygon":
        if geometry.area > 0:
            yield geometry
    elif geometry.geom_type in ("MultiPolygon", "GeometryCollection"):
        for part in geometry.geoms:
            yield from polygon_parts(part)


def clean_ring(coords):
    ring = []
    for value in coords:
        x, y = float(value[0]), float(value[1])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("Non-finite polygon coordinate")
        if not ring or (x, y) != ring[-1]:
            ring.append((x, y))
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    if len(set(ring)) < 3:
        raise ValueError("Polygon ring has fewer than three distinct vertices")
    return ring


def project_clip_areas(entries, bounds, source_crs=None, target_crs=None):
    """Return (source entry, clipped Polygon, was_clipped) tuples and counts.

    Projection is batched once, including holes. ``bounds`` is x0,y0,x1,y1
    in the target CRS. A polygon surrounding the view (no vertex inside) is
    correctly kept. Boundary-only touches and collapsed linework aren't land.
    """
    stats = dict(input=len(entries), invalid=0, repaired=0, outside=0,
                 clipped=0, kept_features=0, parts=0)
    prepared, coordinates = [], []
    for entry in entries:
        try:
            rings = [clean_ring(entry["coords"])] + [clean_ring(r) for r in entry.get("holes", [])]
        except (KeyError, ValueError, TypeError, IndexError, OverflowError):
            stats["invalid"] += 1
            continue
        prepared.append((entry, [len(r) for r in rings]))
        coordinates.extend(point for ring in rings for point in ring)
    if not coordinates:
        return [], stats
    if source_crs and target_crs and source_crs != target_crs:
        xs, ys = warp_transform(source_crs, target_crs, *zip(*coordinates))
        coordinates = list(zip(xs, ys))
    clip = box(*bounds)
    offset, result = 0, []
    for entry, lengths in prepared:
        rings = []
        for length in lengths:
            rings.append(coordinates[offset:offset + length])
            offset += length
        try:
            geometry = Polygon(rings[0], rings[1:])
            if not geometry.is_valid:
                geometry = make_valid(geometry)
                stats["repaired"] += 1
            parts = list(polygon_parts(geometry))
            if not parts:
                stats["invalid"] += 1
                continue
            kept, was_clipped = [], False
            for part in parts:
                if not part.intersects(clip):
                    continue
                is_clipped = not clip.covers(part)
                clipped = part.intersection(clip) if is_clipped else part
                kept.extend(polygon_parts(clipped))
                was_clipped |= is_clipped
            if not kept:
                stats["outside"] += 1
                continue
            stats["kept_features"] += 1
            stats["clipped"] += int(was_clipped)
            result.extend((entry, part, was_clipped) for part in kept)
        except (ValueError, GEOSException):
            stats["invalid"] += 1
    stats["parts"] = len(result)
    return result, stats


def polygon_entry(polygon):
    return {
        "coords": list(polygon.exterior.coords),
        "holes": [list(ring.coords) for ring in polygon.interiors],
    }
