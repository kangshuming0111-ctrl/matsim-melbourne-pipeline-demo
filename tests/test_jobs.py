import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wrapper import jobs


class JobHistoryTests(unittest.TestCase):
    def test_history_survives_reload_and_marks_interrupted_job(self):
        with tempfile.TemporaryDirectory() as raw_dir:
            history = Path(raw_dir) / "jobs.json"
            current = jobs.Job(id="finished", status="completed", result={"ok": True})
            interrupted = jobs.Job(id="interrupted", status="running")
            with patch.object(jobs, "_history_path", history), patch.object(
                jobs, "_jobs", {current.id: current, interrupted.id: interrupted}
            ) as temporary_jobs:
                jobs._save()
                temporary_jobs.clear()
                jobs._load()

                self.assertEqual(temporary_jobs["finished"].status, "completed")
                self.assertEqual(temporary_jobs["finished"].result, {"ok": True})
                self.assertEqual(temporary_jobs["interrupted"].status, "failed")
                self.assertIn("服务曾在任务完成前关闭", temporary_jobs["interrupted"].error)

    def test_failed_job_never_retains_a_result(self):
        job = jobs.Job(id="failed", run_id="run-1")

        def explode():
            raise RuntimeError("external program failed")

        with patch.object(jobs, "_save"):
            jobs._execute(job, explode, (), {}, "run-1")

        self.assertEqual(job.status, "failed")
        self.assertIsNone(job.result)
        self.assertIn("external program failed", job.error)

    def test_job_rejects_result_from_another_run(self):
        job = jobs.Job(id="mismatch", run_id="expected-run")

        with patch.object(jobs, "_save"):
            jobs._execute(
                job,
                lambda: {"run_id": "old-run", "person_count": 1003},
                (),
                {},
                "expected-run",
            )

        self.assertEqual(job.status, "failed")
        self.assertIsNone(job.result)
        self.assertIn("does not belong to expected run", job.error)


if __name__ == "__main__":
    unittest.main()
