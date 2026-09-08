import csv
import gzip
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wrapper import analyze, runs


def _write_gzip_csv(path: Path, fieldnames: list[str], rows: list[dict]):
    with gzip.open(path, "wt", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


class RunCatalogueTests(unittest.TestCase):
    def test_lists_and_loads_completed_run(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            sim = output / "demo_1700000000_sim"
            sim.mkdir()
            (sim / "output_config.xml").write_text("<config/>")
            (sim / "skyline_scene.json").write_text("{}")
            _write_gzip_csv(sim / "output_persons.csv.gz", ["person"], [{"person": "1"}])
            _write_gzip_csv(
                sim / "output_trips.csv.gz",
                ["modes", "trav_time", "traveled_distance"],
                [{"modes": "car", "trav_time": "00:10:00", "traveled_distance": "5000"}],
            )
            (sim / "scorestats.txt").write_text(
                "ITERATION\tavg. EXECUTED\n0\t-10.0\n1\t-9.5\n"
            )
            record_dir = output / "run_records" / "demo_1700000000"
            record_dir.mkdir(parents=True)
            (record_dir / "run_manifest.json").write_text(
                '{"status":"completed","run_id":"demo_1700000000",'
                '"profile":{"id":"cbd_small_v1","validation_status":"verified_demo"}}'
            )

            with patch.object(runs, "OUTPUT_DIR", output), patch.object(analyze, "OUTPUT_DIR", output):
                catalogue = runs.list_runs()
                payload = runs.result_payload(sim.name)

        self.assertEqual(len(catalogue), 1)
        self.assertEqual(catalogue[0]["status"], "completed")
        self.assertTrue(catalogue[0]["has_3d_scene"])
        self.assertEqual(payload["person_count"], 1)
        self.assertEqual(payload["total_trips"], 1)
        self.assertEqual(payload["mode_rows"][0]["mode"], "car")
        self.assertEqual(payload["run_id"], "demo_1700000000")
        self.assertEqual(payload["sim_output_subdir"], "demo_1700000000_sim")

    def test_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            runs.validate_run_name("../secret")

    def test_failed_record_prevents_partial_run_being_listed_as_completed(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            output = Path(raw_dir)
            sim = output / "cbd_demo_1_sim"
            sim.mkdir()
            for name in runs.REQUIRED_RESULT_FILES:
                (sim / name).write_text("present")
            record_dir = output / "run_records" / "cbd_demo_1"
            record_dir.mkdir(parents=True)
            (record_dir / "run_manifest.json").write_text(
                '{"status":"failed","run_id":"cbd_demo_1"}'
            )

            with patch.object(runs, "OUTPUT_DIR", output):
                catalogue = runs.list_runs()
                with self.assertRaises(FileNotFoundError):
                    runs.result_payload(sim.name)

        self.assertEqual(catalogue[0]["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
