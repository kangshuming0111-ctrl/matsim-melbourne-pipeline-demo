"""Deterministic, privacy-safe fixtures exercising the public impact interface."""

import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from wrapper import impact


HEADERS = ["person", "trip_number", "dep_time", "trav_time", "main_mode"]


def trip(person="private-person", number=1, departure="00:00:00", duration="00:01:00", mode="car"):
    return dict(zip(HEADERS, [person, str(number), departure, duration, mode]))


def event(time, kind, **attrs):
    return {"time": str(time), "type": kind, **attrs}


def traversal(person="private-person", vehicle="private-vehicle", mode="car", link="road", entry=10, leave=30,
              departure=0, arrival=60):
    return [event(departure, "departure", person=person, legMode=mode, link="start"),
            event(departure, "vehicle enters traffic", person=person, vehicle=vehicle, networkMode=mode, link="start"),
            event(entry - 1, "left link", vehicle=vehicle, link="start"),
            event(entry, "entered link", vehicle=vehicle, link=link),
            event(leave, "left link", vehicle=vehicle, link=link),
            event(leave + 1, "vehicle leaves traffic", vehicle=vehicle, person=person, link=link),
            event(arrival, "arrival", person=person, legMode=mode, link=link)]


class ImpactTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.plans = self.root / "demand" / "plan.xml"
        self.plans.parent.mkdir()
        self.plans.write_text('<population><person id="private-person"/></population>')
        self.assets = {}
        self.nodes = {"n0": (0, 0), "n1": (100, 0), "n2": (200, 0), "n3": (300, 0)}
        self.links = {"start": ("n0", "n1", 100, 10), "road": ("n1", "n2", 100, 10),
                      "empty": ("n2", "n3", 100, 10)}
        for name in ("baseline_sim", "proposal_sim"):
            sim = self.root / name
            sim.mkdir()
            source = self.root / (name + "_network.xml")
            source.write_text("<network/>")
            record = self.root / (name + "_manifest.json")
            record.write_text('{"status":"completed","random_seeds":{"matsim":4711}}')
            self.assets[name] = {"sim_dir": sim, "network_file": source, "plans_file": self.plans,
                                 "record_path": record, "record": {"status": "completed"}}
            self.write_config(name)
            self.write_network(name)
            self.write_trips(name, [trip()])
            self.write_events(name, traversal())
        self.resolver = patch.object(impact, "resolve_run_assets", side_effect=lambda name: self.assets[name])
        self.resolver.start()
        self.addCleanup(self.resolver.stop)

    def write_config(self, name, seed="4711", iterations="2", extra=None, reverse=False, plans=None):
        assets = self.assets[name]
        modules = {"global": {"randomSeed": seed, "coordinateSystem": "EPSG:7899"},
                   "controler": {"firstIteration": "0", "lastIteration": iterations, "outputDirectory": str(assets["sim_dir"])},
                   "network": {"inputNetworkFile": str(assets["network_file"])},
                   "plans": {"inputPlansFile": str(plans or assets["plans_file"])}}
        if extra:
            modules.update(extra)
        root = ET.Element("config")
        for key in reversed(list(modules)) if reverse else modules:
            module = ET.SubElement(root, "module", name=key)
            for param, value in modules[key].items():
                ET.SubElement(module, "param", name=param, value=value)
        ET.ElementTree(root).write(assets["sim_dir"] / "output_config.xml")

    def write_network(self, name, links=None, nodes=None):
        root = ET.Element("network")
        ns = ET.SubElement(root, "nodes")
        for key, (x, y) in (nodes or self.nodes).items():
            ET.SubElement(ns, "node", id=key, x=str(x), y=str(y))
        ls = ET.SubElement(root, "links")
        for key, (origin, dest, length, speed) in (links or self.links).items():
            ET.SubElement(ls, "link", {"id": key, "from": origin, "to": dest, "length": str(length),
                                      "freespeed": str(speed), "modes": "car,bike,walk"})
        with gzip.open(self.assets[name]["sim_dir"] / "output_network.xml.gz", "wb") as stream:
            ET.ElementTree(root).write(stream)

    def write_trips(self, name, rows, headers=HEADERS):
        with gzip.open(self.assets[name]["sim_dir"] / "output_trips.csv.gz", "wt", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers, delimiter=";", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def write_events(self, name, rows, sort=True):
        root = ET.Element("events")
        for attrs in sorted(rows, key=lambda row: float(row["time"])) if sort else rows:
            ET.SubElement(root, "event", attrs)
        with gzip.open(self.assets[name]["sim_dir"] / "output_events.xml.gz", "wb") as stream:
            ET.ElementTree(root).write(stream)

    def analyze(self, **kwargs):
        return impact.analyze_impact("baseline_sim", "proposal_sim", **kwargs)

    def row(self, result, key="road"):
        return next(row for row in result["network"]["links"] if row["id"] == key)

    def test_self_equivalent_pair_and_privacy_and_json_and_no_writes(self):
        paths = list(self.root.rglob("*"))
        original = {path: path.read_bytes() for path in paths if path.is_file()}
        result = self.analyze()
        self.assertEqual(result["trips"]["paired_count"], 1)
        self.assertEqual(result["trips"]["delta_s"], {"mean": 0, "median": 0, "p95": 0})
        self.assertEqual(result["trips"]["within_1s_count"], 1)
        self.assertEqual(self.row(result)["baseline"]["mean_travel_time_s"], 20)
        self.assertEqual(self.row(result)["baseline"]["mean_delay_s"], 10)
        self.assertEqual(self.row(result)["bin"], "within_1s")
        encoded = json.dumps(result, allow_nan=False)
        self.assertNotIn("private-person", encoded)
        self.assertNotIn("private-vehicle", encoded)
        self.assertEqual(original, {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()})
        self.assertEqual(result["sources"]["baseline"]["plans"]["sha256"], result["sources"]["proposal"]["plans"]["sha256"])
        self.assertEqual(result["sources"]["baseline"]["trip_headers"], HEADERS)
        for value in result["sources"]["baseline"].values():
            if isinstance(value, dict):
                self.assertEqual(len(value["sha256"]), 64)

    def test_baseline_window_and_mode_define_the_same_paired_population(self):
        self.write_trips("baseline_sim", [trip(departure="01:00:00", duration="100"),
                                         trip("at-end", departure="02:00:00", duration="50"),
                                         trip("baseline-bike", departure="01:00:00", duration="50", mode="bike")])
        self.write_trips("proposal_sim", [trip(departure="05:00:00", duration="80", mode="bike"),
                                         trip("at-end", departure="01:00:00", duration="20"),
                                         trip("baseline-bike", departure="01:00:00", duration="5", mode="car")])
        result = self.analyze(start_s=3600, end_s=7200)
        trips = result["trips"]
        self.assertEqual(trips["paired_count"], 1)
        self.assertEqual(trips["delta_s"]["mean"], -20)
        self.assertEqual(trips["baseline"], {"count": 1, "mean_s": 100, "p95_s": 100})
        self.assertEqual(trips["proposal"]["mean_s"], 80)
        self.assertEqual(trips["mode_switches"], [{"baseline_mode": "car", "proposal_mode": "bike", "count": 1}])

    def test_paired_delta_distribution_not_difference_of_percentiles(self):
        self.write_trips("baseline_sim", [trip(str(i), duration=str(value)) for i, value in enumerate([100, 200, 300, 400])])
        self.write_trips("proposal_sim", [trip(str(i), duration=str(value)) for i, value in enumerate([90, 220, 300.5, 300])])
        result = self.analyze()["trips"]
        self.assertEqual((result["faster_count"], result["slower_count"], result["within_1s_count"]), (2, 1, 1))
        self.assertEqual(result["delta_s"]["mean"], -22.375)
        self.assertEqual(result["delta_s"]["median"], -4.75)
        self.assertAlmostEqual(result["delta_s"]["p95"], 17.075)

    def test_invalid_and_missing_and_duplicate_rows_never_become_zero_duration(self):
        self.write_trips("baseline_sim", [trip("good", duration="0"), trip("bad", duration="nonsense"),
                                         trip("missing"), trip("duplicate-proposal"), trip("duplicate-base"), trip("duplicate-base"),
                                         trip("bad-departure", departure="nan"), trip("", duration="9")])
        self.write_trips("proposal_sim", [trip("good", duration="0"), trip("bad"), trip("duplicate-proposal"),
                                         trip("duplicate-proposal"), trip("proposal-only"), trip("duplicate-base")])
        result = self.analyze()["trips"]
        self.assertEqual(result["paired_count"], 1)
        self.assertEqual(result["baseline"]["mean_s"], 0)
        self.assertEqual(result["unmatched"], {"baseline_missing_in_proposal": 1,
                         "proposal_only_in_own_window": 1, "proposal_duplicate_keys_in_cohort": 1,
                         "invalid_pairs_in_cohort": 1})
        self.assertEqual(result["quality"]["baseline"]["duplicate_keys"], 1)
        self.assertEqual(result["quality"]["baseline"]["invalid_rows"], 3)
        self.assertEqual(result["quality"]["baseline"]["invalid_key_rows"], 1)

    def test_30_hour_and_fractional_times_and_invalid_hms(self):
        self.write_trips("baseline_sim", [trip(departure="30:00:00.5", duration="00:00:00"),
                                         trip("bad", departure="30:00:01", duration="00:60:00")])
        self.write_trips("proposal_sim", [trip(departure="31:00:00", duration="0.5"),
                                         trip("bad", departure="31:00:01", duration="-1")])
        result = self.analyze(start_s=108000, end_s=172800)["trips"]
        self.assertEqual(result["paired_count"], 1)
        self.assertEqual(result["delta_s"]["mean"], .5)
        self.assertEqual(result["unmatched"]["invalid_pairs_in_cohort"], 1)

    def test_actual_export_empty_main_mode_falls_back_only_to_unambiguous_modes(self):
        headers = HEADERS + ["modes"]
        rows = [{**trip(), "main_mode": "", "modes": "car"},
                {**trip("mixed"), "main_mode": "", "modes": "walk,car"},
                {**trip("main-wins", mode="bike"), "modes": "car"}]
        for name in self.assets:
            self.write_trips(name, rows, headers=headers)
        result = self.analyze()["trips"]
        self.assertEqual(result["paired_count"], 1)
        self.assertEqual(result["quality"]["baseline"]["mode_fallback_rows"], 1)
        self.assertEqual(result["quality"]["baseline"]["invalid_mode_rows"], 1)
        self.assertEqual(self.analyze(mode="bike")["trips"]["paired_count"], 1)

    def test_counts_real_zero_separately_from_missing_measurement(self):
        self.write_events("proposal_sim", [])
        result = self.analyze()
        row = self.row(result)
        self.assertEqual(row["proposal"]["entered_count"], 0)
        self.assertIsNone(row["proposal"]["mean_travel_time_s"])
        self.assertEqual(row["state"], "no_data")
        self.assertTrue(all(value is None for value in row["delta"].values()))
        self.assertEqual(row["bin"], "unavailable")
        self.assertNotEqual(row["color"], impact._COLORS["within_1s"])
        self.assertEqual(self.row(result, "empty")["baseline"]["complete_traversal_count"], 0)
        self.assertIsNone(self.row(result, "empty")["delta"]["mean_travel_time_s"])

    def test_zero_second_observed_traversal_is_available_and_signed_delay_not_clipped(self):
        for name in self.assets:
            self.write_events(name, traversal(entry=10, leave=10))
        row = self.row(self.analyze())
        self.assertTrue(row["comparable"])
        self.assertEqual(row["baseline"]["complete_traversal_count"], 1)
        self.assertEqual(row["baseline"]["mean_travel_time_s"], 0)
        self.assertEqual(row["baseline"]["mean_delay_s"], -10)
        self.assertEqual(row["delta"]["mean_travel_time_s"], 0)

    def test_no_paired_trips_return_null_distributions(self):
        self.write_trips("proposal_sim", [trip("different-person")])
        result = self.analyze()["trips"]
        self.assertEqual(result["paired_count"], 0)
        self.assertEqual(result["delta_s"], {"mean": None, "median": None, "p95": None})
        self.assertEqual(result["baseline"], {"count": 0, "mean_s": None, "p95_s": None})
        self.assertEqual(result["unmatched"]["baseline_missing_in_proposal"], 1)
        self.assertEqual(result["unmatched"]["proposal_only_in_own_window"], 1)

    def test_entered_time_window_not_exit_time(self):
        events = traversal(entry=10, leave=40)
        self.write_events("baseline_sim", events)
        result = self.analyze(start_s=10, end_s=20)
        self.assertEqual(self.row(result)["baseline"]["complete_traversal_count"], 1)
        self.assertEqual(self.row(result)["baseline"]["mean_travel_time_s"], 30)
        result = self.analyze(start_s=0, end_s=10)
        self.assertEqual(self.row(result)["baseline"]["entered_count"], 0)

    def test_departure_partial_and_parking_gap_and_unfinished_entries_excluded(self):
        events = traversal(entry=10, leave=30)
        events += [event(35, "entered link", vehicle="private-vehicle", link="road"),
                   event(100, "vehicle enters traffic", person="private-person", vehicle="private-vehicle", networkMode="car", link="road"),
                   event(105, "left link", vehicle="private-vehicle", link="road"),
                   event(110, "entered link", vehicle="private-vehicle", link="road"),
                   event(120, "vehicle leaves traffic", vehicle="private-vehicle"),
                   event(1000, "left link", vehicle="private-vehicle", link="road")]
        self.write_events("baseline_sim", events)
        result = self.analyze()
        row = self.row(result)
        self.assertEqual(row["baseline"]["entered_count"], 2)
        self.assertEqual(row["baseline"]["complete_traversal_count"], 1)
        self.assertEqual(row["baseline"]["mean_travel_time_s"], 20)
        self.assertEqual(self.row(result, "start")["baseline"]["entered_count"], 0)
        quality = result["network"]["quality"]["baseline"]
        self.assertEqual(quality["partial_departure_link_exits"], 2)
        self.assertEqual(quality["incomplete_link_entries"], 1)
        self.assertEqual(quality["unattributed_link_entries"], 1)

    def test_actual_vehicle_network_modes_and_teleported_availability(self):
        self.write_events("baseline_sim", traversal(mode="bike"))
        car = self.analyze()
        self.assertEqual(self.row(car)["baseline"]["entered_count"], 0)
        bike = self.analyze(mode="bike")
        self.assertEqual(self.row(bike)["baseline"]["entered_count"], 1)
        all_modes = self.analyze(mode="all")
        self.assertEqual(all_modes["network"]["modes"], ["bike", "car"])
        self.assertIn("car + bike", all_modes["network"]["label"])
        for mode in ("walk", "pt"):
            result = self.analyze(mode=mode)
            self.assertFalse(result["network"]["available"])
            self.assertIsNone(self.row(result)["baseline"])
            self.assertIsNone(result["network"]["summary"]["baseline"])
            self.assertEqual(self.row(result)["bin"], "unavailable")

    def test_changed_freeflow_speed_is_allowed_and_delay_reference_is_per_run(self):
        links = {**self.links, "road": ("n1", "n2", 100, 20)}
        self.write_network("proposal_sim", links=links)
        self.write_events("proposal_sim", traversal(leave=25))
        result = self.analyze()
        row = self.row(result)
        self.assertTrue(row["comparable"])
        self.assertEqual(row["baseline_geometry"]["freeflow_s"], 10)
        self.assertEqual(row["proposal_geometry"]["freeflow_s"], 5)
        self.assertEqual(row["delta"]["mean_travel_time_s"], -5)
        self.assertEqual(row["delta"]["mean_delay_s"], 0)
        self.assertIn("each run", result["network"]["delay_reference"])

    def test_geometry_changes_block_all_signed_deltas_and_new_removed_links_stay_in_map(self):
        nodes = {**self.nodes, "n4": (200, 100)}
        links = {"start": self.links["start"], "road": ("n1", "n4", 100, 10), "new": ("n4", "n3", 100, 10)}
        self.write_network("proposal_sim", nodes=nodes, links=links)
        result = self.analyze(link_ids=["road"])
        self.assertEqual(len(result["network"]["links"]), 4)
        self.assertEqual(self.row(result)["state"], "geometry_changed")
        self.assertTrue(all(value is None for value in self.row(result)["delta"].values()))
        self.assertEqual(self.row(result, "new")["state"], "new")
        self.assertIsNone(self.row(result, "new")["baseline"])
        self.assertEqual(self.row(result, "empty")["state"], "removed")
        self.assertIsNone(self.row(result, "empty")["proposal"])
        self.assertEqual(result["network"]["summary"]["link_count"], 1)
        self.assertEqual(result["network"]["outside_selection"]["link_count"], 3)
        self.assertEqual(result["network"]["outside_selection"]["label"], "outside selection")

    def test_split_shortened_existing_id_and_new_piece_are_unavailable(self):
        nodes = {**self.nodes, "mid": (150, 0)}
        links = {**self.links, "road": ("n1", "mid", 50, 10), "piece": ("mid", "n2", 50, 10)}
        self.write_network("proposal_sim", links=links, nodes=nodes)
        result = self.analyze()
        for key in ("road", "piece"):
            self.assertEqual(self.row(result, key)["state"], "split")
            self.assertEqual(self.row(result, key)["bin"], "unavailable")

    def test_selection_uses_either_run_and_whole_trip_but_retains_entire_map(self):
        self.write_trips("baseline_sim", [trip("selected", duration="120"), trip("other", duration="100")])
        self.write_trips("proposal_sim", [trip("selected", duration="90"), trip("other", duration="50")])
        self.write_events("baseline_sim", traversal(person="selected", link="start", entry=20, leave=30))
        self.write_events("proposal_sim", traversal(person="selected", link="road", entry=40, leave=50))
        result = self.analyze(start_s=0, end_s=10, link_ids=["road"])
        self.assertEqual(result["trips"]["paired_count"], 1)
        self.assertEqual(result["trips"]["delta_s"]["mean"], -30)
        self.assertEqual(len(result["network"]["links"]), 3)
        self.assertEqual(result["network"]["summary"]["link_count"], 1)
        self.assertEqual(result["network"]["outside_selection"]["link_count"], 2)
        self.assertEqual(result["network"]["summary"]["proposal"]["entered_count"], 0)

    def test_trip_number_not_person_alone_and_reused_vehicle_does_not_select_all_trips(self):
        rows = [trip(number=1, duration="60"), trip(number=2, departure="100", duration="60")]
        self.write_trips("baseline_sim", rows)
        self.write_trips("proposal_sim", [rows[0], trip(number=2, departure="100", duration="30")])
        events = traversal(link="start") + traversal(departure=100, entry=110, leave=120, arrival=130)
        self.write_events("baseline_sim", events)
        self.write_events("proposal_sim", events)
        result = self.analyze(link_ids=["road"])
        self.assertEqual(result["trips"]["paired_count"], 1)
        self.assertEqual(result["trips"]["delta_s"]["mean"], -30)

    def test_overlapping_trip_intervals_do_not_guess_selected_membership(self):
        rows = [trip(number=1, duration="1000"), trip(number=2, departure="100", duration="10"),
                trip(number=3, departure="200", duration="100")]
        for name in self.assets:
            self.write_trips(name, rows)
            self.write_events(name, traversal(departure=200, entry=220, leave=230, arrival=300))
        result = self.analyze(link_ids=["road"])
        self.assertEqual(result["trips"]["paired_count"], 0)
        self.assertEqual(result["network"]["quality"]["baseline"]["selected_traversals_without_trip"], 1)

    def test_partial_arrival_and_malformed_vehicle_leave_break_pending_pairs(self):
        rows = traversal()[:4] + [event(20, "vehicle leaves traffic", vehicle="private-vehicle", link="road"),
                                 event(30, "left link", vehicle="private-vehicle", link="road")]
        self.write_events("baseline_sim", rows)
        result = self.analyze()
        self.assertEqual(self.row(result)["baseline"]["complete_traversal_count"], 0)
        self.assertEqual(result["network"]["quality"]["baseline"]["partial_arrival_link_entries"], 1)
        rows[4]["time"] = "invalid"
        self.write_events("baseline_sim", rows, sort=False)
        result = self.analyze()
        self.assertEqual(self.row(result)["baseline"]["complete_traversal_count"], 0)
        self.assertEqual(result["network"]["quality"]["baseline"]["invalid_time_events"], 1)

    def test_completion_counts_by_mode_window_and_stuck_are_diagnostics(self):
        events = traversal() + [event(5, "departure", person="walk-person", legMode="walk"),
                                event(50, "stuckAndAbort", person="walk-person", legMode="walk"),
                                event(100, "arrival", person="late", legMode="pt")]
        self.write_events("baseline_sim", events)
        result = self.analyze(end_s=100)
        self.assertEqual(result["completion"]["baseline"]["walk"], {"departures": 1, "arrivals": 0, "stuck": 1})
        self.assertEqual(result["completion"]["baseline"]["car"], {"departures": 1, "arrivals": 1, "stuck": 0})
        self.assertEqual(result["completion"]["baseline"]["pt"]["arrivals"], 0)

    def test_fixed_bins_and_strict_neutral_boundary(self):
        cases = [(-60, "le_minus_60"), (-59, "minus_60_to_minus_15"), (-15, "minus_60_to_minus_15"),
                 (-14, "minus_15_to_minus_1"), (-1, "minus_15_to_minus_1"), (-.9, "within_1s"),
                 (0, "within_1s"), (.9, "within_1s"), (1, "plus_1_to_plus_15"),
                 (15, "plus_15_to_plus_60"), (60, "ge_plus_60")]
        self.write_events("baseline_sim", traversal(entry=10, leave=110, arrival=200))
        for delta, expected in cases:
            with self.subTest(delta=delta):
                self.write_events("proposal_sim", traversal(entry=10, leave=110 + delta, arrival=200))
                result = self.analyze()
                self.assertEqual(self.row(result)["bin"], expected)
                self.assertTrue(all(0 <= component <= 1 for component in self.row(result)["color"]))

    def test_rejects_bad_windows_modes_and_selection_before_resolving(self):
        bad = [{"start_s": -1}, {"start_s": 10, "end_s": 10}, {"end_s": 172801},
               {"start_s": float("nan")}, {"end_s": float("inf")}, {"start_s": True},
               {"end_s": None}, {"mode": "hovercraft"}, {"mode": []}, {"link_ids": "road"},
               {"link_ids": ["road"] * 101}, {"link_ids": ["road", "road"]}, {"link_ids": [None]}]
        with patch.object(impact, "resolve_run_assets") as resolver:
            for kwargs in bad:
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    self.analyze(**kwargs)
            resolver.assert_not_called()
        with self.assertRaisesRegex(ValueError, "network union"):
            self.analyze(link_ids=["missing"])

    def test_rejects_config_drift_even_with_lying_matching_manifest(self):
        for kwargs in ({"seed": "12"}, {"iterations": "3"}, {"extra": {"qsim": {"flowCapFactor": "0.5"}}}):
            self.write_config("proposal_sim", **kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "actual output configs differ"):
                self.analyze()

    def test_normalizes_xml_order_and_ignores_only_two_permitted_parameters(self):
        self.write_config("proposal_sim", reverse=True)
        self.assertTrue(self.analyze()["comparability"]["normalized_config_equal"])
        config = self.assets["proposal_sim"]["sim_dir"] / "output_config.xml"
        root = ET.parse(config)
        root.find("./module[@name='controler']/param[@name='firstIteration']").set("value", "1")
        root.write(config)
        with self.assertRaisesRegex(ValueError, "actual output configs differ"):
            self.analyze()

    def test_rejects_missing_seed_instead_of_manifest_default(self):
        for assets in self.assets.values():
            path = assets["sim_dir"] / "output_config.xml"
            tree = ET.parse(path)
            module = tree.find("./module[@name='global']")
            module.remove(module.find("param[@name='randomSeed']"))
            tree.write(path)
        with self.assertRaisesRegex(ValueError, "randomSeed"):
            self.analyze()

    def test_config_plans_pointer_must_match_resolved_actual_artifact(self):
        wrong = self.root / "other.xml"
        wrong.write_text("<population/>")
        for name in self.assets:
            self.write_config(name, plans=wrong)
        with self.assertRaisesRegex(ValueError, "input path"):
            self.analyze()

    def test_actual_plans_hash_not_recorded_hash_is_compared(self):
        # Identical Docker paths in separately resolved output roots can address different bytes.
        for name, assets in self.assets.items():
            partition = self.root / name / "output"
            partition.mkdir()
            plans = partition / "same_plans.xml"
            plans.write_text('<population name="' + name + '"/>')
            assets["plans_file"] = plans
            # The /app/output mapping is rooted at sim_dir.parent.
            assets["sim_dir"] = partition / "run_sim"
            assets["sim_dir"].mkdir()
            self.write_config(name, plans=Path("/app/output/same_plans.xml"))
            self.write_network(name)
            self.write_trips(name, [trip()])
            self.write_events(name, [])
        with self.assertRaisesRegex(ValueError, "actual input plans SHA-256"):
            self.analyze()

    def test_absent_events_or_headers_fail_without_fabricating_results(self):
        self.write_trips("proposal_sim", [trip()], headers=["dep_time", "trav_time", "main_mode"])
        with self.assertRaisesRegex(ValueError, "person, trip_number"):
            self.analyze()
        self.write_trips("proposal_sim", [trip()])
        (self.assets["proposal_sim"]["sim_dir"] / "output_events.xml.gz").unlink()
        with self.assertRaises(FileNotFoundError):
            self.analyze()

    def test_completed_assets_resolution_failure_propagates_without_other_work(self):
        with patch.object(impact, "resolve_run_assets", side_effect=ValueError("Baseline run is not marked completed")):
            with self.assertRaisesRegex(ValueError, "not marked completed"):
                self.analyze()

    def test_changes_to_source_files_during_analysis_reject_mixed_evidence(self):
        original = impact._events
        def change_after_reading(*args, **kwargs):
            result = original(*args, **kwargs)
            self.plans.write_text(self.plans.read_text() + " ")
            return result
        with patch.object(impact, "_events", side_effect=change_after_reading):
            with self.assertRaisesRegex(ValueError, "changed during impact analysis"):
                self.analyze()


if __name__ == "__main__":
    unittest.main()
