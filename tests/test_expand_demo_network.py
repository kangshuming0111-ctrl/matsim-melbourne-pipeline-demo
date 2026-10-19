import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import expand_demo_network as expansion


OLD = '''<network><nodes><node id="a" x="0" y="0"/>
<node id="b" x="10" y="0"/><node id="c" x="0" y="10"/></nodes>
<links><link id="ab" from="a" to="b" modes="car,walk"/>
<link id="ba" from="b" to="a" modes="car,walk"/></links></network>'''
NEW = OLD.replace('id="a"', 'id="x"').replace('id="b"', 'id="y"').replace('id="c"', 'id="z"')
NEW = NEW.replace('from="a"', 'from="x"').replace('to="a"', 'to="x"')
NEW = NEW.replace('from="b"', 'from="y"').replace('to="b"', 'to="y"')
NEW = NEW.replace('id="ab"', 'id="xy"').replace('id="ba"', 'id="yx"')
PLANS = '''<population><person id="private"><plan selected="yes">
<activity type="Home" x="1" y="0"/><leg mode="car"/>
<activity type="Work" x="2" y="1"/></plan></person></population>'''


class ExpandDemoNetworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        paths = {
            f"output/{expansion.BASELINE}_network/network.xml": OLD,
            f"output/{expansion.BASELINE}_demand/8.xml/plan.xml": PLANS,
            f"output/run_records/{expansion.BASELINE}/run_manifest.json": json.dumps({"configuration": {"output_crs": 7899}}),
            "data/geofabrik_victoria-latest.osm.pbf": "cached original PBF",
            "wrapper/coverage_audit.py": "audit-source",
        }
        for name, text in paths.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        for key, value in (("PLANS_SHA256", hashlib.sha256(PLANS.encode()).hexdigest()),
                           ("NETWORK_SHA256", hashlib.sha256(OLD.encode()).hexdigest()),
                           ("EXPECTED_PERSONS", 1), ("EXPECTED_ACTIVITIES", 2)):
            patcher = patch.object(expansion, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.environment = patch.object(expansion, "_cached_environment", return_value={
            "image_id": "sha256:pinned", "source_fingerprint": "fingerprint",
            "image_platform": "linux/arm64"})
        self.env_mock = self.environment.start()
        self.addCleanup(self.environment.stop)

    def generate(self, command, *, log_path, cwd):
        directory = log_path.parent
        (directory / "expanded_network").mkdir()
        (directory / "expanded_network/network.xml").write_text(NEW)
        (directory / "expanded_network/network.sqlite").write_bytes(b"fixture")
        (directory / "activity_bbox.gpkg").write_bytes(b"fixture")
        (directory / "domain_summary.json").write_text('{"crs":7899,"buffer_m":500}')
        (directory / "r_environment.json").write_text('{"R":"fixture"}')
        log_path.write_text("fixture generator completed")

    def test_run_preserves_inputs_has_provenance_audits_and_immutable_image(self):
        initial = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with patch.object(expansion, "run_logged", side_effect=self.generate) as run:
            directory = expansion.expand_network(root=self.root, experiment_id="test_domain")
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "completed")
        self.assertIsNotNone(manifest["started_at"])
        self.assertIsNotNone(manifest["finished_at"])
        self.assertIsNotNone(manifest["network_generation_finished_at"])
        self.assertFalse(manifest["simulation_started"])
        self.assertTrue(all(manifest["input_hashes_unchanged"].values()))
        for name, original in initial.items():
            self.assertEqual(Path(name).read_bytes(), original)
        for name in ("coverage_before.json", "coverage_after.json", "network_id_mapping.json"):
            self.assertIn(name, manifest["artifacts"])
        self.assertEqual(manifest["artifacts"]["expanded_network/network.xml"]["sha256"],
                         hashlib.sha256(NEW.encode()).hexdigest())
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--network") + 1], "none")
        self.assertEqual(command[command.index("--pull") + 1], "never")
        self.assertNotIn("--platform", command)
        self.assertEqual(command[command.index("--entrypoint") + 2], "sha256:pinned")
        self.assertIn("--vanilla", command)
        self.assertIn(f"{self.root / 'data'}:/app/data:ro", command)
        writable_mounts = [v for v in command if ":/app/output" in v]
        self.assertEqual(writable_mounts, [f"{directory}:/app/output"])
        self.assertNotIn("build", command)
        self.assertNotIn("private", (directory / "coverage_after.json").read_text())

    def test_existing_experiment_and_invalid_name_are_refused_without_generator(self):
        directory = self.root / "output/domain_experiments/kept"
        directory.mkdir(parents=True)
        (directory / "keep").write_text("preserve")
        with patch.object(expansion, "run_logged") as run:
            with self.assertRaises(FileExistsError):
                expansion.expand_network(root=self.root, experiment_id="kept")
            for name in ("../outside", "", "a/b", "9bad"):
                if not name:
                    continue
                with self.subTest(name=name), self.assertRaises(ValueError):
                    expansion.expand_network(root=self.root, experiment_id=name)
            run.assert_not_called()
        self.assertEqual((directory / "keep").read_text(), "preserve")

    def test_changed_plans_fail_before_docker_with_durable_manifest(self):
        plans = self.root / f"output/{expansion.BASELINE}_demand/8.xml/plan.xml"
        plans.write_text(PLANS.replace('x="1"', 'x="9"'))
        with patch.object(expansion, "run_logged") as run:
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                expansion.expand_network(root=self.root, experiment_id="changed")
            run.assert_not_called()
        self.env_mock.assert_not_called()
        m = json.loads((self.root / "output/domain_experiments/changed/manifest.json").read_text())
        self.assertEqual(m["status"], "failed")
        self.assertEqual(m["stage"], "preflight")

    def test_failed_generator_preserves_error_log_hashes_and_stops_only_owned_container(self):
        def failed(command, *, log_path, cwd):
            log_path.write_text("out of memory fixture")
            raise subprocess.CalledProcessError(137, command)
        with patch.object(expansion, "run_logged", side_effect=failed), \
                patch.object(expansion.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)) as stop:
            with self.assertRaises(subprocess.CalledProcessError):
                expansion.expand_network(root=self.root, experiment_id="failed")
        directory = self.root / "output/domain_experiments/failed"
        m = json.loads((directory / "manifest.json").read_text())
        self.assertEqual(m["status"], "failed")
        self.assertEqual(m["generator_returncode"], 137)
        self.assertEqual(m["stage"], "network_generation")
        self.assertIsNotNone(m["network_generation_finished_at"])
        self.assertTrue(all(m["input_hashes_unchanged"].values()))
        self.assertEqual((directory / "console.log").read_text(), "out of memory fixture")
        self.assertEqual(stop.call_args.args[0], ["docker", "stop", "--time", "10", "domain-failed"])

    def test_zero_exit_without_artifacts_is_not_completed(self):
        with patch.object(expansion, "run_logged"), \
                patch.object(expansion.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(ValueError, "nonempty network.xml"):
                expansion.expand_network(root=self.root, experiment_id="empty_result")
        m = json.loads((self.root / "output/domain_experiments/empty_result/manifest.json").read_text())
        self.assertEqual(m["status"], "failed")
        self.assertEqual(m["generator_returncode"], 0)

    def test_stale_image_fails_without_build_or_generation(self):
        self.env_mock.side_effect = ValueError("Cached R image does not match source")
        with patch.object(expansion, "run_logged") as run:
            with self.assertRaisesRegex(ValueError, "does not match"):
                expansion.expand_network(root=self.root, experiment_id="stale")
            run.assert_not_called()

    def test_image_inspection_records_actual_identity_platform_and_checks_source(self):
        inspected = [{"Id": "sha256:exact", "Os": "linux", "Architecture": "amd64",
                      "Config": {"Labels": {expansion.FINGERPRINT_LABEL: "current"}}}]
        # Exercise the environment adapter rather than the lifecycle fixture stub.
        self.environment.stop()
        with patch.object(expansion, "_capture_json", side_effect=[inspected, {"NCPU": 14}]) as capture, \
                patch.object(expansion, "source_fingerprint", return_value="current"):
            result = expansion._cached_environment(self.root)
        self.assertEqual(result["image_id"], "sha256:exact")
        self.assertEqual(result["image_platform"], "linux/amd64")
        self.assertEqual(capture.call_args_list[0].args[0], ["docker", "image", "inspect", expansion.IMAGE])
        with patch.object(expansion, "_capture_json", return_value=inspected) as capture, \
                patch.object(expansion, "source_fingerprint", return_value="changed"):
            with self.assertRaisesRegex(ValueError, "no automatic rebuild"):
                expansion._cached_environment(self.root)
            self.assertEqual(capture.call_count, 1)

    def test_wrong_crs_is_rejected_before_generator(self):
        record = self.root / f"output/run_records/{expansion.BASELINE}/run_manifest.json"
        record.write_text('{"configuration":{"output_crs":4326}}')
        with patch.object(expansion, "run_logged") as run:
            with self.assertRaisesRegex(ValueError, "EPSG:7899"):
                expansion.expand_network(root=self.root, experiment_id="wrong_crs")
            run.assert_not_called()

    def test_interruption_is_recorded_even_if_container_stop_fails(self):
        with patch.object(expansion, "run_logged", side_effect=KeyboardInterrupt), \
                patch.object(expansion.subprocess, "run", side_effect=OSError("Docker unavailable")):
            with self.assertRaises(KeyboardInterrupt):
                expansion.expand_network(root=self.root, experiment_id="interrupted")
        m = json.loads((self.root / "output/domain_experiments/interrupted/manifest.json").read_text())
        self.assertEqual(m["status"], "interrupted")
        self.assertEqual(m["container_stop_error"], "OSError")
        self.assertTrue(all(m["input_hashes_unchanged"].values()))
        self.assertIsNotNone(m["finished_at"])

    def test_output_audit_does_not_gate_generation_status_on_coverage_threshold(self):
        def outside(command, *, log_path, cwd):
            self.generate(command, log_path=log_path, cwd=cwd)
            path = log_path.parent / "expanded_network/network.xml"
            path.write_text(NEW.replace('x="0"', 'x="100"').replace('x="10"', 'x="110"'))
        with patch.object(expansion, "run_logged", side_effect=outside):
            directory = expansion.expand_network(root=self.root, experiment_id="low_overlap")
        m = json.loads((directory / "manifest.json").read_text())
        self.assertEqual(m["status"], "completed")
        self.assertEqual(m["audit_summary"]["after"]["inside_node_bbox_fraction_of_finite"], 0)
        self.assertFalse(m["simulation_started"])

    def test_id_mapping_tracks_geometry_not_old_numbers_and_preserves_direction(self):
        old, new = self.root / "old.xml", self.root / "new.xml"
        old.write_text(OLD)
        new.write_text(NEW.replace('<link id="yx" from="y" to="x" modes="car,walk"/>', ''))
        mapping = expansion.map_network_ids(old, new)
        self.assertEqual(mapping["nodes"]["a"]["new_node_id"], "x")
        self.assertEqual(mapping["links"]["ab"]["new_link_id"], "xy")
        self.assertIsNone(mapping["links"]["ba"]["new_link_id"])
        self.assertNotIn('"coordinates"', json.dumps(mapping))

    def test_mapping_ambiguous_or_far_nodes_are_not_silently_chosen(self):
        old, new = self.root / "old.xml", self.root / "new.xml"
        old.write_text(OLD)
        new.write_text(NEW.replace('</nodes>', '<node id="duplicate" x="0" y="0"/></nodes>')
                       .replace('id="z" x="0" y="10"', 'id="z" x="0" y="20"'))
        mapping = expansion.map_network_ids(old, new)
        self.assertIsNone(mapping["nodes"]["a"]["new_node_id"])
        self.assertIsNone(mapping["nodes"]["c"]["new_node_id"])
        self.assertIsNone(mapping["links"]["ab"]["new_link_id"])


if __name__ == "__main__":
    unittest.main()
