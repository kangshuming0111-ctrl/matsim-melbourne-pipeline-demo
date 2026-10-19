import unittest
import os
from unittest.mock import patch

from fastapi import HTTPException

from wrapper.api import (
    IfLineInterventionRequest,
    IfLineRequest,
    PipelineRequest,
    _validate_number,
    _validate_output_name,
    start_ifline,
    start_pipeline,
    health,
)


class ApiValidationTests(unittest.TestCase):
    def test_health_probe_is_read_only_and_identifies_process(self):
        with patch("wrapper.api.check_system") as check_system, \
                patch("wrapper.api.submit_with_id") as submit:
            self.assertEqual(health(), {"service": "matsim-unified-framework", "pid": os.getpid()})
        check_system.assert_not_called()
        submit.assert_not_called()

    def test_accepts_normal_output_name(self):
        self.assertEqual(_validate_output_name("scenario-01_sim"), "scenario-01_sim")

    def test_rejects_parent_path(self):
        with self.assertRaises(HTTPException):
            _validate_output_name("../outside")

    def test_rejects_shell_like_name(self):
        with self.assertRaises(HTTPException):
            _validate_output_name("result;shutdown")

    def test_rejects_invalid_numeric_range(self):
        with self.assertRaises(HTTPException):
            _validate_number(0, "num_plans", 1, 1000)

    def test_rejects_unknown_pipeline_region_before_starting_job(self):
        with self.assertRaises(HTTPException):
            start_pipeline(PipelineRequest(region="greater_melbourne"))

    def test_ifline_rejects_unknown_intervention_before_queueing(self):
        request = IfLineRequest(
            baseline_run="baseline_sim",
            name="Invalid branch",
            intervention=IfLineInterventionRequest(
                type="magic_road", link_id="1", value=10,
            ),
        )
        with patch("wrapper.api.resolve_run_assets", return_value={}), \
                patch("wrapper.api.submit_with_id") as submit:
            with self.assertRaises(HTTPException) as raised:
                start_ifline(request)
        self.assertEqual(raised.exception.status_code, 400)
        submit.assert_not_called()

    def test_ifline_allocates_one_expected_run_id(self):
        request = IfLineRequest(
            baseline_run="baseline_sim",
            name="30 km/h test",
            intervention=IfLineInterventionRequest(
                type="speed_limit", link_id="1", value=30,
            ),
        )
        with patch("wrapper.api.resolve_run_assets", return_value={}), \
                patch("wrapper.api.ifline_network_map", return_value={"links": [{"id": "1"}]}), \
                patch("wrapper.api.new_scenario_id", return_value="if_test"), \
                patch("wrapper.api.new_job_id", return_value="job_test"), \
                patch("wrapper.api.submit_with_id", return_value="job_test") as submit:
            result = start_ifline(request)
        self.assertEqual(result, {"job_id": "job_test", "run_id": "if_test"})
        self.assertEqual(submit.call_args.kwargs["run_id"], "if_test")

    def test_ifline_new_road_does_not_require_an_existing_link_id(self):
        request = IfLineRequest(
            baseline_run="baseline_sim",
            name="User-drawn connector",
            intervention=IfLineInterventionRequest(
                type="new_road",
                points=[[0, 0], [100, 25], [200, 0]],
                speed_kph=45,
                lanes=2,
                capacity_per_hour=1600,
                snap_tolerance_m=80,
            ),
        )
        with patch("wrapper.api.resolve_run_assets", return_value={}), \
                patch("wrapper.api.ifline_network_map") as network_map, \
                patch("wrapper.api.new_scenario_id", return_value="if_new_road"), \
                patch("wrapper.api.new_job_id", return_value="job_new_road"), \
                patch("wrapper.api.submit_with_id", return_value="job_new_road") as submit:
            result = start_ifline(request)
        self.assertEqual(result, {"job_id": "job_new_road", "run_id": "if_new_road"})
        network_map.assert_not_called()
        self.assertEqual(submit.call_args.kwargs["run_id"], "if_new_road")


if __name__ == "__main__":
    unittest.main()
