from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wrapper import network_domain, scenario
from test_network_domain import PLANS, NETWORK


class ScenarioActivityDomainTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.data, self.output = self.root/'data', self.root/'output'
        self.data.mkdir()
        self.output.mkdir()
        (self.data/'cache.pbf').write_bytes(b'original')
        stack = ExitStack()
        self.addCleanup(stack.close)
        for module in (scenario, network_domain):
            for attr, value in [('DATA_DIR', self.data), ('OUTPUT_DIR', self.output)]:
                stack.enter_context(patch.object(module, attr, value))
        self.order = []
        self.image = stack.enter_context(patch.object(scenario, 'network_image_exists', return_value=True))
        self.derive = stack.enter_context(patch.object(scenario, 'derive_sa1_subset', side_effect=self.select))
        self.demand = stack.enter_context(patch.object(scenario, 'run_demand', side_effect=self.generate_demand))
        self.network = stack.enter_context(patch.object(scenario, 'run_network', side_effect=self.generate_network))

    def select(self, region, buffer, name):
        self.order.append('sa1')
        (self.data/name).write_text('subset')

    def generate_demand(self, config):
        self.order.append('demand')
        directory = self.output/config.output_subdir
        (directory/'8.xml').mkdir(parents=True)
        (directory/'8.xml/plan.xml').write_text(PLANS)
        return directory

    def generate_network(self, config):
        self.order.append('network')
        if config.cached_only:
            self.assertTrue((self.output/'fresh_domain/domain_manifest.json').is_file())
            self.assertTrue((self.data/config.region_file).is_file())
        directory = self.output/config.output_subdir
        directory.mkdir()
        (directory/'network.xml').write_text(NETWORK)
        return directory

    def run_new(self, **kwargs):
        options = dict(region_file='original.geojson', output_name='fresh', buffer_dist=123,
                       num_plans=500, sample_percent=5, demand_random_seed=4711,
                       osm_pbf_file='cache.pbf', network_domain='activity_bbox',
                       network_buffer_m=500, max_network_area_km2=25)
        options.update(kwargs)
        return scenario.run_scenario(**options)

    def test_demand_first_once_independent_buffers_and_unchanged_plans(self):
        network, demand = self.run_new()
        self.assertEqual(self.order, ['sa1', 'demand', 'network'])
        self.derive.assert_called_once_with('original.geojson', 123, 'fresh_sa1_subset.csv')
        self.assertEqual(self.network.call_args.args[0].region_buffer_dist, 500)
        self.assertTrue(self.network.call_args.args[0].cached_only)
        self.assertEqual(self.demand.call_count, 1)
        self.assertEqual((demand/'8.xml/plan.xml').read_text(), PLANS)
        self.assertEqual(network.name, 'fresh_network')
        m = json.loads((self.output/'fresh_domain/domain_manifest.json').read_text())
        self.assertTrue(m['post_cleaning_gate']['passed'])

    def test_legacy_order_and_buffer_are_unchanged(self):
        scenario.run_scenario('original.geojson', 'fresh', buffer_dist=123)
        self.assertEqual(self.order, ['network', 'sa1', 'demand'])
        self.assertEqual(self.network.call_args.args[0].region_file, 'original.geojson')
        self.assertEqual(self.network.call_args.args[0].region_buffer_dist, 123)
        self.assertFalse(self.network.call_args.args[0].cached_only)
        self.assertFalse((self.output/'fresh_domain').exists())

    def test_missing_budget_cache_unknown_strategy_fail_before_external_work(self):
        for options in ({'max_network_area_km2': None}, {'osm_pbf_file': None},
                        {'network_domain': 'typo'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.run_new(**options)
        self.assertEqual(self.order, [])

    def test_nonfinite_demand_prevents_network_generation(self):
        def generate(config):
            directory = self.generate_demand(config)
            (directory/'8.xml/plan.xml').write_text(PLANS.replace('2495100', 'nan'))
            return directory
        self.demand.side_effect = generate
        with self.assertRaisesRegex(ValueError, 'finite-coordinate'):
            self.run_new()
        self.network.assert_not_called()
        self.assertEqual(json.loads((self.output/'fresh_domain/domain_manifest.json').read_text())['status'], 'failed')

    def test_network_failure_keeps_prepared_evidence_and_does_not_fallback(self):
        self.network.side_effect = RuntimeError('fixture generator failed')
        with self.assertRaisesRegex(RuntimeError, 'fixture generator failed'):
            self.run_new()
        self.assertEqual(self.network.call_count, 1)
        self.assertEqual(self.demand.call_count, 1)
        self.assertEqual(json.loads((self.output/'fresh_domain/domain_manifest.json').read_text())['status'], 'failed')

    def test_post_cleaning_failure_is_fatal_with_saved_audit(self):
        def generate(config):
            directory = self.generate_network(config)
            (directory/'network.xml').write_text(NETWORK.replace('2495200', '2495050'))
            return directory
        self.network.side_effect = generate
        with self.assertRaisesRegex(ValueError, 'gate failed'):
            self.run_new()
        self.assertTrue((self.output/'fresh_domain/coverage_after.json').is_file())
        self.assertEqual(self.network.call_count, 1)

    def test_existing_outputs_are_not_reused(self):
        (self.output/'fresh_demand').mkdir()
        with self.assertRaises(FileExistsError):
            self.run_new()
        self.assertEqual(self.order, [])

    def test_stale_or_missing_network_image_stops_before_any_expensive_stage(self):
        self.image.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'before demand generation'):
            self.run_new()
        self.derive.assert_not_called()
        self.demand.assert_not_called()
        self.network.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_docker_unavailable_has_actionable_early_error(self):
        self.image.side_effect = FileNotFoundError('docker')
        with self.assertRaisesRegex(RuntimeError, 'start Docker'):
            self.run_new()
        self.assertEqual(self.order, [])


if __name__ == '__main__':
    unittest.main()
