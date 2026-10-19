"""Generate small regression inputs with the production geometry preparation.

Run: .venv/bin/python tests/browser/building_fixture.py
Then serve tests/browser and open building_geometry.html (API on port 8000).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from shapely.affinity import rotate
from shapely.geometry import Polygon, box
from wrapper.building_geometry import prepare_buildings

def entry(poly, **extra):
    return {'points':list(poly.exterior.coords),
            'holes':[list(r.coords) for r in poly.interiors],
            'height':20,'height_m':100,'roof':'flat',**extra}

if __name__=='__main__':
    entries = [
        entry(rotate(box(-8,-4,8,4),32),osm_id='rotated'),
        entry(Polygon(box(-9,-9,9,9).exterior.coords,
                      [box(-3,-3,3,3).exterior.coords]),osm_id='courtyard'),
        entry(Polygon([(-8,-8),(8,-8),(8,-3),(-3,-3),(-3,8),(-8,8)]),osm_id='concave'),
        entry(rotate(box(-8,-4,8,4),25),height=4,height_m=18,roof='gabled',osm_id='gabled'),
        entry(rotate(box(-8,-4,8,4),47),height=4,height_m=18,roof='hipped',osm_id='hipped'),
        entry(box(-5,-5,5,5),osm_id='clipped',clipped=True),
    ]
    models,_=prepare_buildings(entries)
    models.append(entry(box(-5,-5,5,5),osm_id='legacy'))
    Path(__file__).with_name('building-fixtures.json').write_text(json.dumps(models))
