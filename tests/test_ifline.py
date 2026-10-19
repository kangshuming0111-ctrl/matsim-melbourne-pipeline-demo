import gzip
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from wrapper.ifline import (
    apply_network_intervention,
    compare_summaries,
    network_map,
    validate_intervention,
)


NETWORK = """<?xml version="1.0" encoding="UTF-8"?>
<network>
  <nodes>
    <node id="a" x="0" y="0" />
    <node id="b" x="100" y="0" />
    <node id="c" x="200" y="0" />
  </nodes>
  <links>
    <link id="1" from="a" to="b" length="100" freespeed="13.8888889" capacity="1200" permlanes="2" modes="car,bike,walk" />
    <link id="2" from="b" to="a" length="100" freespeed="13.8888889" capacity="1200" permlanes="2" modes="car,bike,walk" />
    <link id="3" from="b" to="c" length="100" freespeed="8.3333333" capacity="600" permlanes="1" modes="bike,walk" />
  </links>
</network>
"""


def _links(path: Path):
    return {link.get("id"): link for link in ET.parse(path).getroot().find("links")}


def _nodes(path: Path):
    return {node.get("id"): node for node in ET.parse(path).getroot().find("nodes")}


class IfLineNetworkTests(unittest.TestCase):
    def _apply(self, intervention):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        source = root / "baseline.xml"
        target = root / "branch" / "network.xml"
        source.write_text(NETWORK)
        changed = apply_network_intervention(source, target, intervention)
        return temporary, source, target, changed

    def test_speed_limit_changes_selected_and_exact_reverse_only(self):
        temporary, source, target, changed = self._apply({
            "type": "speed_limit", "link_id": "1", "value": 30, "include_reverse": True,
        })
        with temporary:
            result = _links(target)
            self.assertEqual({row["link_id"] for row in changed}, {"1", "2"})
            self.assertAlmostEqual(float(result["1"].get("freespeed")) * 3.6, 30)
            self.assertAlmostEqual(float(result["2"].get("freespeed")) * 3.6, 30)
            self.assertAlmostEqual(float(_links(source)["1"].get("freespeed")) * 3.6, 50)

    def test_capacity_scale_is_relative_to_recorded_baseline(self):
        temporary, _, target, changed = self._apply({
            "type": "capacity_scale", "link_id": "1", "value": 125, "include_reverse": False,
        })
        with temporary:
            self.assertEqual([row["link_id"] for row in changed], ["1"])
            self.assertEqual(float(_links(target)["1"].get("capacity")), 1500)
            self.assertEqual(float(_links(target)["2"].get("capacity")), 1200)

    def test_road_closure_removes_car_but_preserves_other_modes(self):
        temporary, _, target, changed = self._apply({
            "type": "road_closure", "link_id": "1", "include_reverse": True,
        })
        with temporary:
            result = _links(target)
            self.assertEqual({row["link_id"] for row in changed}, {"1", "2"})
            self.assertEqual(result["1"].get("modes"), "bike,walk")
            self.assertEqual(result["2"].get("modes"), "bike,walk")
            self.assertEqual(result["3"].get("modes"), "bike,walk")

    def test_rejects_missing_and_non_finite_values(self):
        for value in (None, "not-a-number", float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_intervention({"type": "speed_limit", "link_id": "1", "value": value})

    def test_network_map_exposes_all_modes_editability_and_observed_volume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            network = root / "network.xml"
            network.write_text(NETWORK)
            with gzip.open(root / "output_events.xml.gz", "wt") as stream:
                stream.write(
                    '<events><event time="10" type="entered link" link="1" />'
                    '<event time="11" type="entered link" link="1" /></events>'
                )
            with patch("wrapper.ifline.resolve_run_assets", return_value={
                "network_file": network,
                "sim_dir": root,
            }):
                result = network_map("baseline")

        self.assertEqual(result["run_name"], "baseline")
        self.assertEqual({link["id"] for link in result["links"]}, {"1", "2", "3"})
        selected = next(link for link in result["links"] if link["id"] == "1")
        self.assertEqual(selected["modes"], ["bike", "car", "walk"])
        self.assertTrue(selected["car_editable"])
        self.assertEqual(selected["volume"], 2)
        path = next(link for link in result["links"] if link["id"] == "3")
        self.assertEqual(path["modes"], ["bike", "walk"])
        self.assertFalse(path["car_editable"])

    def test_new_road_adds_connected_bidirectional_links_and_one_geometry_node(self):
        temporary, source, target, changed = self._apply({
            "type": "new_road",
            "points": [[2, 1], [100, 50], [199, 2]],
            "speed_kph": 55,
            "lanes": 1.5,
            "capacity_per_hour": 1350,
            "bidirectional": True,
            "snap_tolerance_m": 5,
            "modes": ["car", "bike", "walk"],
        })
        with temporary:
            result_links = _links(target)
            result_nodes = _nodes(target)
            added = [row for row in changed if row["action"] == "added"]
            self.assertEqual(len(added), 4)
            self.assertEqual(len(result_links), len(_links(source)) + 4)
            self.assertEqual(len(result_nodes), len(_nodes(source)) + 1)
            forward = result_links["ifline_new_1_f1"]
            reverse = result_links["ifline_new_1_r1"]
            self.assertEqual(forward.get("from"), "a")
            self.assertEqual(reverse.get("to"), "a")
            self.assertAlmostEqual(float(forward.get("freespeed")) * 3.6, 55)
            self.assertAlmostEqual(float(forward.get("capacity")), 1350)
            self.assertAlmostEqual(float(forward.get("permlanes")), 1.5)
            self.assertEqual(forward.get("modes"), "car,bike,walk")
            summary = added[0]["road_summary"]
            self.assertEqual(summary["created_nodes"], 1)
            self.assertTrue(summary["resolved_points"][0]["snapped"])
            self.assertTrue(summary["resolved_points"][-1]["snapped"])

    def test_new_road_rejects_an_endpoint_that_does_not_connect(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "baseline.xml"
            source.write_text(NETWORK)
            with self.assertRaisesRegex(ValueError, "start is .*nearest network node"):
                apply_network_intervention(source, root / "branch" / "network.xml", {
                    "type": "new_road",
                    "points": [[50, 50], [100, 50], [199, 2]],
                    "speed_kph": 40,
                    "lanes": 1,
                    "capacity_per_hour": 900,
                    "bidirectional": True,
                    "snap_tolerance_m": 5,
                })

    def test_new_road_validation_rejects_invalid_geometry_and_parameters(self):
        base = {
            "type": "new_road", "points": [[0, 0], [100, 0]],
            "speed_kph": 40, "lanes": 1, "capacity_per_hour": 900,
            "snap_tolerance_m": 30,
        }
        for replacement in (
            {"points": [[0, 0]]},
            {"points": [[0, 0], [float("nan"), 1]]},
            {"lanes": 0},
            {"capacity_per_hour": 50},
            {"speed_kph": 200},
        ):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                validate_intervention({**base, **replacement})


class IfLineComparisonTests(unittest.TestCase):
    def test_overall_change_is_trip_weighted_and_modes_are_aligned(self):
        baseline = {
            "sim_output_subdir": "base_sim", "person_count": 10, "total_trips": 10,
            "last_score": -10.0,
            "mode_rows": [
                {"mode": "car", "count": 8, "share": 0.8, "avg_time_seconds": 600, "avg_distance_m": 5000},
                {"mode": "walk", "count": 2, "share": 0.2, "avg_time_seconds": 300, "avg_distance_m": 1000},
            ],
        }
        proposal = {
            "sim_output_subdir": "branch_sim", "person_count": 10, "total_trips": 10,
            "last_score": -9.5,
            "mode_rows": [
                {"mode": "car", "count": 7, "share": 0.7, "avg_time_seconds": 660, "avg_distance_m": 5200},
                {"mode": "walk", "count": 3, "share": 0.3, "avg_time_seconds": 300, "avg_distance_m": 1000},
            ],
        }

        result = compare_summaries(baseline, proposal)

        self.assertAlmostEqual(result["delta"]["avg_trip_time_seconds"], 12)
        self.assertAlmostEqual(result["delta"]["avg_trip_time_percent"], 2.2222222222)
        self.assertAlmostEqual(result["delta"]["avg_trip_distance_m"], -260)
        self.assertAlmostEqual(result["delta"]["avg_trip_distance_percent"], -6.1904761905)
        self.assertAlmostEqual(result["delta"]["last_score"], 0.5)
        car = next(row for row in result["mode_changes"] if row["mode"] == "car")
        self.assertAlmostEqual(car["share_delta_points"], -10)
        self.assertEqual(car["count_delta"], -1)
        self.assertAlmostEqual(car["avg_time_delta_percent"], 10)
        self.assertAlmostEqual(car["avg_distance_delta_m"], 200)


if __name__ == "__main__":
    unittest.main()
