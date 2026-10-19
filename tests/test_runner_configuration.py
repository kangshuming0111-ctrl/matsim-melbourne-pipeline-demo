import tempfile
import json
import subprocess
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from wrapper import baseline_runner, demand_runner, runner, scenario
from wrapper.demand_runner import DemandRunConfig
from wrapper.docker_image import source_fingerprint


class RunnerConfigurationTests(unittest.TestCase):
    def test_all_docker_stages_use_explicit_logs_outside_generated_directories(self):
        with tempfile.TemporaryDirectory() as raw_dir, ExitStack() as stack:
            root = Path(raw_dir)
            output = root / "output"
            data = root / "data"
            data.mkdir()
            (data / "region.geojson").write_text('{}')
            stack.enter_context(patch.object(runner.subprocess, 'run', return_value=
                subprocess.CompletedProcess([], 0, 'sha256:fixture\n', '')))
            modules = (runner, demand_runner, baseline_runner)
            calls = {}
            for module in modules:
                stack.enter_context(patch.object(module, "OUTPUT_DIR", output))
                stack.enter_context(patch.object(module, "image_exists", return_value=False))
                stack.enter_context(patch.object(module, "image_fingerprint", return_value="test"))
                calls[module] = stack.enter_context(patch.object(module, "run_logged"))
            def network_outputs(command, **kwargs):
                if command[1] == 'run':
                    target = output/'test_network'
                    self.assertFalse(target.exists(), 'Producer-owned output must not be pre-created')
                    target.mkdir()
                    (target/'network.xml').write_text('<network/>')
                    (target/'network.sqlite').write_bytes(b'fixture')
            calls[runner].side_effect = network_outputs
            for module in (runner, demand_runner, scenario):
                stack.enter_context(patch.object(module, "DATA_DIR", data))
            stack.enter_context(patch.object(scenario, "OUTPUT_DIR", output))
            stack.enter_context(patch.object(scenario, "demand_image_exists", return_value=False))
            derive = stack.enter_context(patch.object(scenario, "run_logged"))

            runner.run(runner.NetworkRunConfig("test", "region.geojson", "test_network"))
            demand_runner.run(DemandRunConfig(0.1, 500, "test_demand"))
            baseline_runner.run("test_network", "test_demand", "test_sim")
            for module, name in zip(modules, ("test_network", "test_demand", "test_sim")):
                invocations = calls[module].call_args_list
                self.assertEqual(len(invocations), 2, "build + run must both use durable logs")
                for call in invocations:
                    self.assertEqual(call.kwargs["log_path"], output / "process_logs" / (name + ".log"))
                if module is not runner:
                    self.assertFalse((output / name).exists(), "Do not pre-create producer-owned output directory")

            scenario.derive_sa1_subset("region.geojson", 500, "test_sa1_subset.csv")
            expected = output / "process_logs/test_sa1_subset.csv.log"
            self.assertEqual(derive.call_args.kwargs["log_path"], expected)
            self.assertEqual(calls[demand_runner].call_args.kwargs["log_path"], expected)
            config = (output / "test_sim_config/config.xml").read_text()
            self.assertIn('name="randomSeed" value="4711"', config)
            self.assertIn('name="lastIteration" value="2"', config)

    def test_network_container_uses_writable_gdal_temp_directory(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            data = root / "data"
            output = root / "output"
            data.mkdir()
            (data / "region.geojson").write_text('{}')
            with patch.object(runner, "DATA_DIR", data), \
                    patch.object(runner, "OUTPUT_DIR", output), \
                    patch.object(runner, "image_exists", return_value=True), \
                    patch.object(runner.subprocess, 'run', return_value=
                        subprocess.CompletedProcess([], 0, 'sha256:fixture\n', '')), \
                    patch.object(runner, "run_logged") as run:
                def generated(command, **kwargs):
                    target = output/'generated_network'
                    target.mkdir()
                    (target/'network.xml').write_text('<network/>')
                    (target/'network.sqlite').write_bytes(b'fixture')
                run.side_effect = generated
                runner.run(runner.NetworkRunConfig("test", "region.geojson"))

        command = run.call_args.args[0]
        self.assertIn("CPL_TMPDIR=/app/output/network_work/generated_network/scratch", command)
        self.assertEqual(run.call_args.kwargs["log_path"], output / "process_logs/generated_network.log")

    def test_network_config_can_pin_exact_osm_extract(self):
        config = runner.NetworkRunConfig(
            "cbd", "sample_region.geojson", osm_pbf_file="geofabrik_victoria-latest.osm.pbf"
        )
        self.assertEqual(
            config.to_env()["NETWORK_OSM_PBF"],
            "./data/geofabrik_victoria-latest.osm.pbf",
        )

    def test_demand_seed_is_passed_to_container_environment(self):
        config = DemandRunConfig(sample_percent=5, num_plans=500, random_seed=4711)
        self.assertEqual(config.to_env()["DEMAND_RANDOM_SEED"], "4711")

    def test_docker_source_fingerprint_changes_with_source(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            source = Path(raw_dir) / "entrypoint.R"
            source.write_text("value <- 1\n")
            before = source_fingerprint([source])
            source.write_text("value <- 2\n")
            after = source_fingerprint([source])

        self.assertNotEqual(before, after)

    def test_network_scratch_pbf_copy_and_commands_are_isolated(self):
        with tempfile.TemporaryDirectory() as raw_dir, ExitStack() as stack:
            root = Path(raw_dir)
            data, output = root/'data', root/'output'
            data.mkdir()
            output.mkdir()
            (data/'region.geojson').write_text('{}')
            (data/'cache.osm.pbf').write_bytes(b'original-pbf')
            (data/'cache.gpkg').write_bytes(b'preserve-existing-intermediate')
            (output/'osm_extract.gpkg').write_bytes(b'preserve-old-shared-extract')
            (output/'network_unconfigured.sqlite').write_bytes(b'preserve-old-shared-sqlite')
            before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
            stack.enter_context(patch.object(runner, 'DATA_DIR', data))
            stack.enter_context(patch.object(runner, 'OUTPUT_DIR', output))
            stack.enter_context(patch.object(runner, 'image_exists', return_value=True))
            stack.enter_context(patch.object(runner, 'image_fingerprint', return_value='fixture'))
            stack.enter_context(patch.object(runner.subprocess, 'run', return_value=
                subprocess.CompletedProcess([], 0, 'sha256:fixture\n', '')))
            run = stack.enter_context(patch.object(runner, 'run_logged'))
            def generated(command, **kwargs):
                name = next(v.split('=', 1)[1] for v in command if v.startswith('NETWORK_OUTPUT_SUBDIR='))
                target = output/name
                target.mkdir()
                (target/'network.xml').write_text('<network/>')
                (target/'network.sqlite').write_bytes(b'fixture')
            run.side_effect = generated
            for name in ('first_network', 'second_network'):
                runner.run(runner.NetworkRunConfig('city', 'region.geojson', name,
                    osm_pbf_file='cache.osm.pbf', cached_only=True))
                cmd = run.call_args.args[0]
                prefix = f'/app/output/network_work/{name}/scratch'
                self.assertIn(f'NETWORK_OSM_GPKG={prefix}/osm_extract.gpkg', cmd)
                self.assertIn(f'NETWORK_UNCONFIGURED_SQLITE={prefix}/network_unconfigured.sqlite', cmd)
                self.assertIn(f'NETWORK_OSM_PBF={prefix}/cache.osm.pbf', cmd)
                self.assertIn(f'{data}:/source/data:ro', cmd)
                self.assertEqual(cmd[cmd.index('--network')+1], 'none')
                self.assertEqual(cmd[cmd.index('--pull')+1], 'never')
                self.assertIn('--vanilla', cmd)
                self.assertIn('sha256:fixture', cmd)
                self.assertNotIn('--platform', cmd)
                manifest = json.loads((output/'network_work'/name/'runner_manifest.json').read_text())
                self.assertEqual(manifest['status'], 'completed')
                self.assertTrue(all(manifest['inputs_unchanged'].values()))
                for filename, evidence in manifest['artifacts'].items():
                    self.assertEqual(evidence['sha256'], runner.sha256_file(output/name/filename))
            for p, content in before.items():
                self.assertEqual(p.read_bytes(), content)
            with self.assertRaises(FileExistsError):
                runner.run(runner.NetworkRunConfig('city', 'region.geojson', 'first_network'))
            self.assertEqual(run.call_count, 2)

    def test_cached_only_stale_image_fails_without_build(self):
        with tempfile.TemporaryDirectory() as raw_dir, ExitStack() as stack:
            root = Path(raw_dir)
            data, output = root/'data', root/'output'
            data.mkdir()
            (data/'region.geojson').write_text('{}')
            (data/'cache.pbf').write_bytes(b'pbf')
            stack.enter_context(patch.object(runner, 'DATA_DIR', data))
            stack.enter_context(patch.object(runner, 'OUTPUT_DIR', output))
            stack.enter_context(patch.object(runner, 'image_exists', return_value=False))
            build = stack.enter_context(patch.object(runner, 'build_image'))
            run = stack.enter_context(patch.object(runner, 'run_logged'))
            with self.assertRaisesRegex(RuntimeError, 'no automatic build'):
                runner.run(runner.NetworkRunConfig('city', 'region.geojson', 'failed_network',
                    osm_pbf_file='cache.pbf', cached_only=True))
            build.assert_not_called()
            run.assert_not_called()
            m = json.loads((output/'network_work/failed_network/runner_manifest.json').read_text())
            self.assertEqual(m['status'], 'failed')

    def test_zero_exit_without_required_nonempty_artifacts_is_failure(self):
        for failure in ('missing_both', 'missing_sqlite', 'empty_xml', 'empty_sqlite'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as raw_dir, ExitStack() as stack:
                root = Path(raw_dir)
                data, output = root/'data', root/'output'
                data.mkdir()
                (data/'region.geojson').write_text('{}')
                stack.enter_context(patch.object(runner, 'DATA_DIR', data))
                stack.enter_context(patch.object(runner, 'OUTPUT_DIR', output))
                stack.enter_context(patch.object(runner, 'image_exists', return_value=True))
                stack.enter_context(patch.object(runner.subprocess, 'run', return_value=
                    subprocess.CompletedProcess([], 0, 'sha256:fixture\n', '')))
                def partial(command, **kwargs):
                    if failure == 'missing_both':
                        return
                    target = output/'bad_network'
                    target.mkdir()
                    (target/'network.xml').write_text('' if failure == 'empty_xml' else '<network/>')
                    if failure != 'missing_sqlite':
                        (target/'network.sqlite').write_bytes(b'' if failure == 'empty_sqlite' else b'fixture')
                stack.enter_context(patch.object(runner, 'run_logged', side_effect=partial))
                with self.assertRaisesRegex(RuntimeError, 'nonempty network.xml and network.sqlite'):
                    runner.run(runner.NetworkRunConfig('city', 'region.geojson', 'bad_network'))
                m = json.loads((output/'network_work/bad_network/runner_manifest.json').read_text())
                self.assertEqual(m['status'], 'failed')
                self.assertEqual(set(m['artifacts']), {'network.xml', 'network.sqlite'})


if __name__ == "__main__":
    unittest.main()
