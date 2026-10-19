"""Read-only impact/coverage HTTP contracts, using ASGI without httpx or a server."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

from wrapper import api


class ImpactApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # A regression must fail before allocating a job, persisting history,
        # invoking a simulator, or submitting work to the real executor.
        self.side_effect_guards = []
        targets = [
            "wrapper.api.submit", "wrapper.api.submit_with_id", "wrapper.api.new_job_id",
            "wrapper.api.run_network", "wrapper.api.run_demand", "wrapper.api.run_simulation",
            "wrapper.api.run_scenario", "wrapper.api.run_full_pipeline", "wrapper.api.run_ifline_scenario",
            "wrapper.jobs.submit", "wrapper.jobs.submit_with_id", "wrapper.jobs._executor.submit",
            "wrapper.jobs._save",
        ]
        for target in targets:
            guard = patch(target, side_effect=AssertionError(f"Read-only request called {target}"))
            mocked = guard.start()
            self.addCleanup(guard.stop)
            self.side_effect_guards.append(mocked)

    def tearDown(self):
        for guard in self.side_effect_guards:
            guard.assert_not_called()

    async def request(self, path, params=None, method="GET"):
        """Exercise routing, query coercion, exception mapping, and JSON serialization."""
        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": method, "scheme": "http", "path": path,
            "raw_path": path.encode(), "root_path": "", "query_string": urlencode(params or {}).encode(),
            "headers": [(b"host", b"testserver")], "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
        messages = []
        sent_request = False
        finished = asyncio.Event()

        async def receive():
            nonlocal sent_request
            if not sent_request:
                sent_request = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await finished.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                finished.set()

        await api.app(scope, receive, send)
        status = next(message["status"] for message in messages if message["type"] == "http.response.start")
        self.response_headers = dict(next(message["headers"] for message in messages if message["type"] == "http.response.start"))
        body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        return status, json.loads(body)

    async def impact(self, **params):
        return await self.request("/ifline/impact", {"baseline": "baseline_sim", "proposal": "proposal_sim", **params})

    async def test_get_impact_defaults_and_nullable_payload_are_preserved(self):
        payload = {"schema_version": 1, "trips": {"paired_count": 0, "delta_s": {"mean": None}},
                   "network": {"links": [{"id": "road", "delta": {"mean_travel_time_s": None}}]}}
        with patch("wrapper.impact.analyze_impact", return_value=payload) as analyze:
            status, body = await self.impact()
        self.assertEqual(status, 200)
        self.assertEqual(body, payload)
        self.assertEqual(self.response_headers.get(b"cache-control"), b"no-store")
        analyze.assert_called_once_with("baseline_sim", "proposal_sim", start_s=0,
                                        end_s=108000, mode="car", link_ids=None)

    async def test_get_impact_passes_typed_window_mode_and_comma_selected_ids(self):
        with patch("wrapper.impact.analyze_impact", return_value={"ok": True}) as analyze:
            status, body = await self.impact(start_s="25200.5", end_s="32400", mode="bike", links="road:forward,road.reverse")
        self.assertEqual((status, body), (200, {"ok": True}))
        analyze.assert_called_once_with("baseline_sim", "proposal_sim", start_s=25200.5,
                                        end_s=32400.0, mode="bike", link_ids=["road:forward", "road.reverse"])

    async def test_native_json_response_skips_recursive_reencoding(self):
        payload = {"中文": "路段", "empty": None, "negative": -1.25,
                   "links": [{"id": "a", "value": None} for _ in range(2000)]}
        with patch("wrapper.impact.analyze_impact", return_value=payload), \
                patch("fastapi.routing.serialize_response", side_effect=AssertionError("Redundant conversion")):
            status, body = await self.impact()
        self.assertEqual((status, body), (200, payload))

    async def test_nonfinite_analysis_payload_is_rejected_not_published(self):
        with patch("wrapper.impact.analyze_impact", return_value={"invalid": float("nan")}):
            status, body = await self.impact()
        self.assertEqual(status, 400)
        self.assertIn("detail", body)

    async def test_all_supported_modes_and_empty_selection_reach_analysis_unchanged(self):
        for mode in ("car", "bike", "walk", "pt", "all"):
            with self.subTest(mode=mode), patch("wrapper.impact.analyze_impact", return_value={}) as analyze:
                status, _ = await self.impact(mode=mode, links="")
                self.assertEqual(status, 200)
                self.assertEqual(analyze.call_args.kwargs["mode"], mode)
                self.assertIsNone(analyze.call_args.kwargs["link_ids"])

    async def test_missing_required_pair_queries_are_422_before_analysis(self):
        with patch("wrapper.impact.analyze_impact") as analyze:
            for params, missing in (({}, {"baseline", "proposal"}),
                                    ({"baseline": "baseline_sim"}, {"proposal"}),
                                    ({"proposal": "proposal_sim"}, {"baseline"})):
                with self.subTest(params=params):
                    status, body = await self.request("/ifline/impact", params)
                    self.assertEqual(status, 422)
                    self.assertEqual({item["loc"][-1] for item in body["detail"]}, missing)
            analyze.assert_not_called()

    async def test_non_numeric_query_times_are_422_before_analysis(self):
        with patch("wrapper.impact.analyze_impact") as analyze:
            for field in ("start_s", "end_s"):
                with self.subTest(field=field):
                    status, body = await self.impact(**{field: "not-a-time"})
                    self.assertEqual(status, 422)
                    self.assertEqual(body["detail"][0]["loc"], ["query", field])
            analyze.assert_not_called()

    async def test_real_domain_validation_returns_400_before_asset_resolution(self):
        invalid = [
            {"start_s": -1}, {"start_s": 20, "end_s": 20}, {"start_s": 30, "end_s": 20},
            {"end_s": 172801}, {"start_s": "nan"}, {"end_s": "inf"}, {"end_s": "-inf"},
            {"mode": "rail"}, {"mode": ""}, {"links": "road,road"}, {"links": "road,"},
            {"links": ",road"}, {"links": ","}, {"links": ",".join(str(i) for i in range(101))},
        ]
        with patch("wrapper.impact.resolve_run_assets") as resolve:
            for params in invalid:
                with self.subTest(params=params):
                    status, body = await self.impact(**params)
                    self.assertEqual(status, 400)
                    self.assertIsInstance(body["detail"], str)
                    self.assertTrue(body["detail"])
            resolve.assert_not_called()

    async def test_invalid_impact_run_names_are_400_through_real_resolver(self):
        for name in ("../outside_sim", "bad;name_sim", "not_a_result", ""):
            with self.subTest(name=name):
                status, body = await self.impact(baseline=name)
                self.assertEqual(status, 400)
                self.assertIsInstance(body["detail"], str)

    async def test_impact_missing_artifacts_map_to_404_and_keep_message(self):
        with patch("wrapper.impact.analyze_impact", side_effect=FileNotFoundError("Required impact artifact missing: output_events.xml.gz")):
            status, body = await self.impact()
        self.assertEqual(status, 404)
        self.assertEqual(body, {"detail": "Required impact artifact missing: output_events.xml.gz"})

    async def test_impact_incomparable_unknown_links_and_shape_errors_map_to_400(self):
        errors = [ValueError("actual output configs differ"), ValueError("actual input plans SHA-256 differs"),
                  ValueError("Selected link IDs must exist in the baseline/proposal network union"),
                  KeyError("plans_file"), TypeError("invalid run evidence")]
        for error in errors:
            with self.subTest(error=error), patch("wrapper.impact.analyze_impact", side_effect=error):
                status, body = await self.impact()
                self.assertEqual(status, 400)
                self.assertEqual(body, {"detail": str(error)})

    async def test_get_coverage_resolves_requested_run_and_preserves_nulls(self):
        assets = {"network_file": Path("network.xml"), "plans_file": Path("plans.xml")}
        payload = {"activities": {"inside_node_bbox_fraction_of_finite": None, "outside_node_bbox": 0}}
        with patch("wrapper.api.resolve_run_assets", return_value=assets) as resolve, \
                patch("wrapper.coverage_audit.audit_coverage", return_value=payload) as audit:
            status, body = await self.request("/ifline/coverage/baseline_sim")
        self.assertEqual((status, body), (200, payload))
        resolve.assert_called_once_with("baseline_sim")
        audit.assert_called_once_with(assets["network_file"], assets["plans_file"])

    async def test_coverage_with_tiny_actual_xml_is_read_only_and_private(self):
        with tempfile.TemporaryDirectory() as directory:
            network = Path(directory) / "network.xml"
            plans = Path(directory) / "plans.xml"
            network.write_text('<network><nodes><node id="a" x="0" y="0"/><node id="b" x="100" y="100"/>'
                               '</nodes><links><link id="road" from="a" to="b" modes="car"/></links></network>')
            plans.write_text('<population><person id="DO-NOT-EXPOSE"><plan selected="yes">'
                             '<act type="Home" x="50" y="50"/><leg mode="car"/>'
                             '<act type="Work" x="200" y="200"/></plan></person></population>')
            before = {path.name: path.read_bytes() for path in Path(directory).iterdir()}
            with patch("wrapper.api.resolve_run_assets", return_value={"network_file": network, "plans_file": plans}):
                status, body = await self.request("/ifline/coverage/example_sim")
            self.assertEqual(status, 200)
            self.assertEqual(body["activities"]["inside_node_bbox_fraction_of_finite"], .5)
            self.assertEqual(body["activities"]["outside_node_bbox"], 1)
            self.assertNotIn("DO-NOT-EXPOSE", json.dumps(body, allow_nan=False))
            self.assertEqual(before, {path.name: path.read_bytes() for path in Path(directory).iterdir()})

    async def test_coverage_resolver_failures_stop_before_audit_and_map_status(self):
        for error, expected in ((ValueError("not completed"), 400), (FileNotFoundError("missing run"), 404),
                                (KeyError("network_file"), 400), (TypeError("invalid assets"), 400)):
            with self.subTest(error=error), patch("wrapper.api.resolve_run_assets", side_effect=error), \
                    patch("wrapper.coverage_audit.audit_coverage") as audit:
                status, body = await self.request("/ifline/coverage/example_sim")
                self.assertEqual((status, body), (expected, {"detail": str(error)}))
                audit.assert_not_called()

    async def test_coverage_audit_errors_map_400_or_404(self):
        assets = {"network_file": Path("network.xml"), "plans_file": Path("plans.xml")}
        for error, expected in ((ValueError("invalid XML"), 400), (FileNotFoundError("missing plans"), 404),
                                (KeyError("coordinates"), 400), (TypeError("invalid coordinates"), 400)):
            with self.subTest(error=error), patch("wrapper.api.resolve_run_assets", return_value=assets), \
                    patch("wrapper.coverage_audit.audit_coverage", side_effect=error):
                status, body = await self.request("/ifline/coverage/example_sim")
                self.assertEqual((status, body), (expected, {"detail": str(error)}))

    async def test_invalid_coverage_run_names_are_400_before_audit(self):
        with patch("wrapper.coverage_audit.audit_coverage") as audit:
            for name in ("bad..name_sim", "bad;name_sim", "not_a_result"):
                with self.subTest(name=name):
                    status, body = await self.request(f"/ifline/coverage/{name}")
                    self.assertEqual(status, 400)
                    self.assertIsInstance(body["detail"], str)
            audit.assert_not_called()

    async def test_get_only_routes_reject_post_without_calling_modules(self):
        with patch("wrapper.impact.analyze_impact") as analyze, patch("wrapper.coverage_audit.audit_coverage") as audit:
            for path in ("/ifline/impact", "/ifline/coverage/example_sim"):
                with self.subTest(path=path):
                    status, body = await self.request(path, method="POST")
                    self.assertEqual((status, body), (405, {"detail": "Method Not Allowed"}))
            analyze.assert_not_called()
            audit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
