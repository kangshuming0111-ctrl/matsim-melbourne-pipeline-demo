import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wrapper import analyze, runs
from wrapper.ifline import compare_summaries
from wrapper.impact import _time
from wrapper.measurements import parse_time, nonnegative_number, trip_mode


class MeasurementQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.directory = self.output / "fixture_sim"
        self.directory.mkdir()
        with gzip.open(self.directory / "output_persons.csv.gz", "wt") as stream:
            stream.write("person\n1\n")
        (self.directory / "scorestats.txt").write_text("ITERATION\tavg. EXECUTED\n0\t-10\n1\t-9\n")
        self.mock = patch.object(analyze, "OUTPUT_DIR", self.output)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def summary(self, rows):
        fields = ["modes", "main_mode", "trav_time", "traveled_distance"]
        with gzip.open(self.directory / "output_trips.csv.gz", "wt", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, delimiter=";")
            writer.writeheader()
            writer.writerows(rows)
        return analyze.compute_summary_data("fixture_sim")

    @staticmethod
    def row(time, distance, mode="car"):
        return {"modes": mode, "trav_time": time, "traveled_distance": distance}

    def test_missing_measurements_do_not_halve_the_mean(self):
        result = self.summary([self.row("00:01:30", "1000"), self.row("", "")])
        row = result["mode_rows"][0]
        self.assertEqual((row["avg_time_seconds"], row["avg_distance_m"]), (90, 1000))
        self.assertEqual(row["time_quality"], {"valid": 1, "missing": 1, "invalid": 0})
        self.assertEqual(result["total_trips"], 2)

    def test_all_missing_is_null_and_markdown_can_render_it(self):
        result = self.summary([self.row("", " ")])
        row = result["mode_rows"][0]
        self.assertIsNone(row["avg_time_seconds"])
        self.assertIsNone(row["avg_distance_m"])
        self.assertIn("null", json.dumps(result, allow_nan=False))
        report = analyze.summarize("fixture_sim").read_text()
        self.assertIn("无有效数据", report)
        self.assertIn("0/1/0", report)

    def test_real_zero_is_valid_and_not_missing(self):
        row = self.summary([self.row("00:00:00", "0"), self.row("", "")])["mode_rows"][0]
        self.assertEqual(row["avg_time_seconds"], 0)
        self.assertEqual(row["avg_distance_m"], 0)
        self.assertEqual(row["avg_time_label"], "0 秒")
        self.assertEqual(row["time_quality"]["valid"], 1)

    def test_malformed_negative_and_nonfinite_are_invalid(self):
        values = ["broken", "-1", "NaN", "inf", "-inf"]
        result = self.summary([self.row(v, v) for v in values] + [self.row("90", "1000")])
        row = result["mode_rows"][0]
        self.assertEqual((row["avg_time_seconds"], row["avg_distance_m"]), (90, 1000))
        self.assertEqual(row["time_quality"], {"valid": 1, "missing": 0, "invalid": 5})
        self.assertEqual(row["distance_quality"]["invalid"], 5)
        json.dumps(result, allow_nan=False)

    def test_time_and_distance_use_independent_denominators(self):
        row = self.summary([self.row("90", ""), self.row("", "1000")])["mode_rows"][0]
        self.assertEqual((row["avg_time_seconds"], row["avg_distance_m"]), (90, 1000))
        self.assertEqual(row["time_quality"]["valid"], 1)
        self.assertEqual(row["distance_quality"]["valid"], 1)

    def test_empty_trips_produces_unavailable_overall_comparison(self):
        result = self.summary([])
        comparison = compare_summaries(result, result)
        self.assertEqual(result["total_trips"], 0)
        self.assertIsNone(comparison["baseline"]["avg_trip_time_seconds"])
        self.assertIsNone(comparison["delta"]["avg_trip_time_seconds"])

    def test_valid_sample_weighting_across_modes(self):
        rows = [self.row("90", "1000")] + [self.row("", "") for _ in range(9)]
        rows += [self.row("30", "100", "walk"), self.row("30", "100", "walk")]
        result = self.summary(rows)
        comparison = compare_summaries(result, result)
        self.assertEqual(comparison["baseline"]["avg_trip_time_seconds"], 50)
        self.assertEqual(comparison["baseline"]["avg_trip_distance_m"], 400)
        self.assertEqual(comparison["baseline"]["time_valid_count"], 3)
        self.assertEqual(comparison["delta"]["avg_trip_time_seconds"], 0)

    def test_comparison_propagates_unavailable(self):
        valid = self.summary([self.row("90", "1000")])
        missing = self.summary([self.row("", "")])
        result = compare_summaries(valid, missing)
        for key in ("avg_trip_time_seconds", "avg_trip_time_percent", "avg_trip_distance_m", "avg_trip_distance_percent"):
            self.assertIsNone(result["delta"][key])
        self.assertIsNone(result["mode_changes"][0]["avg_time_delta_seconds"])
        self.assertEqual(result["proposal"]["time_valid_count"], 0)

    def test_absent_mode_does_not_imply_zero_duration(self):
        base = self.summary([self.row("90", "1000", "car")])
        alt = self.summary([self.row("30", "100", "walk")])
        result = compare_summaries(base, alt)
        for row in result["mode_changes"]:
            self.assertIsNone(row["avg_time_delta_seconds"])

    def test_main_mode_and_unambiguous_fallback_match_impact(self):
        result = self.summary([
            {"main_mode":"pt", "modes":"walk,pt,walk", "trav_time":"90", "traveled_distance":"1000"},
            self.row("30", "100", "car"),
            self.row("20", "50", "car,walk")])
        self.assertEqual({r["mode"] for r in result["mode_rows"]}, {"pt", "car", "(未知)"})
        self.assertEqual(result["data_quality"]["mode"], {"unknown":1, "fallback":1})

    def test_hours_over_24_and_fractional_seconds(self):
        self.assertIs(_time, parse_time)
        for value, expected in [("30:00:00",108000), ("1:02:03.5",3723.5), ("90.5",90.5), (" 00:00:00 ",0)]:
            with self.subTest(value=value):
                self.assertEqual(parse_time(value), expected)

    def test_invalid_clock_components_and_overflow_are_unavailable(self):
        for value in ["00:60:00", "00:00:60", "1.5:00:00", "-1:00:00", "00:-1:00", "00:00:NaN", "1e309:00:00", "0:1.5:0", "a:b:c", None, ""]:
            with self.subTest(value=value):
                self.assertIsNone(parse_time(value))

    def test_fully_measured_result_preserves_expected_mean_and_count(self):
        row = self.summary([self.row("00:01:00", "1000"), self.row("00:02:00", "2000")])["mode_rows"][0]
        self.assertEqual((row["count"], row["avg_time_seconds"], row["avg_distance_m"]), (2,90,1500))
        self.assertEqual(row["time_quality"], {"valid":2,"missing":0,"invalid":0})

    def test_distance_rejects_boolean_and_preserves_zero(self):
        self.assertIsNone(nonnegative_number(True))
        self.assertEqual(nonnegative_number("0"),0)

    def test_legacy_record_can_omit_new_quality_but_not_changed_metrics(self):
        from scripts.report_demo_comparison import recorded_comparison_matches
        old={"baseline":{"avg_trip_time_seconds":90}}
        fresh={"baseline":{"avg_trip_time_seconds":90, "time_valid_count":1, "data_quality":{}}}
        self.assertTrue(recorded_comparison_matches(old, fresh))
        fresh["baseline"]["avg_trip_time_seconds"]=45
        self.assertFalse(recorded_comparison_matches(old, fresh))
        self.assertFalse(recorded_comparison_matches({}, fresh))

    def test_replay_recomputes_legacy_comparison_without_rewriting_it(self):
        import shutil
        self.summary([self.row("90", "1000"), self.row("", "")])
        (self.directory / "output_config.xml").write_text("<config/>")
        shutil.copytree(self.directory, self.output / "base_sim")
        folder=self.output / "ifline" / "fixture"
        folder.mkdir(parents=True)
        record={"baseline_run":"base_sim", "comparison":{"scenario_name":"Original", "baseline":{"avg_trip_time_seconds":45}}}
        path=folder/"scenario.json"
        path.write_text(json.dumps(record))
        original=path.read_bytes()
        with patch.object(runs, "OUTPUT_DIR", self.output):
            payload=runs.result_payload("fixture_sim")
        self.assertEqual(payload["ifline_comparison"]["baseline"]["avg_trip_time_seconds"],90)
        self.assertEqual(payload["ifline_comparison"]["scenario_name"],"Original")
        self.assertEqual(path.read_bytes(),original)

    def test_report_export_handles_null_measurements(self):
        from scripts.report_demo_comparison import export_report
        result=self.summary([self.row("", "")])
        evidence={"baseline_run":"a", "proposal_run":"b", "comparison":compare_summaries(result,result), "limitations":[]}
        destination=self.output/"report"
        export_report(evidence,destination)
        self.assertIn("Unavailable",(destination/"README.md").read_text())


if __name__ == "__main__":
    unittest.main()
