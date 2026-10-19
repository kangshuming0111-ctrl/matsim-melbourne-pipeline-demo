"""Uncapped, read-only known-footprint input for production road-plan checks.

Display meshes are not evidence of absent buildings. Source geometry is strict:
no cap, repair, dropped invalid feature, or clipping that could erase a conflict.
Returned rings/heights use the display scene's units; screening uses native metres.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from rasterio.crs import CRS
from rasterio.warp import transform
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from wrapper.landmark_geometry import clean_ring
from wrapper.skyline import landmark_cache_path

ROOT = Path(__file__).resolve().parent.parent
SCREEN_VERSION = 1


def road_corridors(roads):
    """One footprint definition shared by extent checks and conflict detection."""
    return [(road['operation'], unary_union([
        LineString([p[:2], q[:2]]).buffer(road['width_m'] / 2, cap_style='flat')
        for p, q in road['segments']])) for road in roads]


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def load_corridor_buildings(region_key, roads, coordinate_transform):
    """Return (uncapped corridor scene, evidence) or raise ValueError, never write.

    Must be called with compiler-resolved roads, not unsnapped draft points.
    Cache bounds are W/E/S/N in WGS84, matching the landmark extractor. Every
    source footprint is validated; only complete intersecting polygons are sent
    to the existing conflict detector. Heights remain display-only assumptions.
    """
    if not roads:
        raise ValueError('完整建筑筛查只接受已编译的新道路走廊')
    if not isinstance(region_key, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,119}', region_key):
        raise ValueError('基线缺少有效区域标识，无法定位完整建筑源')
    tr = dict(coordinate_transform)
    if (any(not _finite(tr.get(key)) for key in ('center_x', 'center_y', 'scene_units_per_metre'))
            or tr['scene_units_per_metre'] <= 0):
        raise ValueError('基线场景坐标变换无效，无法进行完整建筑筛查')
    try:
        crs = CRS.from_user_input(tr.get('network_crs'))
        if not crs.is_projected or crs.linear_units_factor[1] != 1:
            raise ValueError('not projected metres')
    except (ValueError, TypeError) as exc:
        raise ValueError('完整建筑筛查需要已知的米制投影坐标系') from exc
    path = landmark_cache_path(region_key)
    try:
        source_bytes = path.read_bytes()
        source = json.loads(source_bytes)
    except (OSError, ValueError, UnicodeError) as exc:
        raise ValueError('完整建筑源不可用；不能使用显示裁剪层代替') from exc
    if not isinstance(source, dict) or not isinstance(source.get('buildings'), list) or not source['buildings']:
        raise ValueError('完整建筑源缺少非空建筑轮廓层，不能声称零冲突')
    metadata = source.get('metadata')
    bounds = metadata.get('bounds') if isinstance(metadata, dict) else None
    if (not isinstance(bounds, list) or len(bounds) != 4 or not all(_finite(v) for v in bounds)
            or not -180 <= bounds[0] < bounds[1] <= 180 or not -90 <= bounds[2] < bounds[3] <= 90):
        raise ValueError('完整建筑源缺少有效覆盖范围（W/E/S/N）')
    diagnostics = metadata.get('diagnostics', {})
    if (not isinstance(diagnostics, dict) or
            type(diagnostics.get('incomplete_area', 0)) is not int or diagnostics.get('incomplete_area', 0) != 0):
        raise ValueError('建筑源缓存记录了不完整面数据，需修复源数据后重新检查')
    corridors = road_corridors(roads)
    corridor = unary_union([polygon for _, polygon in corridors])
    if corridor.is_empty or not corridor.is_valid:
        raise ValueError('新道路走廊几何无效')
    # Densify the entire width-inclusive boundary, not just draft endpoints.
    boundary = corridor.segmentize(10).boundary
    rings = [boundary] if boundary.geom_type == 'LineString' else list(boundary.geoms)
    points = [point for ring in rings for point in ring.coords]
    try:
        lons, lats = transform(crs, 'EPSG:4326', *zip(*points))
    except Exception as exc:
        raise ValueError('新道路走廊坐标投影失败') from exc
    if any(not (bounds[0] <= lon <= bounds[1] and bounds[2] <= lat <= bounds[3])
           for lon, lat in zip(lons, lats)):
        raise ValueError('新道路完整宽度走廊超出建筑源覆盖范围；请扩展建筑数据后重新检查')

    prepared, coordinates = [], []
    for index, entry in enumerate(source['buildings']):
        try:
            rings = [clean_ring(entry['coords'])] + [clean_ring(ring) for ring in entry.get('holes', [])]
            if any(not -180 <= x <= 180 or not -90 <= y <= 90 for ring in rings for x, y in ring):
                raise ValueError('not WGS84')
            polygon = Polygon(rings[0], rings[1:])
            if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
                raise ValueError('invalid polygon')
        except (KeyError, ValueError, TypeError, IndexError, OverflowError, AttributeError) as exc:
            raise ValueError(f'完整建筑源第 {index + 1} 项轮廓无效；不能跳过或自动修复后声称零冲突') from exc
        prepared.append((entry, [len(ring) for ring in rings]))
        coordinates.extend(point for ring in rings for point in ring)
    try:
        xs, ys = transform('EPSG:4326', crs, *zip(*coordinates))
    except Exception as exc:
        raise ValueError('完整建筑源坐标投影失败') from exc
    projected = list(zip(xs, ys))
    if any(not math.isfinite(x) or not math.isfinite(y) for x, y in projected):
        raise ValueError('完整建筑源投影后包含非有限坐标')
    scale, cx, cy = tr['scene_units_per_metre'], tr['center_x'], tr['center_y']

    def displayed(ring):
        return [[(x - cx) * scale, (y - cy) * scale] for x, y in ring.coords]

    buildings, offset = [], 0
    for index, (entry, lengths) in enumerate(prepared):
        rings = []
        for length in lengths:
            rings.append(projected[offset:offset + length])
            offset += length
        polygon = Polygon(rings[0], rings[1:])
        if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
            raise ValueError(f'完整建筑源第 {index + 1} 项投影轮廓无效')
        if not polygon.intersects(corridor):
            continue
        height = entry.get('height', 9)
        height = float(height) if _finite(height) and height > 0 else 9.0
        buildings.append({'osm_id': entry.get('osm_id'), 'name': entry.get('name', ''),
                          'points': displayed(polygon.exterior),
                          'holes': [displayed(ring) for ring in polygon.interiors],
                          'height': height * scale, 'height_m': height})
    try:
        source_path = str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        source_path = path.name
    evidence = {
        'schema_version': SCREEN_VERSION, 'status': 'completed',
        'scope': 'compiled_new_road_corridors', 'basis': 'uncapped_known_footprints',
        'operation_ids': [road['operation'] for road in roads],
        'source': {'path': source_path, 'sha256': hashlib.sha256(source_bytes).hexdigest()},
        'source_bounds_wgs84': dict(zip(('west', 'east', 'south', 'north'), bounds)),
        'corridors_within_source_extent': True,
        'counts': {'source_features': len(prepared), 'validated_features': len(prepared),
                   'corridor_features': len(buildings)},
        'known_source_only': True,
    }
    return {'coordinate_transform': tr, 'landmarks': {'buildings': buildings}}, evidence
