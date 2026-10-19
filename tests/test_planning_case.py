"""Deterministic case orchestration tests. All simulation artifacts are fixtures."""
import copy
import gzip
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree as ET

from scripts import run_planning_case as case
from wrapper import analyze, ifline, planning, provenance, runs


NETWORK = '''<network><nodes>
<node id="8844" x="2496581" y="2408829"/>
<node id="8954" x="2496544" y="2408715"/>
<node id="8695" x="2496731" y="2408809"/>
<node id="9032" x="2496648" y="2408628"/>
<node id="9019" x="2496778" y="2408758"/>
</nodes><links>
<link id="890" from="8844" to="8954" length="120.498" freespeed="14" capacity="1800" permlanes="4" modes="car,bike,walk"/>
<link id="2071" from="8954" to="8844" length="120.498" freespeed="14" capacity="1800" permlanes="4" modes="car,bike,walk"/>
<link id="1069" from="8695" to="9019" length="72" freespeed="13" capacity="600" permlanes="1" modes="car,bike,walk"/>
<link id="1167" from="9019" to="9032" length="185" freespeed="12" capacity="379" permlanes="1" modes="car,bike,walk"/>
</links></network>'''

SCENE = {"coordinate_transform": {"network_crs": "EPSG:7899", "scene_units_per_metre": 1, "center_x": 0, "center_y": 0},
         "roads": [], "landmarks": {"buildings": [{"osm_id": "fixture/building",
             "points": [[2496680, 2408710], [2496710, 2408710],
                        [2496710, 2408740], [2496680, 2408740]], "height": 8}]}}


class PlanningCaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for module in (case, ifline, analyze, provenance, runs):
            for attribute, value in (("ROOT", self.root), ("PROJECT_ROOT", self.root),
                                     ("OUTPUT", self.output), ("OUTPUT_DIR", self.output)):
                if hasattr(module, attribute):
                    self.stack.enter_context(patch.object(module, attribute, value))
        self.stack.enter_context(patch.object(ifline, "IFLINE_DIR", self.output / "ifline"))
        self.stack.enter_context(patch.object(provenance, "code_snapshot", return_value={"test_fixture": True}))
        self.stack.enter_context(patch.object(provenance, "environment_snapshot", return_value={"test_fixture": True}))
        # Use real compiler, recorder, summary, IF Line and difference-scene paths.
        # Only external simulation/terrain rendering and optional analysis are replaced.
        self.calls = []
        self.simulator = self.stack.enter_context(patch.object(case, "run_simulation", side_effect=self.simulate))
        self.stack.enter_context(patch.object(ifline, "run_simulation", side_effect=self.simulate))
        self.stack.enter_context(patch.object(case, "render_skyline_scene", side_effect=self.scene))
        self.stack.enter_context(patch.object(ifline, "render_skyline_scene", side_effect=self.scene))
        self.stack.enter_context(patch.object(case, "_optional_impact", return_value={"available": False, "reason": "test fixture"}))
        self.building_cache = self.root / "data" / "landmarks" / "v2" / "cbd.json"
        self.stack.enter_context(patch.object(case, "landmark_cache_path", return_value=self.building_cache))
        # Production check_plan now requires an uncapped source. Keep these
        # orchestration fixtures real at that seam, not a display-layer bypass.
        self.stack.enter_context(patch("wrapper.building_screen.landmark_cache_path", return_value=self.building_cache))
        self.full_building_source()
        self.base = "source"
        network = self.output / f"{self.base}_network"
        demand = self.output / f"{self.base}_demand" / "8.xml"
        sim = self.output / f"{self.base}_sim"
        record = self.output / "run_records" / self.base
        for path in (network, demand, sim, record):
            path.mkdir(parents=True)
        (network / "network.xml").write_text(NETWORK)
        (demand / "plan.xml").write_text('<population><person id="fixture-person"><plan>'
                                       '<activity type="home" x="2496600" y="2408750"/>'
                                       '</plan></person></population>')
        self.scene(sim.name)
        (record / "run_manifest.json").write_text(json.dumps({
            "status": "completed", "run_id": self.base, "verification": {"passed": True},
            "configuration": {"region_key": "cbd", "output_crs": 7899, "matsim_last_iteration": 2},
            "random_seeds": {"demand": 4711, "matsim": 4711},
            "outputs": {"network": f"output/{self.base}_network", "demand": f"output/{self.base}_demand"}}))

    def scene(self, name, **kwargs):
        path = self.output / name / "skyline_scene.json"
        path.write_text(json.dumps(SCENE))
        return path

    def simulate(self, *, network_output_subdir, demand_output_subdir, output_subdir,
                 last_iteration, random_seed):
        self.calls.append({"network": network_output_subdir, "demand": demand_output_subdir,
                           "output": output_subdir, "last_iteration": last_iteration, "seed": random_seed})
        sim = self.output / output_subdir
        sim.mkdir(exist_ok=False)
        config_dir = self.output / f"{output_subdir}_config"
        config_dir.mkdir(exist_ok=False)
        config = case.CONFIG_TEMPLATE.format(
            network_file=f"/app/output/{network_output_subdir}/network.xml",
            plans_file=f"/app/output/{demand_output_subdir}/8.xml/plan.xml",
            output_dir=f"/app/output/{output_subdir}", last_iteration=last_iteration, random_seed=random_seed)
        (config_dir / "config.xml").write_text(config)
        (sim / "output_config.xml").write_text(config)
        with gzip.open(sim / "output_network.xml.gz", "wb") as stream:
            stream.write((self.output / network_output_subdir / "network.xml").read_bytes())
        fixtures = {"output_events.xml.gz": '<events/>',
                    "output_persons.csv.gz": 'person\nfixture-person\n',
                    "output_trips.csv.gz": 'person;trip_number;dep_time;trav_time;modes;main_mode;traveled_distance\n'
                                           'fixture-person;1;08:00:00;00:10:00;car;car;1000\n'}
        for name, content in fixtures.items():
            with gzip.open(sim / name, "wt") as stream:
                stream.write(content)
        (sim / "scorestats.txt").write_text('ITERATION\tavg. EXECUTED\n' + ''.join(
            f'{iteration}\t-10\n' for iteration in range(last_iteration + 1)))
        (sim / "logfile.log").write_text('Shutdown completed\n')
        return sim

    def prepare(self, **kwargs):
        return case.prepare_case(source_run="source_sim", case_id="test_case", **kwargs)

    def expanded_network(self):
        directory = self.output / "expanded_network"
        directory.mkdir()
        root = ET.fromstring(NETWORK)
        for node in root.findall("nodes/node"):
            node.set("id", "expanded_" + node.get("id"))
            node.set("x", str(float(node.get("x")) + 0.5))
        for link in root.findall("links/link"):
            link.set("id", "expanded_" + link.get("id"))
            link.set("from", "expanded_" + link.get("from"))
            link.set("to", "expanded_" + link.get("to"))
        ET.ElementTree(root).write(directory / "network.xml")
        (directory / "makeMatsimNetwork.log").write_text("Finished generating the xml output\n")
        return directory

    def test_expanded_network_bootstrap_reuses_original_plans_then_prepare_launches_nothing(self):
        expanded = self.expanded_network()
        original_plans = case.sha256_file(self.output / "source_demand" / "8.xml" / "plan.xml")
        run_name = case.bootstrap_baseline(network_dir=expanded, source_run="source_sim", bootstrap_id="bootstrap_test")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["demand"], "source_demand")
        self.assertEqual(self.calls[0]["network"], "bootstrap_test_inputs_network")
        self.assertEqual((self.calls[0]["seed"], self.calls[0]["last_iteration"]), (4711, 9))
        resolved = ifline.resolve_run_assets(run_name)
        self.assertEqual(resolved["network_dir"], (self.output / "bootstrap_test_inputs_network").resolve())
        self.assertEqual(case.sha256_file(resolved["plans_file"]), original_plans)
        directory = case.prepare_case(source_run=run_name, network_dir=expanded, case_id="expanded_case")
        spec = case._read(directory / "case_spec.json")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(spec["seeds"], case.DEFAULT_SEEDS)
        self.assertEqual(spec["scope"], "expanded_network_fixed_population")
        self.assertEqual(spec["geometry"]["resolved_node_ids"]["8695"], "expanded_8695")
        self.assertEqual(spec["geometry"]["node_displacement_m"]["8695"], 0.5)
        self.assertEqual(spec["plans"]["closure"]["operations"][0]["link_id"], "expanded_890")
        self.assertEqual(spec["inputs"]["plans_file"]["sha256"], original_plans)
        self.assertEqual(spec["conflict_count"]["alternative"], 1)
        with self.assertRaises(FileExistsError):
            case.bootstrap_baseline(network_dir=expanded, source_run="source_sim", bootstrap_id="bootstrap_test")
        self.assertEqual(len(self.calls), 1)

    def test_network_override_cannot_relabel_an_old_record_without_bootstrap(self):
        expanded = self.expanded_network()
        with self.assertRaisesRegex(ValueError, "first --bootstrap"):
            self.prepare(network_dir=expanded)
        self.assertEqual(self.calls, [])

    def test_nested_domain_manifest_must_be_completed_and_bind_the_fixed_inputs(self):
        expanded = self.expanded_network()
        domain = self.output / "domain_experiments" / "fixture_domain"
        domain.mkdir(parents=True)
        expanded = expanded.rename(domain / "expanded_network")
        manifest = domain / "manifest.json"
        manifest.write_text(json.dumps({"status": "running"}))
        with self.assertRaisesRegex(ValueError, "not completed"):
            case.bootstrap_baseline(network_dir=expanded, source_run="source_sim")
        manifest.write_text(json.dumps({"status": "completed", "artifacts": {}, "inputs": {}}))
        with self.assertRaisesRegex(ValueError, "does not match"):
            case.bootstrap_baseline(network_dir=expanded, source_run="source_sim")
        manifest.write_text(json.dumps({"status": "completed", "artifacts": {
            "expanded_network/network.xml": {"sha256": case.sha256_file(expanded / "network.xml")}},
            "inputs": {"plans": {"sha256": case.sha256_file(self.output / "source_demand" / "8.xml" / "plan.xml")}}}))
        name = case.bootstrap_baseline(network_dir=expanded, source_run="source_sim", bootstrap_id="nested_bootstrap")
        self.assertEqual(name, "nested_bootstrap_baseline_sim")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["network"], "nested_bootstrap_inputs_network")

    def test_bootstrap_waits_for_generation_completion_and_activity_coverage(self):
        expanded = self.expanded_network()
        log = expanded / "makeMatsimNetwork.log"
        log.write_text("still generating")
        with self.assertRaisesRegex(ValueError, "not recorded XML completion"):
            case.bootstrap_baseline(network_dir=expanded, source_run="source_sim")
        log.write_text("Finished generating the xml output")
        plans = self.output / "source_demand" / "8.xml" / "plan.xml"
        plans.write_text(plans.read_text().replace('x="2496600"', 'x="2490000"'))
        with self.assertRaisesRegex(ValueError, "outside=1"):
            case.bootstrap_baseline(network_dir=expanded, source_run="source_sim")
        self.assertEqual(self.calls, [])

    def test_original_corridor_coordinate_matching_fails_on_drift_and_ambiguity(self):
        expanded = self.expanded_network()
        path = expanded / "network.xml"
        root = ET.parse(path).getroot()
        original = ET.tostring(root)
        root.find("nodes/node[@id='expanded_8695']").set("x", "2496732.01")
        ET.ElementTree(root).write(path)
        with self.assertRaisesRegex(ValueError, "within 1 m; found 0"):
            case.bootstrap_baseline(network_dir=expanded, source_run="source_sim")
        root = ET.fromstring(original)
        ET.SubElement(root.find("nodes"), "node", id="duplicate", x="2496731", y="2408809")
        link = copy.deepcopy(root.find("links/link[@id='expanded_1069']"))
        link.set("id", "duplicate_link")
        link.set("from", "duplicate")
        root.find("links").append(link)
        ET.ElementTree(root).write(path)
        with self.assertRaisesRegex(ValueError, "within 1 m; found 2"):
            case.bootstrap_baseline(network_dir=expanded, source_run="source_sim")
        self.assertEqual(self.calls, [])

    def detour_fixture_extent(self):
        network = self.output / "source_network" / "network.xml"
        root = ET.parse(network).getroot()
        ET.SubElement(root.find("nodes"), "node", id="extent", x="2496900", y="2408500")
        ET.ElementTree(root).write(network)

    def test_detour_is_fixed_geometry_with_zero_known_conflicts_and_margin(self):
        self.detour_fixture_extent()
        directory = self.prepare(alternative_route="detour")
        spec = case._read(directory / "case_spec.json")
        self.assertEqual(spec["geometry"]["alternative_route"], "detour")
        self.assertAlmostEqual(spec["geometry"]["alternative_length_m"], 356.1585117494346)
        self.assertEqual(spec["conflict_count"], {"closure": 0, "alternative": 0})
        report = case._read(case._verify_file(spec["checks"]["alternative"]))
        self.assertEqual(report["detour_clearance"]["screened_width_m"], 13)
        self.assertEqual(report["detour_clearance"]["conflicts"], [])
        self.assertEqual(len(report["plan"]["operations"][1]["points"]), 14)
        self.assertEqual(self.calls, [])

    def test_detour_conflict_is_retained_but_not_acknowledgeable_as_prepared_case(self):
        self.detour_fixture_extent()
        scene_path = self.output / "source_sim" / "skyline_scene.json"
        scene = case._read(scene_path)
        scene["landmarks"]["buildings"] = [{"osm_id": "new-obstacle", "height": 5,
            "points": [[2496790, 2408710], [2496805, 2408710], [2496805, 2408730], [2496790, 2408730]]}]
        scene_path.write_text(json.dumps(scene))
        raw = self.full_building_source(scene["landmarks"]["buildings"][0]["points"])
        raw["buildings"][0]["osm_id"] = "new-obstacle"
        self.building_cache.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError, "Detour has known building conflicts"):
            self.prepare(alternative_route="detour")
        directory = self.output / "planning_cases" / "test_case"
        self.assertEqual(case._read(directory / "case_manifest.json")["status"], "prepare_failed")
        self.assertEqual(case._read(directory / "checks" / "alternative.json")["conflicts"][0]["key"], "new-obstacle")
        self.assertFalse((directory / "case_spec.json").exists())
        self.assertEqual(self.calls, [])

    def test_detour_rejects_long_parallel_duplicate_road_segments(self):
        self.detour_fixture_extent()
        path = self.output / "source_network" / "network.xml"
        root = ET.parse(path).getroot()
        for index, point in enumerate(case.DETOUR_POINTS[1:3]):
            ET.SubElement(root.find("nodes"), "node", id=f"parallel{index}", x=str(point[0]), y=str(point[1]))
        ET.SubElement(root.find("links"), "link", id="parallel_road", attrib={
            "from": "parallel0", "to": "parallel1", "length": "50", "freespeed": "10",
            "capacity": "900", "permlanes": "1", "modes": "car"})
        ET.ElementTree(root).write(path)
        with self.assertRaisesRegex(ValueError, "follows existing car link parallel_road"):
            self.prepare(alternative_route="detour")
        self.assertEqual(self.calls, [])

    def full_building_source(self, native_points=None):
        key = "fixture/building" if native_points is None else "full-source/building"
        native_points = native_points or SCENE["landmarks"]["buildings"][0]["points"]
        lons, lats = case.project_coordinates("EPSG:7899", "EPSG:4326", *zip(*native_points))
        raw = {"buildings": [{"osm_id": key, "coords": list(zip(lons, lats))}],
               "metadata": {"bounds": [144.945, 144.978, -37.832, -37.802]}}
        self.building_cache.parent.mkdir(parents=True, exist_ok=True)
        self.building_cache.write_text(json.dumps(raw))
        return raw

    def test_display_cap_requires_full_source_and_catches_an_omitted_obstacle(self):
        self.detour_fixture_extent()
        path = self.output / "source_sim" / "skyline_scene.json"
        scene = case._read(path)
        scene["landmark_diagnostics"] = {"buildings": {"omitted_by_limit": 1}}
        path.write_text(json.dumps(scene))
        self.building_cache.unlink()
        with self.assertRaisesRegex(ValueError, "完整建筑源不可用"):
            self.prepare(alternative_route="detour")
        self.full_building_source([[2496790, 2408710], [2496805, 2408710],
                                   [2496805, 2408730], [2496790, 2408730]])
        with self.assertRaisesRegex(ValueError, "Detour has known building conflicts"):
            self.prepare(alternative_route="detour")
        directory = self.output / "planning_cases" / "test_case"
        report = case._read(directory / "checks" / "alternative.json")
        # Production check_plan now catches the source obstacle itself, before
        # the study's additional 2 m margin screening.
        self.assertEqual(report["conflicts"][0]["key"], "full-source/building")
        full = report["detour_clearance"]["full_source_screen"]
        self.assertEqual(full["corridor_conflicts"][0]["key"], "full-source/building")
        self.assertEqual(case._read(directory / "case_manifest.json")["status"], "prepare_failed")
        self.assertFalse((directory / "case_spec.json").exists())
        self.assertEqual(self.calls, [])

    def test_full_source_checks_extent_validity_and_hash_before_simulation(self):
        self.detour_fixture_extent()
        raw = self.full_building_source()
        raw["metadata"]["bounds"] = [140, 141, -39, -38]
        self.building_cache.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError, "超出建筑源覆盖范围"):
            self.prepare(alternative_route="detour")
        raw = self.full_building_source()
        raw["buildings"].append({"coords": [[0, 0], [1, 1]]})
        self.building_cache.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError, "轮廓无效"):
            self.prepare(alternative_route="detour")
        raw = self.full_building_source()
        directory = self.prepare(alternative_route="detour")
        spec, _ = case._load_case(directory.resolve())
        report = case._read(case._verify_file(spec["checks"]["alternative"]))
        full = report["detour_clearance"]["full_source_screen"]
        self.assertEqual(full["source"]["sha256"], case.sha256_file(self.building_cache))
        self.assertTrue(full["corridor_and_margin_inside_cache_extent"])
        self.assertEqual(full["diagnostics"]["input"], 1)
        raw["metadata"]["changed"] = True
        self.building_cache.write_text(json.dumps(raw))
        with self.assertRaisesRegex(ValueError, "building evidence changed"):
            case.run_case(directory)
        self.assertEqual(self.calls, [])

    def test_detour_requires_full_source_before_preparation(self):
        self.detour_fixture_extent()
        self.building_cache.unlink()
        with self.assertRaisesRegex(ValueError, "完整建筑源不可用"):
            self.prepare(alternative_route="detour")
        self.assertFalse((self.output / "planning_cases" / "test_case").exists())
        self.assertEqual(self.calls, [])

    def test_full_source_detour_runs_the_fixed_triple_with_fixture_simulator(self):
        self.detour_fixture_extent()
        self.full_building_source()
        directory = self.prepare(alternative_route="detour", seeds=[4711])
        result = case.run_case(directory)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(self.calls), 3)

    def test_prepare_records_exact_geometry_conflicts_and_fixed_inputs_without_running(self):
        directory = self.prepare()
        spec = case._read(directory / "case_spec.json")
        self.assertEqual(self.calls, [])
        self.assertEqual(spec["seeds"], [4711, 4712, 4713])
        self.assertEqual(spec["total_iterations"], 10)
        self.assertEqual(spec["conflict_count"], {"closure": 0, "alternative": 1})
        self.assertEqual(spec["geometry"]["nodes"]["8695"], [2496731, 2408809])
        self.assertEqual(spec["plans"]["alternative"]["operations"][1]["snap_points"], [False, False])
        for key in ("network_file", "plans_file"):
            self.assertEqual(spec["inputs"][key]["sha256"], spec["source_evidence"][key]["sha256"])
        report = case._read(case._verify_file(spec["checks"]["alternative"]))
        self.assertEqual(report["conflicts"][0]["key"], "fixture/building")
        self.assertTrue(report["token"])

    def test_explicit_acknowledgement_is_required_before_any_simulation(self):
        directory = self.prepare()
        with self.assertRaisesRegex(ValueError, "acknowledge-conceptual-conflicts"):
            case.run_case(directory)
        self.assertEqual(self.calls, [])
        self.assertEqual(case._read(directory / "case_manifest.json")["status"], "prepared")

    def test_matched_triples_use_fresh_baseline_same_population_and_two_compiled_branches(self):
        directory = self.prepare()
        manifest = case.run_case(directory, acknowledge_conceptual_conflicts=True)
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(len(self.calls), 9)
        self.assertEqual({call["demand"] for call in self.calls}, {"test_case_inputs_demand"})
        self.assertEqual({call["last_iteration"] for call in self.calls}, {9})
        self.assertEqual([call["seed"] for call in self.calls], [4711] * 3 + [4712] * 3 + [4713] * 3)
        self.assertEqual(len({call["output"] for call in self.calls}), 9)
        for row in manifest["rows"]:
            baseline_id = case._completed(row["stages"]["baseline"])["run_id"]
            baseline = ifline.resolve_run_assets(f"{baseline_id}_sim")
            self.assertEqual(baseline["network_dir"].name, "test_case_inputs_network")
            for stage_name in ("closure", "alternative"):
                attempt = case._completed(row["stages"][stage_name])
                result = case._read(case._verify_file(attempt["result"]))
                record = case._read(case._verify_file(result["files"]["run_record"]))
                self.assertEqual(record["configuration"]["baseline_run"], f"{baseline_id}_sim")
                self.assertEqual(record["random_seeds"]["matsim"], row["seed"])
                self.assertEqual(result["files"]["plans"]["path"], "output/test_case_inputs_demand/8.xml/plan.xml")
                network = ET.parse(case._verify_file(result["files"]["network"]))
                self.assertEqual(network.find("links/link[@id='890']").get("modes"), "bike,walk")
                self.assertEqual(network.find("links/link[@id='2071']").get("modes"), "bike,walk")
                added = [link for link in network.findall("links/link") if link.get("id").startswith("ifplan_road")]
                self.assertEqual(len(added), 2 if stage_name == "alternative" else 0)
        aggregate = case._read(case._verify_file(manifest["aggregate"]))
        self.assertEqual(aggregate["completed_seeds"], case.DEFAULT_SEEDS)
        self.assertEqual(aggregate["incomplete_seeds"], [])
        self.assertEqual(set(aggregate["descriptive_ranges"]),
                         {"closure_vs_baseline", "alternative_vs_baseline", "alternative_vs_closure"})

    def test_prepare_and_completed_cases_never_overwrite(self):
        directory = self.prepare(seeds=[4711])
        spec_hash = case.sha256_file(directory / "case_spec.json")
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual(case.sha256_file(directory / "case_spec.json"), spec_hash)
        case.run_case(directory, acknowledge_conceptual_conflicts=True)
        with self.assertRaisesRegex(ValueError, "already completed"):
            case.run_case(directory, acknowledge_conceptual_conflicts=True, resume=True)
        self.assertEqual(len(self.calls), 3)

    def test_failed_branch_retains_artifacts_and_resumes_under_new_id(self):
        directory = self.prepare(seeds=[4711])
        original = self.simulate
        failed_paths = []

        def fail_once(**kwargs):
            path = original(**kwargs)
            if "closure_a01" in kwargs["output_subdir"]:
                failed_paths.append(path)
                raise RuntimeError("fixture interrupted closure")
            return path

        with patch.object(ifline, "run_simulation", side_effect=fail_once):
            with self.assertRaisesRegex(RuntimeError, "fixture interrupted"):
                case.run_case(directory, acknowledge_conceptual_conflicts=True)
        manifest = case._read(directory / "case_manifest.json")
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["rows"][0]["stages"]["baseline"]["attempts"][0]["status"], "completed")
        self.assertEqual(case._read(case._verify_file(manifest["aggregate"]))["completed_seeds"], [])
        retained = (failed_paths[0] / "output_config.xml").read_bytes()
        with self.assertRaisesRegex(ValueError, "resume"):
            case.run_case(directory, acknowledge_conceptual_conflicts=True)
        result = case.run_case(directory, acknowledge_conceptual_conflicts=True, resume=True)
        self.assertEqual(result["status"], "completed")
        attempts = result["rows"][0]["stages"]["closure"]["attempts"]
        self.assertEqual([attempt["status"] for attempt in attempts], ["failed", "completed"])
        self.assertTrue(attempts[-1]["run_id"].endswith("a02"))
        self.assertEqual((failed_paths[0] / "output_config.xml").read_bytes(), retained)
        self.assertEqual(sum("baseline" in call["output"] for call in self.calls), 1)

    def test_changed_snapshot_and_case_spec_stop_before_execution(self):
        directory = self.prepare()
        spec = case._read(directory / "case_spec.json")
        plans = self.root / spec["inputs"]["plans_file"]["path"]
        plans.write_text(plans.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, "changed case evidence"):
            case.run_case(directory, acknowledge_conceptual_conflicts=True)
        (directory / "case_spec.json").write_text('{}')
        with self.assertRaisesRegex(ValueError, "specification changed"):
            case.run_case(directory, acknowledge_conceptual_conflicts=True)
        self.assertEqual(self.calls, [])

    def test_changed_building_scene_invalidates_preparation(self):
        directory = self.prepare()
        scene = self.output / "source_sim" / "skyline_scene.json"
        data = case._read(scene)
        data["landmarks"]["buildings"][0]["height"] = 15
        scene.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "building evidence changed"):
            case.run_case(directory, acknowledge_conceptual_conflicts=True)
        self.assertEqual(self.calls, [])

    def test_actual_seed_mismatch_is_not_accepted_from_manifest_alone(self):
        directory = self.prepare(seeds=[4711])
        original = self.simulate

        def wrong_seed(**kwargs):
            sim = original(**kwargs)
            config = sim / "output_config.xml"
            config.write_text(config.read_text().replace('randomSeed" value="4711', 'randomSeed" value="9999'))
            return sim

        with patch.object(case, "run_simulation", side_effect=wrong_seed):
            with self.assertRaisesRegex(ValueError, "Actual simulation control mismatch"):
                case.run_case(directory, acknowledge_conceptual_conflicts=True)
        self.assertEqual(len(self.calls), 1)

    def test_existing_native_output_is_not_reused(self):
        directory = self.prepare(seeds=[4711])
        occupied = self.output / "test_case_s4711_baseline_a01_sim"
        occupied.mkdir()
        (occupied / "marker").write_text("retain me")
        with self.assertRaisesRegex(FileExistsError, "Refusing to reuse"):
            case.run_case(directory, acknowledge_conceptual_conflicts=True)
        self.assertEqual((occupied / "marker").read_text(), "retain me")
        self.assertEqual(self.calls, [])

    def test_case_lock_prevents_concurrent_runner(self):
        directory = self.prepare()
        with case._case_lock(directory):
            with self.assertRaisesRegex(ValueError, "already running"):
                case.run_case(directory, acknowledge_conceptual_conflicts=True)
        self.assertEqual(self.calls, [])

    def test_duplicate_iteration_row_is_not_accepted_by_row_count_alone(self):
        directory = self.prepare(seeds=[4711])
        original = self.simulate

        def duplicate_iteration(**kwargs):
            sim = original(**kwargs)
            score = sim / "scorestats.txt"
            score.write_text(score.read_text().replace('5\t-10\n', '4\t-10\n'))
            return sim

        with patch.object(case, "run_simulation", side_effect=duplicate_iteration):
            with self.assertRaisesRegex(ValueError, "duplicated"):
                case.run_case(directory, acknowledge_conceptual_conflicts=True)
        self.assertEqual(len(self.calls), 1)

    def test_completed_artifact_drift_blocks_recovery(self):
        directory = self.prepare(seeds=[4711])
        with patch.object(ifline, "run_simulation", side_effect=RuntimeError("fixture failure")):
            with self.assertRaisesRegex(RuntimeError, "fixture failure"):
                case.run_case(directory, acknowledge_conceptual_conflicts=True)
        manifest = case._read(directory / "case_manifest.json")
        attempt = case._completed(manifest["rows"][0]["stages"]["baseline"])
        result = case._read(case._verify_file(attempt["result"]))
        config = case._verify_file(result["files"]["output_config.xml"])
        config.write_text(config.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, "changed case evidence"):
            case.run_case(directory, acknowledge_conceptual_conflicts=True, resume=True)
        self.assertEqual(len(self.calls), 1)

    def test_new_baseline_source_building_diagnostics_must_match_preparation(self):
        directory = self.prepare(seeds=[4711])

        def changed_scene(name, **kwargs):
            path = self.scene(name)
            data = case._read(path)
            data["landmarks"]["buildings"][0]["points"] = [[2496600,2408780], [2496610,2408780],
                                                         [2496610,2408790], [2496600,2408790]]
            path.write_text(json.dumps(data))
            self.full_building_source(data["landmarks"]["buildings"][0]["points"])
            return path

        with patch.object(case, "render_skyline_scene", side_effect=changed_scene):
            with self.assertRaisesRegex(ValueError, "conflict diagnostics differ"):
                case.run_case(directory, acknowledge_conceptual_conflicts=True)
        # Closure has no footprint conflicts; only the alternative is blocked.
        self.assertEqual(len(self.calls), 2)

    def test_invalid_controls_and_unknown_geometry_fail_closed(self):
        for seeds, iterations in (([], 9), ([1, 1], 9), ([True], 9), ([0], 9),
                                   ([2**31], 9), (list(range(1, 12)), 9), ([1], 50), ([1], -1)):
            with self.subTest(seeds=seeds, iterations=iterations), self.assertRaises(ValueError):
                self.prepare(seeds=seeds, last_iteration=iterations)
        for case_id in ("../escape", "", "x" * 49):
            with self.assertRaises(ValueError):
                case.prepare_case(source_run="source_sim", case_id=case_id)
        source = self.output / "source_network" / "network.xml"
        source.write_text(NETWORK.replace('from="8844" to="8954"', 'from="8844" to="9032"'))
        with self.assertRaisesRegex(ValueError, "Original closure corridor"):
            self.prepare()
        self.assertFalse((self.output / "planning_cases").exists())

    def test_cli_requires_action_and_disallows_changing_frozen_run_controls(self):
        for args in ([], ["--prepare", "--run", "anything"], ["--run", "anything", "--seeds", "1"],
                     ["--prepare", "--acknowledge-conceptual-conflicts"]):
            with self.subTest(args=args), self.assertRaises(SystemExit) as exc:
                case.main(args)
            self.assertEqual(exc.exception.code, 2)
        self.assertEqual(self.calls, [])


