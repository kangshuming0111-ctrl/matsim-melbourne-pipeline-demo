import unittest

from fastapi import HTTPException

from wrapper.api import PipelineRequest, _validate_number, _validate_output_name, start_pipeline


class ApiValidationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
