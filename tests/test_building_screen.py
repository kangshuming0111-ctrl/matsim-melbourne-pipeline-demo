"""Production footprint screening contracts; temporary inputs, no simulations."""
import copy
import hashlib
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from rasterio.warp import transform

from wrapper import building_screen, ifline, planning
from wrapper.api import PlanRequest, check_city_plan, run_city_plan

NETWORK = '''<network><nodes>
<node id="w" x="0" y="100"/><node id="e" x="400" y="100"/>
<node id="n" x="200" y="200"/><node id="s" x="200" y="0"/>
</nodes><links>
<link id="wn" from="w" to="n" length="224" freespeed="10" capacity="900" permlanes="1" modes="car,bike"/>
<link id="ne" from="n" to="e" length="224" freespeed="10" capacity="900" permlanes="1" modes="car,bike"/>
<link id="cross" from="n" to="s" length="200" freespeed="10" capacity="900" permlanes="1" modes="car,bike"/>
</links></network>'''
ROAD = {'type': 'new_road', 'points': [[0, 100], [400, 100]], 'heights': [0, 0],
        'speed_kph': 30, 'lanes': 1, 'capacity_per_hour': 900, 'snap_tolerance_m': 5,
        'modes': ['car'], 'bidirectional': True}
TRANSFORM = {'network_crs': 'EPSG:3857', 'center_x': 200, 'center_y': 100,
             'scene_units_per_metre': 0.2}