class PlanningCaseAggregationTests(unittest.TestCase):
    @staticmethod
    def summary(name, duration, trips=1):
        return {"sim_output_subdir": name, "person_count": 1, "total_trips": trips, "last_score": -10,
                "mode_rows": [{"mode": "car", "count": trips, "share": 1,
                               "avg_time_seconds": duration, "avg_distance_m": 1000}]}

    def test_seed_pairing_ranges_and_alternative_relative_denominator(self):
        rows = [(4711, {"baseline": self.summary("b1", 100), "closure": self.summary("c1", 200),
                        "alternative": self.summary("a1", 150)}),
                (4712, {"baseline": self.summary("b2", 200), "closure": self.summary("c2", 180),
                        "alternative": self.summary("a2", 220)})]
        result = case.aggregate_results(rows, [4711, 4712, 4713])
        self.assertEqual(result["incomplete_seeds"], [4713])
        first = result["paired_results"][0]["comparisons"]["alternative_vs_closure"]
        self.assertEqual(first["delta"]["avg_trip_time_percent"], -25)
        values = result["descriptive_ranges"]["alternative_vs_closure"]["avg_trip_time_seconds"]
        self.assertEqual(values, {"n": 2, "missing": 0, "min": -50, "max": 40, "mean": -5, "median": -5})
        self.assertEqual(result["descriptive_ranges"]["alternative_vs_closure"]["car_mean_travel_time_s"], values)

    def test_car_mode_range_is_missing_when_either_side_has_no_car_trips(self):
        car = self.summary("car", 100)
        walk = copy.deepcopy(car)
        walk["mode_rows"][0]["mode"] = "walk"
        walk["sim_output_subdir"] = "walk"
        empty_car = self.summary("empty_car", 0, trips=0)
        cases = ((car, walk), (walk, car), (walk, walk), (empty_car, car), (car, empty_car))
        for baseline, closure in cases:
            with self.subTest(baseline=baseline, closure=closure):
                result = case.aggregate_results([(1, {"baseline": baseline, "closure": closure,
                                                      "alternative": closure})], [1])
                value = result["descriptive_ranges"]["closure_vs_baseline"]["car_mean_travel_time_s"]
                self.assertEqual(value, {"n": 0, "missing": 1, "min": None, "max": None,
                                         "mean": None, "median": None})
                self.assertIn("not paired trips", result["metric_definitions"]["car_mean_travel_time_s"]["population_basis"])

    def test_car_mode_range_excludes_missing_seed_instead_of_imputing_zero(self):
        baseline, closure = self.summary("b", 100), self.summary("c", 150)
        walk = copy.deepcopy(baseline)
        walk["mode_rows"][0]["mode"] = "walk"
        result = case.aggregate_results([
            (1, {"baseline": baseline, "closure": closure, "alternative": closure}),
            (2, {"baseline": walk, "closure": closure, "alternative": closure})], [1, 2])
        self.assertEqual(result["descriptive_ranges"]["closure_vs_baseline"]["car_mean_travel_time_s"],
                         {"n": 1, "missing": 1, "min": 50, "max": 50, "mean": 50, "median": 50})

    def test_undefined_percentage_stays_missing_not_zero(self):
        summary = self.summary("b", 0)
        result = case.aggregate_results([(1, {stage: summary for stage in case.STAGES})], [1])
        value = result["descriptive_ranges"]["closure_vs_baseline"]["avg_trip_time_percent"]
        self.assertEqual(value["n"], 0)
        self.assertEqual(value["missing"], 1)
        self.assertIsNone(value["mean"])

    def test_optional_impact_contract_and_module_absence_only_fallback(self):
        calls = []
        module = SimpleNamespace(analyze_impact=lambda *args, **kwargs: calls.append((args, kwargs)) or {"trips": {}})
        with patch.object(case.importlib, "import_module", return_value=module):
            self.assertTrue(case._optional_impact("b_sim", "a_sim")["available"])
        self.assertEqual(calls, [(("b_sim", "a_sim"), {"start_s": 0, "end_s": 108000, "mode": "all"})])
        with patch.object(case.importlib, "import_module", side_effect=ModuleNotFoundError(name="wrapper.impact")):
            self.assertFalse(case._optional_impact("b", "a")["available"])
        with patch.object(case.importlib, "import_module", side_effect=ModuleNotFoundError(name="broken_dependency")):
            with self.assertRaises(ModuleNotFoundError):
                case._optional_impact("b", "a")
        with patch.object(case.importlib, "import_module", return_value=SimpleNamespace(
                analyze_impact=lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("incomparable")))):
            with self.assertRaisesRegex(ValueError, "incomparable"):
                case._optional_impact("b", "a")


if __name__ == "__main__":
    unittest.main()
