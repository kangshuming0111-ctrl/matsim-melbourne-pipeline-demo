import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wrapper import pipeline


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


if __name__ == "__main__":
    unittest.main()
