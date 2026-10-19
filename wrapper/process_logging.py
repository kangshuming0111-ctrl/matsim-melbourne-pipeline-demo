"""Durable console output for external stages; never inherit a terminal pipe.

Logs live outside generator-owned directories (which R may recreate and MATSim
expects not to exist). Appending keeps earlier attempts rather than erasing them.
This module owns process I/O only, not retries, job state or simulation policy.
"""

from __future__ import annotations

import errno
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


def announce(message: str) -> None:
    """Best-effort CLI progress. A closed console must not fail a background job.

    Use an unbuffered write, so a failed flush cannot reappear at interpreter exit.
    Authoritative child output and failures are always retained in the log file.
    """
    pending = (message + "\n").encode("utf-8", errors="replace")
    while pending:
        try:
            pending = pending[os.write(1, pending):]
        except OSError as exc:
            if exc.errno in {errno.EPIPE, errno.EBADF, errno.EIO}:
                return
            raise


def process_log_path(output_dir: Path, name: str) -> Path:
    relative = Path(name)
    if not name or relative.is_absolute() or ".." in relative.parts or name == ".":
        raise ValueError("Process log name must be a relative output name")
    return output_dir / "process_logs" / f"{name}.log"


class ExternalProcessError(subprocess.CalledProcessError):
    def __init__(self, returncode: int, cmd: Sequence[str], log_path: Path):
        super().__init__(returncode, cmd)
        self.log_path = log_path

    def __str__(self) -> str:
        reason = (f"signal {-self.returncode}" if self.returncode < 0
                  else f"exit code {self.returncode}")
        # Don't echo the full argv or environment (which might contain secrets).
        return f"External process failed ({reason}). Console log: {self.log_path}"


def run_logged(command: Sequence[str], *, log_path: Path,
               cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run synchronously with explicit file-backed stdout/stderr and closed stdin.

    Opening the log must succeed before starting work. Nonzero exit codes still
    raise; callers cannot accidentally mark an unsuccessful stage as completed.
    """
    log_path = log_path.resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab", buffering=0) as stream:
        def record(message: str) -> None:
            stamp = datetime.now(timezone.utc).isoformat()
            stream.write(f"\n{stamp} | {message}\n".encode("utf-8"))

        record("External process started")
        announce(f"External process console log: {log_path}")
        try:
            result = subprocess.run(
                command, cwd=cwd, stdin=subprocess.DEVNULL,
                stdout=stream, stderr=subprocess.STDOUT, check=False,
            )
        except OSError as exc:
            record(f"Could not start process: {type(exc).__name__} (errno={exc.errno})")
            raise OSError(f"Could not start external process; console log: {log_path}") from exc
        record(f"External process finished: returncode={result.returncode}")
        if result.returncode != 0:
            raise ExternalProcessError(result.returncode, command, log_path)
        return result
