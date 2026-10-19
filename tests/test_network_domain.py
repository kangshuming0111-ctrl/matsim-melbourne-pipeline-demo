import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rasterio.warp import transform
from shapely.geometry import Polygon, box

from wrapper import network_domain as domain


PLANS = '''<population><person id="private-person"><plan selected="yes">
<activity type="Home" x="2495000" y="2408000"/><leg mode="car"/>
<activity type="Work" x="2495100" y="2408100"/>
</plan></person></population>'''
NETWORK = '''<network><nodes>
<node id="a" x="2494900" y="2407900"/><node id="b" x="2495200" y="2408200"/>
</nodes><links><link id="ab" from="a" to="b" modes="car"/></links></network>'''


class NetworkDomainTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data, self.output = self.root / 'data', self.root / 'output'
        self.data.mkdir()
        self.output.mkdir()
        for name, value in [('DATA_DIR', self.data), ('OUTPUT_DIR', self.output)]:
            patcher = patch.object(domain, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.plans = self.root / 'plans.xml'
        self.plans.write_text(PLANS)
        self.network = self.root / 'network.xml'
        self.network.write_text(NETWORK)

    def prepare(self, name='example', **kwargs):
        opts = dict(output_name=name, plans_crs=7899, max_buffered_area_km2=25,
                    network_buffer_m=500)
        opts.update(kwargs)
        return domain.prepare_activity_domain(self.plans, **opts)

    def manifest(self, name='example'):
        return json.loads((self.output / f'{name}_domain/domain_manifest.json').read_text())

    def test_native_bbox_serialized_as_unbuffered_wgs84_preserves_source(self):
        before = self.plans.read_bytes()
        result = self.prepare()
        geo = json.loads((self.data / result.region_file).read_text())
        ring = geo['features'][0]['geometry']['coordinates'][0]
        xs, ys = transform('EPSG:4326', 'EPSG:7899', *zip(*ring))
        restored = Polygon(zip(xs, ys))
        self.assertLess(restored.hausdorff_distance(box(2495000, 2408000, 2495100, 2408100)), .1)
        self.assertLess(abs(restored.area - 10000), .1)
        self.assertEqual(self.plans.read_bytes(), before)
        self.assertEqual(result.plans_sha256, hashlib.sha256(before).hexdigest())
        m = self.manifest()
        self.assertEqual(m['status'], 'prepared')
        self.assertFalse(m['geojson_is_buffered'])
        self.assertEqual(m['network_buffer_m'], 500)
        self.assertEqual(m['activity_inventory']['activities'], 2)
        self.assertNotIn('private-person', json.dumps(m) + json.dumps(geo))
        json.dumps(m, allow_nan=False)

    def test_boundary_is_densified_not_only_four_corners(self):
        self.plans.write_text(PLANS.replace('2495100', '2497000'))
        d = self.prepare()
        ring = json.loads((self.data / d.region_file).read_text())['features'][0]['geometry']['coordinates'][0]
        self.assertGreater(len(ring), 5)
        self.assertLessEqual(self.manifest()['domain_geometry']['python_roundtrip_hausdorff_m'], .1)

    def test_namespaces_gzip_act_and_unmarked_single_plan(self):
        self.plans = self.root / 'plans.xml.gz'
        with gzip.open(self.plans, 'wt') as f:
            f.write(PLANS.replace('<population>', '<population xmlns="urn:test">')
                    .replace('activity', 'act').replace(' selected="yes"', ''))
        d = self.prepare()
        self.assertTrue(d.evidence_path.is_file())
        self.assertEqual(self.manifest()['activity_inventory']['finite_coordinates'], 2)

    def test_invalid_coordinates_fail_without_silently_dropping_activities(self):
        for index, replacement in enumerate(('x="nan"', 'x="inf"', 'x="bad"', '')):
            with self.subTest(replacement=replacement):
                self.plans.write_text(PLANS.replace('x="2495100"', replacement))
                with self.assertRaisesRegex(ValueError, 'finite-coordinate'):
                    self.prepare(f'bad{index}')
                m = self.manifest(f'bad{index}')
                self.assertEqual(m['status'], 'failed')
                self.assertEqual(m['activity_inventory']['activities'], 2)
                self.assertEqual(m['activity_inventory']['finite_coordinates'], 1)
        self.assertEqual(list(self.data.glob('*.geojson')), [])

    def test_ambiguous_alternate_empty_and_network_bound_plans_rejected(self):
        variants = [PLANS.replace('</person>', '<plan selected="no"/></person>'),
                    PLANS.replace('selected="yes"', 'selected="no"'),
                    '<population><person id="p"><plan/></person></population>',
                    PLANS.replace('type="Home"', 'type="Home" link="old"'),
                    PLANS.replace('<leg mode="car"/>', '<leg mode="car"><route/></leg>')]
        for i, content in enumerate(variants):
            with self.subTest(i=i):
                self.plans.write_text(content)
                with self.assertRaises(ValueError):
                    self.prepare(f'bad{i}')
                self.assertEqual(self.manifest(f'bad{i}')['status'], 'failed')

    def test_empty_degenerate_and_oversized_population_domains_rejected(self):
        for i, content in enumerate(('<population/>', PLANS.replace('2495100', '2495000'),
                                      PLANS.replace('2495100', '2595100'))):
            with self.subTest(i=i):
                self.plans.write_text(content)
                with self.assertRaises(ValueError):
                    self.prepare(f'bad{i}')
                self.assertEqual(self.manifest(f'bad{i}')['status'], 'failed')
        self.assertEqual(list(self.data.glob('*.geojson')), [])

    def test_unknown_crs_invalid_budget_buffer_and_traversal_rejected(self):
        for options in ({'plans_crs': 4326}, {'max_buffered_area_km2': None},
                        {'max_buffered_area_km2': float('nan')}, {'network_buffer_m': 0},
                        {'network_buffer_m': True}, {'output_name': '../escape'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.prepare(**options)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_output_collision_preserves_first_manifest_and_geojson(self):
        d = self.prepare()
        original = d.evidence_path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual(d.evidence_path.read_bytes(), original)
        self.assertEqual(len(list(self.data.glob('*.geojson'))), 1)

    def test_successful_post_cleaning_gate_has_hashed_audit_not_transport_claim(self):
        d = self.prepare()
        report = domain.audit_activity_network(d, self.network)
        m = self.manifest()
        self.assertEqual(m['status'], 'completed')
        self.assertTrue(m['post_cleaning_gate']['passed'])
        self.assertTrue(all(m['post_cleaning_gate']['checks'].values()))
        self.assertEqual(report['activities']['inside_node_bbox'], 2)
        self.assertEqual(m['coverage_after']['sha256'], hashlib.sha256(d.coverage_path.read_bytes()).hexdigest())
        self.assertIn('not transport', m['post_cleaning_gate']['meaning'])

    def test_incomplete_bbox_gate_saves_audit_before_raising(self):
        d = self.prepare()
        self.network.write_text(NETWORK.replace('2495200', '2495050'))
        with self.assertRaisesRegex(ValueError, 'gate failed'):
            domain.audit_activity_network(d, self.network)
        self.assertTrue(d.coverage_path.is_file())
        m = self.manifest()
        self.assertEqual(m['status'], 'failed')
        self.assertFalse(m['post_cleaning_gate']['passed'])
        self.assertEqual(json.loads(d.coverage_path.read_text())['activities']['outside_node_bbox'], 1)

    def test_changed_plans_or_region_and_nonfinite_network_stop_gate(self):
        for i, mutate in enumerate((lambda d: self.plans.write_text(PLANS + '\n'),
                                    lambda d: (self.data / d.region_file).write_text('{}'),
                                    lambda d: self.network.write_text(NETWORK.replace('2495200', 'nan')))):
            with self.subTest(i=i):
                self.plans.write_text(PLANS)
                self.network.write_text(NETWORK)
                d = self.prepare(f'changed{i}')
                mutate(d)
                with self.assertRaises(ValueError):
                    domain.audit_activity_network(d, self.network)
                self.assertEqual(self.manifest(f'changed{i}')['status'], 'failed')

    def test_parse_errors_preserve_failure_manifest(self):
        self.plans.write_text('<population><broken>')
        with self.assertRaises(Exception):
            self.prepare()
        self.assertEqual(self.manifest()['status'], 'failed')

    def test_finite_coordinate_overflow_has_json_safe_failure_record(self):
        self.plans.write_text(PLANS.replace('2495000', '-1e308').replace('2495100', '1e308'))
        with self.assertRaisesRegex(ValueError, 'overflow'):
            self.prepare()
        self.assertEqual(self.manifest()['status'], 'failed')
        json.dumps(self.manifest(), allow_nan=False)


if __name__ == '__main__':
    unittest.main()
