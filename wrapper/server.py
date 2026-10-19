"""Local web launcher with durable logs, independent of the launching terminal.

Reuses a healthy instance; never stops a server or retries a simulation. A new
instance is reported ready only when its own PID answers the health endpoint.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from wrapper.process_logging import announce

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "http://127.0.0.1:8000"
SERVICE_ID = "matsim-unified-framework"
SERVICE_LOG = PROJECT_ROOT / "output" / "service_logs" / "web.log"


def probe_server() -> dict | None:
    """Read-only liveness, without Docker checks or proxying localhost traffic."""
    try:
        with build_opener(ProxyHandler({})).open(BASE_URL + "/health", timeout=1) as response:
            data = json.load(response)
        if (isinstance(data, dict) and data.get("service") == SERVICE_ID
                and isinstance(data.get("pid"), int) and data["pid"] > 0):
            return data
    except (OSError, URLError, ValueError):
        pass
    return None


def spawn_detached(command: list[str], *, log_path: Path,
                   cwd: Path) -> subprocess.Popen:
    """No inherited terminal, stdin, stdout or stderr; file append is intentional."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab", buffering=0) as stream:
        stream.write(f"\n{datetime.now(timezone.utc).isoformat()} | Starting web service\n".encode())
        return subprocess.Popen(
            command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stream,
            stderr=subprocess.STDOUT, start_new_session=True, close_fds=True,
        )


def start_server(*, timeout: float = 20) -> int:
    existing = probe_server()
    if existing:
        return existing["pid"]
    process = spawn_detached(
        [sys.executable, "-u", "-m", "uvicorn", "wrapper.api:app",
         "--host", "127.0.0.1", "--port", "8000"],
        log_path=SERVICE_LOG, cwd=PROJECT_ROOT,
    )
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            returncode = process.poll()
            if returncode is not None:
                raise RuntimeError(f"Web service exited ({returncode}). See {SERVICE_LOG}")
            status = probe_server()
            if status and status["pid"] == process.pid:
                return process.pid
            time.sleep(0.2)
        raise RuntimeError(f"Web service did not become ready. See {SERVICE_LOG}")
    except BaseException:
        # Only clean up the process THIS invocation started. Never touch the
        # owner of an occupied port, a stale PID file, or an existing busy server.
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        pid = start_server()
    except (OSError, RuntimeError) as exc:
        announce(f"启动失败：{exc}")
        return 1
    announce(f"MATSim 网页服务已就绪（PID {pid}）：{BASE_URL}/")
    announce(f"服务日志：{SERVICE_LOG}")
    announce("可以关闭此终端窗口；服务会继续运行。关闭网页不会取消正在运行的任务。")
    if not args.no_browser:
        webbrowser.open(BASE_URL + "/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
