"""Refresh visual land polygons only, retaining each original result JSON.

Usage: .venv/bin/python scripts/refresh_scene_landmarks.py RUN_sim --region cbd
Writes *.landuse-v2.json sidecars; never runs MATSim or recalculates traffic.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from wrapper import skyline
from wrapper.runs import validate_run_name


def refresh_scene(source, cache, region):
    source_bytes = source.read_bytes()
    cache_bytes = cache.read_bytes()
    data = json.loads(source_bytes)
    layers, diagnostics = skyline.scene_area_layers(
        json.loads(cache_bytes), data['coordinate_transform'], data['terrain'])
    # Refresh footprint coverage and safe roofs together; never publish a mix
    # of new outlines with stale building profiles/diagnostics from the old scene.
    layers['buildings'], building_diagnostics = skyline.prepare_buildings(layers['buildings'])
    data.setdefault('landmarks', {}).update(layers)
    data['landmarks']['labels'] = skyline._area_labels(layers['buildings'])
    data['landmark_geometry_version'] = 2
    data['landmark_diagnostics'] = diagnostics
    data['building_geometry_version'] = 1
    data['building_diagnostics'] = building_diagnostics
    data['landmark_refresh'] = {
        'source_file': source.name,
        'source_sha256': hashlib.sha256(source_bytes).hexdigest(),
        'cache_sha256': hashlib.sha256(cache_bytes).hexdigest(),
        'region': region,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'scope': 'visual polygons only; original traffic and terrain unchanged',
    }
    destination = source.with_name(source.stem + '.landuse-v2.json')
    temp = destination.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False))
    temp.replace(destination)
    return destination, diagnostics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run')
    parser.add_argument('--region', required=True)
    args = parser.parse_args()
    run = validate_run_name(args.run)
    region = validate_run_name(args.region)
    cache = skyline.landmark_cache_path(region)
    if not cache.is_file():
        parser.error('Extract v2 landmarks for this region first')
    sources = [skyline.OUTPUT_DIR / run / name for name in ('skyline_scene.json', 'ifline_scene.json')]
    if not any(p.is_file() for p in sources):
        parser.error('No existing visualization scene in this run')
    for source in sources:
        if source.is_file():
            destination, diagnostics = refresh_scene(source, cache, region)
            print(destination)
            print(json.dumps(diagnostics))


if __name__ == '__main__':
    main()
