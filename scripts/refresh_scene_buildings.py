"""Update roof/solid display only; preserve the original and land-use refresh.

python3 scripts/refresh_scene_buildings.py RUN_sim
No MATSim process, new data extraction or traffic analysis is invoked.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from wrapper.building_geometry import prepare_buildings
from wrapper.runs import OUTPUT_DIR, validate_run_name, refreshed_landmark_scene


def refresh_buildings(source):
    original = source.read_bytes()
    data = json.loads(original)
    buildings, diagnostics = prepare_buildings(data.get('landmarks',{}).get('buildings',[]))
    data.setdefault('landmarks',{})['buildings'] = buildings
    data['building_geometry_version'] = 1
    data['building_diagnostics'] = diagnostics
    data['building_refresh'] = {
        'source_file':source.name, 'source_sha256':hashlib.sha256(original).hexdigest(),
        'created_at':datetime.now(timezone.utc).isoformat(),
        'scope':'building display only; traffic, terrain and land-use unchanged',
    }
    dest = source.with_name(source.stem+'.buildings-v1.json')
    temp = dest.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False))
    temp.replace(dest)
    return dest, diagnostics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    args = parser.parse_args()
    directory = OUTPUT_DIR/validate_run_name(args.run)
    sources = [directory/name for name in ('skyline_scene.json','ifline_scene.json')]
    if not any(p.is_file() for p in sources):
        parser.error('No existing scene for this run')
    for original in sources:
        if original.is_file():
            source = refreshed_landmark_scene(original) or original
            dest, diagnostics = refresh_buildings(source)
            print(dest)
            print(json.dumps(diagnostics))


if __name__ == '__main__':
    main()
