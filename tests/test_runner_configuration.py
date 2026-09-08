import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wrapper import runner
from wrapper.demand_runner import DemandRunConfig
from wrapper.docker_image import source_fingerprint


class RunnerConfigurationTests(unittest.TestCase):
    def test_network_container_uses_writable_gdal_temp_directory(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            data = root / "data"
            output = root / "output"
            with patch.object(runner, "DATA_DIR", data), \
                    patch.object(runner, "OUTPUT_DIR", output), \
                    patch.object(runner, "image_exists", return_value=True), \
                    patch.object(runner.subprocess, "run") as run:
                runner.run(runner.NetworkRunConfig("test", "region.geojson"))

        command = run.call_args.args[0]
        self.assertIn("CPL_TMPDIR=/app/output", command)

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


if __name__ == "__main__":
    unittest.main()
