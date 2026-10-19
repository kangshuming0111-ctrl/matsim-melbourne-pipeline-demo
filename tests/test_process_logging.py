import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wrapper import process_logging as processes


class ProcessLoggingTests(unittest.TestCase):
    def test_both_streams_are_saved_and_repeated_attempts_append(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "logs" / "console.log"
            command = [sys.executable, "-c", "import sys; print('stdout-marker'); print('stderr-marker', file=sys.stderr)"]
            for _ in range(2):
                processes.run_logged(command, log_path=log)
            content = log.read_text()
        self.assertEqual(content.count("stdout-marker"), 2)
        self.assertEqual(content.count("stderr-marker"), 2)
        self.assertEqual(content.count("returncode=0"), 2)

    def test_closed_parent_pipes_cannot_kill_child_or_progress_reporting(self):
        # A real OS pipe whose reader is gone: this reproduces the stale service
        # descriptors without Docker, simulation data, or a live web server.
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "child.log"
            script = (
                "from pathlib import Path; import sys; "
                "from wrapper.process_logging import announce, run_logged; "
                "announce('parent progress'); "
                "run_logged([sys.executable, '-c', "
                "\"import sys; print('child stdout'); print('child stderr', file=sys.stderr)\"], "
                "log_path=Path(sys.argv[1]))"
            )
            read_fd, write_fd = os.pipe()
            os.close(read_fd)
            try:
                result = subprocess.run(
                    [sys.executable, "-c", script, str(log)],
                    cwd=Path(__file__).resolve().parents[1],
                    stdin=subprocess.DEVNULL, stdout=write_fd, stderr=write_fd,
                    timeout=10,
                )
            finally:
                os.close(write_fd)
            self.assertEqual(result.returncode, 0)
            self.assertIn("child stdout", log.read_text())
            self.assertIn("child stderr", log.read_text())

    def test_failure_preserves_output_exit_code_and_log_path(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "failure.log"
            with self.assertRaises(processes.ExternalProcessError) as caught:
                processes.run_logged(
                    [sys.executable, "-c", "print('before failure'); raise SystemExit(7)"],
                    log_path=log,
                )
            self.assertEqual(caught.exception.returncode, 7)
            self.assertIn(str(log.resolve()), str(caught.exception))
            self.assertIn("before failure", log.read_text())
            self.assertIn("returncode=7", log.read_text())

    def test_signal_failure_is_not_silently_successful(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "signal.log"
            with self.assertRaises(processes.ExternalProcessError) as caught:
                processes.run_logged(
                    [sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"],
                    log_path=log,
                )
        self.assertEqual(caught.exception.returncode, -signal.SIGTERM)

    def test_unavailable_command_reports_log_location(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "start.log"
            with self.assertRaisesRegex(OSError, "console log"):
                processes.run_logged([str(Path(directory) / "no-such-program")], log_path=log)
            self.assertIn("Could not start process", log.read_text())

    def test_unwritable_log_prevents_work_from_starting(self):
        with tempfile.TemporaryDirectory() as directory:
            # A directory used as a file fails even when tests run as root.
            with patch.object(processes.subprocess, "run") as run:
                with self.assertRaises(OSError):
                    processes.run_logged(["must-not-run"], log_path=Path(directory))
                run.assert_not_called()

    def test_log_name_cannot_escape_the_log_directory(self):
        for name in ("", ".", "../elsewhere", "/elsewhere"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                processes.process_log_path(Path("output"), name)

    def test_file_io_contract_and_no_sensitive_argv_in_log_header(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "contract.log"

            def fake_run(command, **kwargs):
                self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
                self.assertEqual(kwargs["stderr"], subprocess.STDOUT)
                self.assertFalse(kwargs["check"])
                self.assertTrue(kwargs["stdout"].writable())
                self.assertEqual(Path(kwargs["stdout"].name), log.resolve())
                return subprocess.CompletedProcess(command, 0)

            with patch.object(processes.subprocess, "run", side_effect=fake_run):
                processes.run_logged(["example", "sensitive-test-argument"], log_path=log)
            self.assertNotIn("sensitive-test-argument", log.read_text())


if __name__ == "__main__":
    unittest.main()
