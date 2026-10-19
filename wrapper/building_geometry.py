"""Display-only building models: safe roofs inside real footprints.

prepare_buildings is the interface used by both export and replay refresh. It
does not infer building:part ownership, merge neighbours, or alter traffic data.
Every roof is contained in its footprint, keeps courtyards open, and consumes
part of the existing total height rather than adding arbitrary storeys on top.
"""
import math
from collections import Counter

from shapely.geometry import Polygon, LineString
from shapely.ops import split, triangulate

from wrapper.landmark_geometry import clean_ring, polygon_parts


def _ring(ring):
    return [[round(x, 6), round(z, 6)] for x, z in ring.coords]


def _footprint(poly):
    return {'points': _ring(poly.exterior), 'holes': [_ring(r) for r in poly.interiors]}


def _face(a, b, c):
    # X/Z footprint coordinates, Y height. Make the roof face upwards.
    normal_y = (b[2]-a[2])*(c[0]-a[0]) - (b[0]-a[0])*(c[2]-a[2])
    return [a, b, c] if normal_y > 0 else [a, c, b]


def _oriented_box(poly):
    # Explicit edge projections avoid the installed GEOS oriented_envelope's
    # divide-by-zero warnings on horizontal/vertical edges (including squares).
    hull = list(poly.convex_hull.exterior.coords)[:-1]
    ox, oz = hull[0]
    best = None
    for a,b in zip(hull,hull[1:]+hull[:1]):
        length = math.dist(a,b)
        if length < 1e-12:
            continue
        ux,uz = (b[0]-a[0])/length,(b[1]-a[1])/length
        nx,nz = -uz,ux
        us = [(x-ox)*ux+(z-oz)*uz for x,z in hull]
        ns = [(x-ox)*nx+(z-oz)*nz for x,z in hull]
        lo,hi,left,right = min(us),max(us),min(ns),max(ns)
        w,d = hi-lo,right-left
        candidate = (w*d,ox+(lo+hi)/2*ux+(left+right)/2*nx,
                     oz+(lo+hi)/2*uz+(left+right)/2*nz,ux,uz,w,d)
        if best is None or candidate[0] < best[0]-1e-10:
            best = candidate
    area,cx,cz,ux,uz,w,d = best
    if d > w:
        ux,uz,w,d = -uz,ux,d,w
    return area,cx,cz,ux,uz,w,d


def _pitched_roof(poly, depth, tag):
    """Conservative low-rise roofs. Complex/holed outlines fall back to flat."""
    if poly.interiors or poly.area / poly.convex_hull.area < 0.995:
        return None
    ring = list(poly.exterior.coords)[:-1]
    center = poly.centroid
    faces, skirts = [], []
    if tag in ('hipped', 'pyramidal'):
        # In a convex ring every triangle to the interior apex stays inside.
        peak = [center.x, depth, center.y]
        for a, b in zip(ring, ring[1:] + ring[:1]):
            faces.extend(_face([a[0],0,a[1]], [b[0],0,b[1]], peak))
    elif tag == 'gabled':
        area,cx,cz,ux,uz,length,width = _oriented_box(poly)
        if poly.area / area < 0.995:
            return None
        nx, nz = -uz, ux
        half_width = width/2
        def h(x,z):
            return depth*max(0, 1-abs((x-cx)*nx+(z-cz)*nz)/half_width)
        ridge = LineString([(cx-ux*length*2,cz-uz*length*2),
                            (cx+ux*length*2,cz+uz*length*2)])
        for part in polygon_parts(split(poly, ridge)):
            for tri in triangulate(part):
                if part.covers(tri):
                    faces.extend(_face(*[[x,h(x,z),z] for x,z in list(tri.exterior.coords)[:3]]))
            boundary = list(part.exterior.coords)
            for a,b in zip(boundary,boundary[1:]):
                edge = LineString([a,b])
                if poly.boundary.buffer(1e-7).covers(edge) and max(h(*a),h(*b)) > 1e-6:
                    # Gable wall: retain below the sloping roof, not a hole.
                    va,vb = [a[0],h(*a),a[1]],[b[0],h(*b),b[1]]
                    skirts.extend([va,[a[0],0,a[1]],[b[0],0,b[1]],va,[b[0],0,b[1]],vb])
    else:
        return None
    return {'kind':'pitched', 'depth':depth, 'faces':faces, 'skirts':skirts} if faces else None


def prepare_buildings(buildings):
    models, diagnostics = [], Counter(input=len(buildings))
    # Deduplicate only identical footprints. Do NOT union adjacent buildings
    # or subtract arbitrary overlaps: those can be genuine podium/tower parts.
    groups = {}
    for b in buildings:
        try:
            poly = Polygon(clean_ring(b['points']), [clean_ring(r) for r in b.get('holes',[])])
            height = float(b['height'])
            if not poly.is_valid or poly.is_empty or not math.isfinite(height) or height <= 0:
                raise ValueError('Invalid display solid')
        except (ValueError, KeyError, TypeError, IndexError):
            diagnostics['invalid'] += 1
            continue
        key = poly.normalize().wkb
        groups.setdefault(key, []).append((b,poly,height))
    for members in groups.values():
        source, poly, height = max(members, key=lambda item:(item[2],bool(item[0].get('name'))))
        b = dict(source)
        b['source_ids'] = sorted({m[0]['osm_id'] for m in members if m[0].get('osm_id')})
        b['source_names'] = sorted({m[0]['name'] for m in members if m[0].get('name')})
        diagnostics['duplicate_footprints'] += len(members)-1
        if len({m[2] for m in members}) > 1:
            diagnostics['duplicate_height_conflicts'] += 1
        if not b.get('name') and b['source_names']:
            b['name'] = b['source_names'][0]
        # A roof is part of the original height. No random tiers/spires, no
        # bounding-box pyramids, no domes inferred from a civic category/name.
        profile = {'version':1, 'kind':'flat', 'body_top':height, 'total_height':height}
        height_m = float(b.get('height_m',9))
        tag = b.get('roof','flat')
        if height_m >= 90 and not b.get('clipped'):
            short_side = _oriented_box(poly)[-1]
            inset_distance = min(0.65, max(0.12, short_side*0.07))
            inset_parts = list(polygon_parts(poly.buffer(-inset_distance, join_style='mitre', mitre_limit=2)))
            # Splitting a narrow neck into many roof islands recreates shards.
            if len(inset_parts) == 1:
                inner = inset_parts[0]
                ratio = inner.area/poly.area
                if 0.55 <= ratio <= 0.95 and poly.covers(inner):
                    depth = min(1.25, height*0.045)
                    profile.update(kind='setback',body_top=height-depth,depth=depth,
                                   inset=_footprint(inner))
        elif height_m <= 30 and tag in ('gabled','hipped','pyramidal') and not b.get('clipped'):
            roof = _pitched_roof(poly, min(1.0,height*0.15), tag)
            if roof:
                profile.update(roof)
                profile['body_top'] = height-roof['depth']
        if profile['kind']=='flat' and tag!='flat':
            diagnostics['nonflat_tag_fallback'] += 1
        b['architecture'] = profile
        models.append(b)
        diagnostics[profile['kind']] += 1
    diagnostics['output'] = len(models)
    return models, dict(diagnostics)
