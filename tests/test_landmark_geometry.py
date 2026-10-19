import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shapely.geometry import Point, Polygon
from wrapper.landmark_geometry import project_clip_areas
from wrapper.skyline import scene_area_layers
from wrapper.runs import refreshed_landmark_scene
from wrapper import pipeline, skyline, runs
from scripts.refresh_scene_landmarks import refresh_scene


def rectangle(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


class PolygonClippingTests(unittest.TestCase):
    def clip(self, *entries):
        return project_clip_areas(entries, (0, 0, 10, 10))

    def test_cross_boundary_area_is_clipped_not_dropped(self):
        parts, stats = self.clip({'coords': rectangle(-2, 2, 4, 8)})
        self.assertEqual(parts[0][1].area, 24)
        self.assertEqual(stats['clipped'], 1)

    def test_surrounding_area_with_no_vertex_inside_is_retained(self):
        parts, _ = self.clip({'coords': rectangle(-2, -2, 12, 12)})
        self.assertEqual(parts[0][1].area, 100)

    def test_outside_and_boundary_only_touch_have_no_surface(self):
        parts, stats = self.clip({'coords': rectangle(-2, 2, 0, 8)},
                                 {'coords': rectangle(20, 20, 22, 22)})
        self.assertEqual(parts, [])
        self.assertEqual(stats['outside'], 2)

    def test_holes_survive_clipping(self):
        parts, _ = self.clip({'coords': rectangle(-2, -2, 12, 12),
                             'holes': [rectangle(4, 4, 6, 6)]})
        self.assertEqual(parts[0][1].area, 96)
        self.assertFalse(parts[0][1].contains(Point(5, 5)))

    def test_concave_intersection_can_split_without_connecting_bridge(self):
        # U-shaped area connected below the viewport.
        ring = [[1,-2],[9,-2],[9,8],[7,8],[7,-1],[3,-1],[3,8],[1,8]]
        parts, stats = self.clip({'coords': ring})
        self.assertEqual(len(parts), 2)
        self.assertEqual(stats['kept_features'], 1)
        self.assertEqual(sum(p.area for _, p, _ in parts), 32)
        self.assertTrue(all(not p.contains(Point(5, 5)) for _, p, _ in parts))

    def test_repair_retains_both_bowtie_lobes(self):
        parts, stats = self.clip({'coords': [[1,1],[9,9],[1,9],[9,1]]})
        self.assertEqual(stats['repaired'], 1)
        self.assertEqual(len(parts), 2)
        self.assertEqual(sum(p.area for _, p, _ in parts), 32)

    def test_bad_coordinate_does_not_create_a_replacement_edge(self):
        parts, stats = self.clip({'coords': [[0,0],[float('nan'),0],[2,2],[0,2]]},
                                 {'coords': rectangle(1,1,3,3)})
        self.assertEqual(stats['invalid'], 1)
        self.assertEqual(len(parts), 1)

    def test_valid_thin_polygon_is_not_rejected(self):
        ring = [[0,0],[10,9],[10,9.01],[0,0.01]]
        parts, _ = self.clip({'coords': ring})
        self.assertAlmostEqual(parts[0][1].area, Polygon(ring).area)

    def test_legacy_open_ring_and_duplicate_endpoint_work(self):
        parts, _ = self.clip({'coords': [[1,1],[3,1],[3,1],[3,3],[1,3]]})
        self.assertEqual(parts[0][1].area, 4)

    def test_projection_uses_target_coordinates(self):
        parts, _ = project_clip_areas([{'coords': rectangle(0,0,0.01,0.01)}],
                                      (0,0,1000,1000), 'EPSG:4326', 'EPSG:3857')
        self.assertAlmostEqual(parts[0][1].area, 1000000)


class SceneLandmarkRefreshTests(unittest.TestCase):
    def setUp(self):
        self.transform = {'network_crs': 'EPSG:4326', 'center_x': 0, 'center_y': 0,
                          'scene_units_per_metre': 1}
        self.terrain = {'min_x':0,'min_z':0,'max_x':10,'max_z':10,
                        'nx':2,'nz':2,'heights':[0,0,0,0]}
        self.raw = {'parks': [{'coords': rectangle(-2,-2,12,12),
                              'holes':[rectangle(4,4,6,6)], 'osm_id':'relation/1'}]}

    def test_scene_preserves_holes_id_and_reports_clipping(self):
        layers, diagnostics = scene_area_layers(self.raw, self.transform, self.terrain)
        self.assertEqual(layers['parks'][0]['osm_id'], 'relation/1')
        self.assertEqual(len(layers['parks'][0]['holes']), 1)
        self.assertEqual(diagnostics['parks']['clipped'], 1)

    def test_low_rise_neighbourhoods_are_not_removed_by_height_cap(self):
        buildings = [{'coords': rectangle((i % 60)*.1, (i // 60)*.1,
                                          (i % 60)*.1+.08, (i // 60)*.1+.08),
                      'height': 9 if i % 2 else 100, 'osm_id': f'way/{i}'}
                     for i in range(3102)]
        layers, diagnostics = scene_area_layers({'buildings': buildings}, self.transform, self.terrain)
        self.assertEqual(len(layers['buildings']), 3102)
        self.assertEqual(diagnostics['buildings']['omitted_by_limit'], 0)
        self.assertEqual({b['osm_id'] for b in layers['buildings']}, {b['osm_id'] for b in buildings})
        self.assertEqual(sum(b['height_m'] == 9 for b in layers['buildings']), 1551)

    def test_coverage_checks_full_display_extent_and_unknown_is_not_complete(self):
        for bounds, expected in [([-1,11,-1,11],'complete'), ([0,4,0,4],'partial'),
                                 ([0,10,0,10],'complete'), ([10,0,10,0],'unknown'),
                                 ([0,float('nan'),0,10],'unknown'), (None,'unknown')]:
            raw = {'metadata': {'bounds': bounds}}
            result = skyline.landmark_coverage(raw, self.transform, self.terrain)
            self.assertEqual(result['status'], expected)
            self.assertEqual(result['required_bounds_wesn'], [0,10,0,10])
        self.assertEqual(skyline.landmark_coverage({}, self.transform, self.terrain)['status'], 'unknown')

    def test_native_bounds_and_wesn_order_and_invalid_scale(self):
        tr = {**self.transform, 'center_x':20, 'center_y':30, 'scene_units_per_metre':2}
        self.assertEqual(skyline.scene_native_bounds(tr, self.terrain), (20,30,25,35))
        self.assertEqual(skyline.scene_geographic_bounds(tr, self.terrain), [20,25,30,35])
        for scale in (0,-1,float('nan')):
            with self.assertRaises(ValueError):
                skyline.scene_native_bounds({**tr,'scene_units_per_metre':scale}, self.terrain)

    def test_full_scene_export_retains_roads_vehicles_and_point_line_layers(self):
        # Synthetic export fixture only; no simulator or real output required.
        link = {'x1':0,'y1':0,'x2':10,'y2':10,'from':'a','to':'b',
                'length':100,'freespeed':10,'lanes':1,'capacity':1000,
                'oneway':True,'modes':'car'}
        raw = {**self.raw, 'libraries':[{'lon':1,'lat':1,'name':'Library'}],
               'tram_ways':[{'coords':[[1,1],[2,2],[50,50]]}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'fixture_sim').mkdir()
            with patch.object(skyline,'OUTPUT_DIR',root), \
                    patch.object(skyline,'NETWORK_CRS','EPSG:4326'), \
                    patch.object(skyline,'_parse_events',return_value=({'7':2},{'7':[12]})), \
                    patch.object(skyline,'_network_data',return_value=({'a':(0,0),'b':(10,10)},{'7':link})), \
                    patch.object(skyline,'_vehicle_trip_segments',return_value={'v':[[(0,'7'),(12,'7')]]}), \
                    patch.object(skyline,'_sample_elevations',side_effect=lambda xs,ys:[0]*len(xs)), \
                    patch.object(skyline,'_load_landmarks',return_value=raw):
                path = skyline.render_skyline_scene('fixture_sim',region_key='cbd')
            scene = json.loads(path.read_text())
        self.assertEqual(scene['landmark_geometry_version'],2)
        self.assertEqual(scene['total_volume'],2)
        self.assertEqual(scene['roads'][0]['link_id'],'7')
        self.assertEqual(len(scene['vehicles']),1)
        self.assertEqual(scene['sim_time_range'],[0,12])
        self.assertEqual(len(scene['landmarks']['parks'][0]['holes']),1)
        self.assertEqual(scene['landmarks']['libraries'][0]['name'],'Library')
        self.assertEqual(len(scene['landmarks']['tram_lines']),1)

    def test_refresh_preserves_traffic_and_original_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'ifline_scene.json'
            cache = Path(directory) / 'cache.json'
            original = {'coordinate_transform': self.transform, 'terrain': self.terrain,
                        'roads':[{'id':'7','severity':0.7,'delta':2}],
                        'vehicles':[{'trips':[[[1,2,3,4],[5,6,7,8]]]}],
                        'sim_time_range':[1,5], 'total_volume':42, 'ifline':{'baseline':'abc'},
                        'landmarks': {'libraries':[{'name':'preserve'}], 'tram_lines':[{'id':'8'}]}}
            source.write_text(json.dumps(original))
            cache.write_text(json.dumps(self.raw))
            old_bytes = source.read_bytes()
            dest, _ = refresh_scene(source, cache, 'cbd')
            refreshed = json.loads(dest.read_text())
            self.assertEqual(source.read_bytes(), old_bytes)
            for key in original.keys() - {'landmarks'}:
                self.assertEqual(refreshed[key], original[key])
            self.assertEqual(refreshed['landmarks']['libraries'], original['landmarks']['libraries'])
            self.assertEqual(refreshed['landmarks']['tram_lines'], original['landmarks']['tram_lines'])
            self.assertEqual(refreshed_landmark_scene(source), dest)
            # Changing the source invalidates a refresh, even if filenames match.
            source.write_text(json.dumps({**original, 'total_volume':43}))
            self.assertIsNone(refreshed_landmark_scene(source))

    def test_invalid_or_wrong_source_sidecar_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'skyline_scene.json'
            source.write_text('{}')
            dest = source.with_name('skyline_scene.landuse-v2.json')
            for content in ('{broken', 'null', '{}', json.dumps({
                    'roads':[], 'terrain':{}, 'landmarks':{}, 'landmark_geometry_version':2,
                    'landmark_refresh':{'source_file':'ifline_scene.json',
                        'source_sha256':hashlib.sha256(b'{}').hexdigest()}})):
                dest.write_text(content)
                self.assertIsNone(refreshed_landmark_scene(source))

    def test_loader_and_input_record_choose_same_v2_cache_with_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            landmarks = root/'landmarks'
            (landmarks/'v2').mkdir(parents=True)
            legacy = landmarks/'cbd.json'
            modern = landmarks/'v2'/'cbd.json'
            legacy.write_text('{"parks":[]}')
            with patch.object(skyline, 'LANDMARKS_DIR', landmarks), \
                    patch.object(pipeline, 'DATA_DIR', root), \
                    patch('wrapper.provenance.PROJECT_ROOT', root):
                self.assertEqual(skyline.landmark_cache_path('cbd'), legacy)
                modern.write_text(json.dumps(self.raw))
                self.assertEqual(skyline._load_landmarks('cbd'), self.raw)
                snapshot = pipeline._input_snapshot('cbd')['landmarks']
                self.assertTrue(snapshot['path'].endswith('landmarks/v2/cbd.json'))
                self.assertEqual(snapshot['sha256'], hashlib.sha256(modern.read_bytes()).hexdigest())
                (landmarks/'expanded').mkdir()
                expanded = landmarks/'expanded'/'cbd.json'
                expanded.write_text(json.dumps({'buildings':[], 'metadata':{'bounds':[0,10,0,10]}}))
                self.assertEqual(skyline.landmark_cache_path('cbd'), expanded)
                self.assertEqual(pipeline._input_snapshot('cbd')['landmarks']['sha256'],
                                 hashlib.sha256(expanded.read_bytes()).hexdigest())

    def test_ifline_payload_never_uses_baseline_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sim = root/'demo_sim'
            sim.mkdir()
            for name in runs.REQUIRED_RESULT_FILES:
                (sim/name).write_text('fixture')
            cache = root/'cache.json'
            cache.write_text(json.dumps(self.raw))
            data = {'coordinate_transform': self.transform, 'terrain': self.terrain, 'roads':[]}
            for name in ('skyline_scene.json','ifline_scene.json'):
                (sim/name).write_text(json.dumps(data))
                refresh_scene(sim/name, cache, 'cbd')
            with patch.object(runs, 'OUTPUT_DIR', root), \
                    patch.object(runs, 'compute_summary_data', return_value={}), \
                    patch.object(runs, '_ifline_record', return_value={'comparison':{'check':1}}):
                result = runs.result_payload('demo_sim')
            self.assertEqual(result['skyline_scene_url'], '/results/demo_sim/ifline_scene.landuse-v2.json')
            self.assertEqual(result['result_source'], 'existing_ifline_replay')
            self.assertEqual(result['recorded_ifline_comparison'], {'check':1})
            self.assertNotIn('ifline_comparison', result)
            self.assertIn('comparison_unavailable_reason', result)


class OsmAreaExtractionTests(unittest.TestCase):
    def test_closed_way_and_split_relation_with_hole(self):
        try:
            from scripts.extract_landmarks import LandmarkHandler
        except ModuleNotFoundError as error:
            if error.name != 'osmium':
                raise
            self.skipTest('osmium optional data-preparation dependency not installed')
        nodes = [(1,-2,-2),(2,12,-2),(3,12,12),(4,-2,12),
                 (5,4,4),(6,6,4),(7,6,6),(8,4,6),
                 (9,1,1),(10,3,1),(11,3,3),(12,1,3)]
        text = '<osm version="0.6">'
        for i,x,y in nodes:
            text += f'<node id="{i}" lon="{x}" lat="{y}"/>'
        for i, refs, tags in [(1,[1,2,3],''),(2,[3,4,1],''),(3,[5,6,7,8,5],''),
                              (4,[9,10,11,12,9],'<tag k="leisure" v="park"/>')]:
            text += f'<way id="{i}">' + ''.join(f'<nd ref="{n}"/>' for n in refs) + tags + '</way>'
        text += ('<relation id="10"><member type="way" ref="1" role="outer"/>'
                 '<member type="way" ref="2" role="outer"/>'
                 '<member type="way" ref="3" role="inner"/>'
                 '<tag k="type" v="multipolygon"/><tag k="natural" v="water"/>'
                 '</relation></osm>')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'fixture.osm'
            path.write_text(text)
            handler = LandmarkHandler(0,10,0,10)
            handler.apply_file(str(path), locations=True)
        self.assertEqual(len(handler.parks), 1)
        self.assertEqual(handler.parks[0]['osm_id'], 'way/4')
        self.assertEqual(len(handler.water), 1)
        self.assertEqual(handler.water[0]['osm_id'], 'relation/10')
        self.assertEqual(len(handler.water[0]['holes']), 1)


if __name__ == '__main__':
    unittest.main()
