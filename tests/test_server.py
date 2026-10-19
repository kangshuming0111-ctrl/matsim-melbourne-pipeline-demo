import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from wrapper import server


class ServerLauncherTests(unittest.TestCase):
    def test_healthy_instance_is_reused_without_starting_or_stopping_anything(self):
        with patch.object(server, "probe_server", return_value={"pid": 4321}), \
                patch.object(server, "spawn_detached") as spawn:
            self.assertEqual(server.start_server(), 4321)
            spawn.assert_not_called()

    def test_waits_for_own_pid_not_another_server(self):
        child = Mock(pid=1234)
        child.poll.return_value = None
        with patch.object(server, "probe_server", side_effect=[None, {"pid": 99}, {"pid": 1234}]), \
                patch.object(server, "spawn_detached", return_value=child), \
                patch.object(server.time, "sleep"):
            self.assertEqual(server.start_server(), 1234)
        child.terminate.assert_not_called()

    def test_startup_failure_does_not_claim_success(self):
        child = Mock(pid=1234)
        child.poll.return_value = 1
        with patch.object(server, "probe_server", return_value=None), \
                patch.object(server, "spawn_detached", return_value=child):
            with self.assertRaisesRegex(RuntimeError, "exited.*1"):
                server.start_server()
        child.terminate.assert_not_called()

    def test_timeout_cleans_up_only_child_it_started(self):
        child = Mock(pid=1234)
        child.poll.return_value = None
        with patch.object(server, "probe_server", return_value=None), \
                patch.object(server, "spawn_detached", return_value=child):
            with self.assertRaisesRegex(RuntimeError, "did not become ready"):
                server.start_server(timeout=0)
        child.terminate.assert_called_once()
        child.wait.assert_called_once_with(timeout=5)

    def test_spawn_actually_detaches_and_redirects_stdio(self):
        # Harmless real child, not uvicorn. It reports its own descriptors and
        # session so this checks the OS behavior as well as Popen arguments.
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "web.log"
            child = server.spawn_detached(
                [sys.executable, "-c", (
                    "import os, stat, json, sys; "
                    "print(json.dumps({'pid': os.getpid(), 'session': os.getsid(0), "
                    "'stdin_eof': os.read(0, 1) == b'', "
                    "'regular_stdout': stat.S_ISREG(os.fstat(1).st_mode), "
                    "'regular_stderr': stat.S_ISREG(os.fstat(2).st_mode)})); "
                    "print('stderr-marker', file=sys.stderr)"
                )], log_path=log, cwd=Path(directory),
            )
            self.assertEqual(child.wait(timeout=10), 0)
            lines = log.read_text().splitlines()
            data = json.loads(next(line for line in lines if line.startswith("{")))
        self.assertEqual(data["pid"], data["session"])
        self.assertNotEqual(data["session"], os.getsid(0))
        self.assertTrue(data["stdin_eof"])
        self.assertTrue(data["regular_stdout"])
        self.assertTrue(data["regular_stderr"])
        self.assertIn("stderr-marker", lines)

    def test_invalid_health_response_is_not_our_server(self):
        for data in ({"service": "other", "pid": 42}, [], {"service": server.SERVICE_ID}):
            with self.subTest(data=data):
                response = Mock()
                response.read.return_value = json.dumps(data).encode()
                context = Mock()
                context.__enter__ = Mock(return_value=response)
                context.__exit__ = Mock(return_value=False)
                opener = Mock()
                opener.open.return_value = context
                with patch.object(server, "build_opener", return_value=opener):
                    self.assertIsNone(server.probe_server())


if __name__ == "__main__":
    unittest.main()
