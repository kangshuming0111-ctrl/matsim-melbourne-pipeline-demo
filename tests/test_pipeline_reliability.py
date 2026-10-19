import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack

from wrapper import pipeline, scenario, network_domain
from test_network_domain import PLANS, NETWORK


class PipelineReliabilityTests(unittest.TestCase):
    def test_failed_external_stage_leaves_failed_manifest(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            output = root / "output"
            data = root / "data"
            output.mkdir()
            data.mkdir()
            (data / "sample_region.geojson").write_text("{}")

            with patch.object(pipeline, "OUTPUT_DIR", output), \
                    patch.object(pipeline, "DATA_DIR", data), \
                    patch("wrapper.provenance.code_snapshot", return_value={"git_commit": "test"}), \
                    patch("wrapper.provenance.environment_snapshot", return_value={"python": "test"}), \
                    patch.object(pipeline, "run_scenario", side_effect=RuntimeError("docker failed")):
                with self.assertRaisesRegex(RuntimeError, "docker failed"):
                    pipeline.run_full_pipeline(region_key="cbd", run_name="failure_demo")

            manifest_path = output / "run_records" / "failure_demo" / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text())

        self.assertEqual(manifest["status"], "failed")
        self.assertFalse(manifest["verification"]["passed"])
        self.assertEqual(manifest["error"]["type"], "RuntimeError")
        self.assertEqual(manifest["steps"][0]["status"], "failed")
        self.assertEqual(manifest["logs"]["network_console"],
                         "output/process_logs/failure_demo_network.log")
        self.assertEqual(manifest["logs"]["simulation_console"],
                         "output/process_logs/failure_demo_sim.log")

    def test_completion_verification_requires_clean_shutdown(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            sim = output / "demo_sim"
            sim.mkdir()
            (sim / "logfile.log").write_text("unexpectedly terminated")
            artifacts = {
                "example": {"exists": True, "size_bytes": 1},
            }
            summary = {"person_count": 10, "total_trips": 20, "num_iterations": 3}

            with patch.object(pipeline, "OUTPUT_DIR", output):
                with self.assertRaisesRegex(RuntimeError, "successful shutdown"):
                    pipeline._verify_completed_run("demo", summary, artifacts)


class ActivityDomainPipelineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.data, self.output = self.root/'data', self.root/'output'
        self.data.mkdir()
        self.output.mkdir()
        (self.data/pipeline.VICTORIA_OSM_PBF).write_bytes(b'pbf')
        stack = ExitStack()
        self.addCleanup(stack.close)
        for module in (pipeline, scenario, network_domain):
            for field, value in [('DATA_DIR', self.data), ('OUTPUT_DIR', self.output)]:
                stack.enter_context(patch.object(module, field, value))
        stack.enter_context(patch('wrapper.provenance.PROJECT_ROOT', self.root))
        stack.enter_context(patch('wrapper.provenance.code_snapshot', return_value={}))
        stack.enter_context(patch('wrapper.provenance.environment_snapshot', return_value={}))
        stack.enter_context(patch.object(pipeline, '_input_snapshot', return_value={}))
        stack.enter_context(patch.object(pipeline, '_artifacts', return_value={}))
        stack.enter_context(patch.object(pipeline, 'summarize'))
        stack.enter_context(patch.object(pipeline, 'render_skyline_scene'))
        stack.enter_context(patch.object(pipeline, 'compute_summary_data', return_value={
            'person_count': 1, 'total_trips': 1, 'num_iterations': pipeline.DEFAULT_LAST_ITERATION+1}))
        self.simulate = stack.enter_context(patch.object(pipeline, 'run_simulation', side_effect=self.fake_sim))
        stack.enter_context(patch.object(scenario, 'derive_sa1_subset', side_effect=self.fake_subset))
        self.demand = stack.enter_context(patch.object(scenario, 'run_demand', side_effect=self.fake_demand))
        self.network = stack.enter_context(patch.object(scenario, 'run_network', side_effect=self.fake_network))
        self.plans_content, self.network_content = PLANS, NETWORK
        self.image = stack.enter_context(patch.object(scenario, 'network_image_exists', return_value=True))

    def fake_subset(self, region, buffer, name):
        (self.data/name).write_text('fixture')

    def fake_demand(self, config):
        directory = self.output/config.output_subdir
        (directory/'8.xml').mkdir(parents=True)
        (directory/'8.xml/plan.xml').write_text(self.plans_content)
        return directory

    def fake_network(self, config):
        directory = self.output/config.output_subdir
        directory.mkdir()
        (directory/'network.xml').write_text(self.network_content)
        return directory

    def fake_sim(self, **kwargs):
        directory = self.output/kwargs['output_subdir']
        directory.mkdir()
        (directory/'logfile.log').write_text('shutdown completed')
        return directory

    def record(self, name='fresh'):
        return json.loads((self.output/f'run_records/{name}/run_manifest.json').read_text())

    def test_cbd_explicit_v2_keeps_experimental_status_and_copies_hashed_evidence(self):
        result = pipeline.run_full_pipeline(region_key='cbd', run_name='fresh')
        self.simulate.assert_called_once()
        self.assertTrue(self.network.call_args.args[0].cached_only)
        self.assertEqual(result['profile_id'], 'cbd_activity_domain_v2')
        self.assertEqual(result['validation_status'], 'experimental')
        m = self.record()
        self.assertEqual(m['status'], 'completed')
        self.assertEqual(m['configuration']['network_domain_policy'], 'activity_bbox')
        self.assertEqual(m['verification']['validation_status'], 'experimental')
        self.assertEqual(m['profile']['validation_status'], 'experimental')
        self.assertEqual(m['inputs']['fixed_plans']['sha256'],
                         network_domain.sha256_file(self.output/'fresh_demand/8.xml/plan.xml'))
        for key, filename in [('network_domain_manifest', 'domain_manifest.json'),
                              ('network_coverage_after', 'coverage_after.json')]:
            source = self.output/'fresh_domain'/filename
            target = self.output/'run_records/fresh/artifacts'/filename
            self.assertEqual(source.read_bytes(), target.read_bytes())
            self.assertEqual(m['artifacts'][key]['sha256'], network_domain.sha256_file(target))
            self.assertEqual(m['artifacts'][key]['path'], f'output/run_records/fresh/artifacts/{filename}')

    def test_bbox_gate_failure_records_audit_and_never_starts_simulation(self):
        self.network_content = NETWORK.replace('2495200', '2495050')
        with self.assertRaisesRegex(ValueError, 'gate failed'):
            pipeline.run_full_pipeline(region_key='cbd', run_name='fresh')
        self.simulate.assert_not_called()
        m = self.record()
        self.assertEqual(m['status'], 'failed')
        self.assertTrue(m['artifacts']['network_domain_manifest']['exists'])
        self.assertTrue(m['artifacts']['network_coverage_after']['exists'])
        audit = json.loads((self.output/'run_records/fresh/artifacts/coverage_after.json').read_text())
        self.assertEqual(audit['activities']['outside_node_bbox'], 1)
        domain = json.loads((self.output/'run_records/fresh/artifacts/domain_manifest.json').read_text())
        self.assertFalse(domain['post_cleaning_gate']['passed'])

    def test_nonfinite_input_records_failure_without_network_or_simulation(self):
        self.plans_content = PLANS.replace('2495100', 'nan')
        with self.assertRaisesRegex(ValueError, 'finite-coordinate'):
            pipeline.run_full_pipeline(region_key='cbd', run_name='fresh')
        self.network.assert_not_called()
        self.simulate.assert_not_called()
        self.assertTrue(self.record()['artifacts']['network_domain_manifest']['exists'])
        self.assertFalse(self.record()['artifacts']['network_coverage_after']['exists'])

    def test_generation_error_retains_domain_without_fabricating_audit(self):
        self.network.side_effect = RuntimeError('fixture R failure')
        with self.assertRaisesRegex(RuntimeError, 'fixture R failure'):
            pipeline.run_full_pipeline(region_key='cbd', run_name='fresh')
        self.simulate.assert_not_called()
        self.assertTrue(self.record()['artifacts']['network_domain_manifest']['exists'])
        self.assertFalse(self.record()['artifacts']['network_coverage_after']['exists'])

    def test_changed_input_after_gate_stops_before_simulation(self):
        real_scenario = pipeline.run_scenario
        def changed(**kwargs):
            paths = real_scenario(**kwargs)
            with (paths[1]/'8.xml/plan.xml').open('a') as f:
                f.write('\n')
            return paths
        with patch.object(pipeline, 'run_scenario', side_effect=changed):
            with self.assertRaisesRegex(RuntimeError, 'changed after the domain gate'):
                pipeline.run_full_pipeline(region_key='cbd', run_name='fresh')
        self.simulate.assert_not_called()

    def test_other_region_retains_legacy_strategy_and_explicit_experimental_profile(self):
        result = pipeline.run_full_pipeline(region_key='inner_north', run_name='fresh')
        config = self.network.call_args.args[0]
        self.assertEqual(config.region_file, 'region_inner_north.geojson')
        self.assertFalse(config.cached_only)
        self.assertEqual(result['profile_id'], 'experimental_inner_north_v1')
        self.assertEqual(result['validation_status'], 'experimental')
        self.assertEqual(self.record()['configuration']['network_domain_policy'], 'region')
        self.assertNotIn('network_domain_manifest', self.record()['artifacts'])
        self.assertFalse((self.output/'fresh_domain').exists())

    def test_all_available_regions_are_experimental(self):
        self.assertTrue(all(r['validation'] == 'experimental' for r in pipeline.AVAILABLE_REGIONS.values()))

    def test_stale_image_failure_is_recorded_before_demand(self):
        self.image.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'before demand generation'):
            pipeline.run_full_pipeline(region_key='cbd', run_name='fresh')
        self.demand.assert_not_called()
        self.network.assert_not_called()
        self.simulate.assert_not_called()
        self.assertEqual(self.record()['status'], 'failed')


if __name__ == "__main__":
    unittest.main()
