import tempfile
import unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import patch

from wrapper import preflight


class PreflightTests(unittest.TestCase):
    GB = 1024 ** 3

    def test_ready_when_required_data_and_runtime_are_available(self):
        usage = namedtuple("usage", "total used free")
        with tempfile.TemporaryDirectory() as raw_dir:
            data_dir = Path(raw_dir)
            for relative in preflight.DEMAND_DATA_FILES:
                path = data_dir / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            (data_dir / "sample.geojson").touch()
            (data_dir / "geofabrik_victoria-latest.osm.pbf").touch()
            (data_dir / "dem").mkdir()
            (data_dir / "dem" / "fabdem_melbourne.tif").touch()
            (data_dir / "landmarks").mkdir()
            for key in preflight.PRESET_LANDMARK_KEYS:
                (data_dir / "landmarks" / f"{key}.json").touch()

            docker = ({
                "key": "docker", "label": "Docker", "status": "ready", "detail": "ready"
            }, {"memory_gb": 32})
            with patch.object(preflight, "DATA_DIR", data_dir), \
                    patch.object(preflight, "_docker_check", return_value=docker), \
                    patch.object(preflight.shutil, "disk_usage", return_value=usage(100 * self.GB, 10 * self.GB, 90 * self.GB)):
                result = preflight.check_system()

        self.assertTrue(result["can_run_pipeline"])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["missing_data"], [])

    def test_missing_demand_data_blocks_pipeline(self):
        usage = namedtuple("usage", "total used free")
        with tempfile.TemporaryDirectory() as raw_dir:
            docker = ({
                "key": "docker", "label": "Docker", "status": "ready", "detail": "ready"
            }, {"memory_gb": 32})
            with patch.object(preflight, "DATA_DIR", Path(raw_dir)), \
                    patch.object(preflight, "_docker_check", return_value=docker), \
                    patch.object(preflight.shutil, "disk_usage", return_value=usage(100 * self.GB, 10 * self.GB, 90 * self.GB)):
                result = preflight.check_system()

        self.assertFalse(result["can_run_pipeline"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(len(result["missing_data"]), len(preflight.DEMAND_DATA_FILES))


if __name__ == "__main__":
    unittest.main()