def rectangle(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def geographic(points):
    return list(map(list, zip(*transform('EPSG:3857', 'EPSG:4326', *zip(*points)))))


def source_building(key='low-building', points=None, holes=None):
    return {'osm_id': key, 'name': 'A low building', 'height': 2,
            'coords': geographic(points or rectangle(150, 98, 170, 102)),
            'holes': [geographic(ring) for ring in (holes or [])]}


class BuildingScreenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.network = self.root / 'network.xml'
        self.network.write_text(NETWORK)
        self.cache = self.root / 'fixture.json'
        self.scene_path = self.root / 'skyline_scene.json'
        self.scene = {'coordinate_transform': copy.deepcopy(TRANSFORM),
                      'landmarks': {'buildings': []},
                      'landmark_diagnostics': {'buildings': {'omitted_by_limit': 1}}}
        self.scene_path.write_text(json.dumps(self.scene))
        self.raw = {'metadata': {'bounds': [-0.01, 0.01, -0.01, 0.01]},
                    'buildings': [source_building()]}
        self.write_source()
        self.assets = {'sim_dir': self.root, 'network_file': self.network, 'region_key': 'fixture'}
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(planning, 'resolve_run_assets', return_value=self.assets))
        stack.enter_context(patch.object(ifline, 'resolve_run_assets', return_value=self.assets))
        stack.enter_context(patch.object(building_screen, 'landmark_cache_path', return_value=self.cache))

    def write_source(self):
        self.cache.write_text(json.dumps(self.raw))

    def check(self, road=None, **fields):
        return planning.check_plan('fixture_sim', {'operations': [road or ROAD], **fields})[1]

    def test_omitted_low_building_is_found_without_display_cap_and_coordinates_stay_compatible(self):
        far = source_building('tall', rectangle(-200, -200, -190, -190))
        far['height'] = 100
        self.raw['buildings'] = [{**far, 'osm_id': f'tall-{i}'} for i in range(3000)] + [source_building()]
        self.write_source()
        before_scene = self.scene_path.read_bytes()
        report = self.check(building_labels={'low-building': 7})
        hit = report['conflicts'][0]
        self.assertEqual((hit['key'], hit['label'], hit['operation_ids']), ('low-building', '建筑7', [1]))
        self.assertAlmostEqual(hit['focus']['x'], 160)
        self.assertAlmostEqual(hit['focus']['y'], 100)
        self.assertAlmostEqual(hit['points'][0][0], -10)
        self.assertAlmostEqual(hit['points'][0][1], -0.4)
        self.assertAlmostEqual(hit['height'], 0.4)
        evidence = report['building_screen']
        self.assertEqual(evidence['counts'], {'source_features': 3001, 'validated_features': 3001,
                                               'corridor_features': 1})
        self.assertEqual(evidence['source']['sha256'], hashlib.sha256(self.cache.read_bytes()).hexdigest())
        self.assertTrue(report['building_data_available'])
        self.assertEqual(evidence['status'], 'completed')
        self.assertEqual(evidence['scope'], 'compiled_new_road_corridors')
        self.assertTrue(any('未受显示数量上限' in warning for warning in report['warnings']))
        self.assertEqual(self.scene_path.read_bytes(), before_scene)
        self.assertEqual(self.network.read_text(), NETWORK)
        self.assertEqual(set(p.name for p in self.root.iterdir()), {'fixture.json', 'network.xml', 'skyline_scene.json'})

    def test_hole_is_open_and_full_polygon_focus_is_not_clipped_to_corridor(self):
        self.raw['buildings'] = [source_building('courtyard', rectangle(20, 70, 100, 130),
                                                [rectangle(30, 85, 90, 115)])]
        self.write_source()
        roads = [{'operation': 1, 'width_m': 9, 'segments': [[[40, 100, 0], [80, 100, 0]]]}]
        scene, _ = building_screen.load_corridor_buildings('fixture', roads, TRANSFORM)
        hits, _ = planning.building_conflicts(roads, scene, {})
        self.assertEqual(hits, [])
        roads[0]['segments'] = [[[20, 80, 0], [40, 80, 0]]]
        scene, _ = building_screen.load_corridor_buildings('fixture', roads, TRANSFORM)
        hits, _ = planning.building_conflicts(roads, scene, {})
        self.assertEqual(hits[0]['key'], 'courtyard')
        self.assertEqual(len(hits[0]['holes']), 1)
        self.assertAlmostEqual(hits[0]['focus']['x'], 60)
        self.assertAlmostEqual(hits[0]['focus']['y'], 100)

    def test_full_width_outside_cache_fails_even_when_centerline_is_inside(self):
        north = geographic([[0, 102]])[0][1]
        self.raw['metadata']['bounds'][3] = north
        self.write_source()
        with self.assertRaisesRegex(ValueError, '完整宽度走廊超出'):
            self.check()

    def test_coverage_uses_compiled_snapped_geometry_not_draft(self):
        self.raw['metadata']['bounds'][2] = geographic([[0, 95]])[0][1]
        self.raw['metadata']['bounds'][3] = geographic([[0, 105]])[0][1]
        self.write_source()
        report = self.check({**ROAD, 'points': [[0, 104], [400, 104]]})
        self.assertEqual(report['roads'][0]['segments'][0][0][:2], [0, 100])
        self.assertTrue(report['building_screen']['corridors_within_source_extent'])

    def test_source_digest_invalidates_token_even_without_new_conflict(self):
        first = self.check(building_labels={'low-building': 7})
        _, repeated = planning.check_plan('fixture_sim', first['plan'])
        self.assertEqual(first['token'], repeated['token'])
        self.raw['metadata']['revision'] = 'changed source evidence'
        self.write_source()
        changed = self.check(building_labels={'low-building': 7})
        self.assertEqual(first['conflicts'], changed['conflicts'])
        self.assertNotEqual(first['token'], changed['token'])
        with patch('wrapper.api.submit_with_id') as submit:
            with self.assertRaises(HTTPException) as error:
                run_city_plan(PlanRequest(baseline_run='fixture_sim', plan=first['plan'],
                                         check_token=first['token'], acknowledge_conflicts=True))
            self.assertEqual(error.exception.status_code, 409)
            submit.assert_not_called()
        with patch.object(ifline, 'run_simulation') as simulate:
            with self.assertRaisesRegex(ValueError, '重新检查'):
                ifline.run_ifline_scenario('fixture_sim', 'Never run', {
                    **first['plan'], 'check_token': first['token'], 'acknowledge_conflicts': True})
            simulate.assert_not_called()

    def test_no_road_operations_skip_source_and_do_not_claim_a_scan(self):
        self.cache.unlink()
        self.scene_path.unlink()
        for operation in ({'type': 'road_closure', 'link_id': 'cross'},
                          {'type': 'speed_limit', 'link_id': 'cross', 'value': 30},
                          {'type': 'capacity_scale', 'link_id': 'cross', 'value': 110}):
            with self.subTest(operation=operation), patch.object(planning, 'load_corridor_buildings') as loader:
                report = self.check(operation)
                loader.assert_not_called()
                self.assertEqual(report['conflicts'], [])
                self.assertEqual(report['building_screen']['status'], 'not_required')
                self.assertIsNone(report['building_screen']['source'])
                self.assertFalse(report['building_data_available'])
                self.assertTrue(any('未扫描建筑轮廓' in warning for warning in report['warnings']))

    def test_compile_plan_remains_pure_without_source_loading(self):
        with patch.object(planning, 'load_corridor_buildings', side_effect=AssertionError('I/O in compiler')):
            _, report = planning.compile_plan(self.network, {'operations': [ROAD]})
        self.assertFalse(report['building_data_available'])
        self.assertNotIn('building_screen', report)

    def test_mixed_and_elevated_plans_keep_operation_scope_and_planar_caution(self):
        _, report = planning.check_plan('fixture_sim', {'operations': [
            {'type': 'road_closure', 'link_id': 'cross'},
            {**ROAD, 'points': [[0, 100], [100, 100], [300, 100], [400, 100]],
             'heights': [0, 8, 8, 0]}]})
        self.assertEqual(report['building_screen']['operation_ids'], [2])
        self.assertEqual(report['conflicts'][0]['operation_ids'], [2])
        self.assertEqual(report['conflicts'][0]['key'], 'low-building')
        self.assertTrue(any('净空' in warning for warning in report['warnings']))

    def test_no_road_keeps_legacy_token_with_scene_but_does_not_inspect_bad_building(self):
        self.scene['landmarks']['buildings'] = [{'points': 'invalid display geometry'}]
        self.scene_path.write_text(json.dumps(self.scene))
        self.cache.write_text('{invalid source')
        report = self.check({'type': 'road_closure', 'link_id': 'cross'})
        legacy_digest = hashlib.sha256(self.network.read_bytes() + self.scene_path.read_bytes()
                                       + json.dumps(report['plan'], sort_keys=True).encode()).hexdigest()
        self.assertEqual(report['token'], legacy_digest)
        self.assertEqual(report['building_screen']['status'], 'not_required')

    def test_no_road_sidecar_selection_is_read_only_and_keeps_legacy_token(self):
        sidecar = self.scene_path.with_name('skyline_scene.buildings-v1.json')
        current = {**self.scene, 'roads': [], 'terrain': {}, 'building_geometry_version': 1,
                   'building_refresh': {'source_file': self.scene_path.name,
                       'source_sha256': hashlib.sha256(self.scene_path.read_bytes()).hexdigest()}}
        sidecar.write_text(json.dumps(current))
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        with patch.object(planning, 'load_corridor_buildings') as loader:
            report = self.check({'type': 'road_closure', 'link_id': 'cross'})
            loader.assert_not_called()
        self.assertEqual(report['source_scene'], sidecar.name)
        self.assertEqual(report['building_screen']['status'], 'not_required')
        legacy_digest = hashlib.sha256(self.network.read_bytes() + sidecar.read_bytes()
                                       + json.dumps(report['plan'], sort_keys=True).encode()).hexdigest()
        self.assertEqual(report['token'], legacy_digest)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.root.iterdir()})

    def test_invalid_crs_is_a_plan_check_error_not_an_unhandled_rasterio_error(self):
        self.scene['coordinate_transform']['network_crs'] = 'not-a-coordinate-system'
        self.scene_path.write_text(json.dumps(self.scene))
        with self.assertRaisesRegex(ValueError, '米制投影坐标系'):
            self.check()
        with self.assertRaises(HTTPException) as error:
            check_city_plan(PlanRequest(baseline_run='fixture_sim', plan={'operations': [ROAD]}))
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn('米制投影坐标系', error.exception.detail)

    def test_recorded_incomplete_source_is_not_mistaken_for_complete_coverage(self):
        self.raw['metadata']['diagnostics'] = {'incomplete_area': 1}
        self.write_source()
        with self.assertRaisesRegex(ValueError, '不完整面数据'):
            self.check()

    def test_missing_empty_and_malformed_sources_fail_closed(self):
        for content in (None, '{broken', '[]', '{}', '{"buildings":[]}'):
            with self.subTest(content=content):
                if content is None:
                    self.cache.unlink(missing_ok=True)
                else:
                    self.cache.write_text(content)
                with self.assertRaisesRegex(ValueError, '完整建筑源'):
                    self.check()

    def test_absent_invalid_extent_and_invalid_far_footprint_fail_closed(self):
        for bounds in (None, [], [1, -1, -1, 1], [False, 1, -1, 1], [-1, 1, float('nan'), 1]):
            with self.subTest(bounds=bounds):
                self.raw['metadata']['bounds'] = bounds
                self.write_source()
                with self.assertRaisesRegex(ValueError, '覆盖范围'):
                    self.check()
        self.raw['metadata']['bounds'] = [-0.01, 0.01, -0.01, 0.01]
        invalid = [source_building('bowtie', [[-200, -200], [-100, -100], [-200, -100], [-100, -200]]),
                   {'coords': [[0, 0], [float('nan'), 0], [0, 1]]},
                   source_building('bad-hole', rectangle(-200, -200, -100, -100),
                                   [rectangle(-50, -50, -10, -10)])]
        for entry in invalid:
            with self.subTest(entry=entry):
                self.raw['buildings'] = [source_building(), entry]
                self.write_source()
                with self.assertRaisesRegex(ValueError, '轮廓无效'):
                    self.check()

    def test_missing_region_nonmetric_crs_and_bad_scale_fail_closed(self):
        for change in ({'network_crs': 'EPSG:4326'}, {'network_crs': None},
                       {'network_crs': 'EPSG:2263'}, {'scene_units_per_metre': 0}, {'center_x': float('inf')}):
            with self.subTest(change=change):
                self.scene['coordinate_transform'] = {**TRANSFORM, **change}
                self.scene_path.write_text(json.dumps(self.scene))
                with self.assertRaises(ValueError):
                    self.check()
        self.scene['coordinate_transform'] = TRANSFORM
        self.scene_path.write_text(json.dumps(self.scene))
        self.assets['region_key'] = '../not-a-region'
        with self.assertRaisesRegex(ValueError, '区域标识'):
            self.check()


if __name__ == '__main__':
    unittest.main()
