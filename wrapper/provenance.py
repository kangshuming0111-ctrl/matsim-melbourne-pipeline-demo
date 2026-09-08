"""Durable, privacy-conscious records for one-click MATSim runs.

The record intentionally captures versions, file fingerprints and paths, but
never dumps environment variables, host names, user names or file contents.
It is evidence for reproducibility and debugging, not a replacement for the
native network, demand and MATSim logs.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
RUN_RECORDS_DIR = OUTPUT_DIR / "run_records"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _command_text(args: list[str], timeout: int = 8) -> str | None:
    try:
        proc = subprocess.run(
            args,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _project_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return path.name


def _sanitized(text: str) -> str:
    return text.replace(str(PROJECT_ROOT), ".")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def file_evidence(path: Path, *, checksum: bool = False) -> dict[str, Any]:
    """Return metadata that identifies a file without exposing its contents."""
    item: dict[str, Any] = {"path": _project_path(path), "exists": path.is_file()}
    if not path.is_file():
        return item
    stat = path.stat()
    item.update({
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    })
    if checksum:
        item["sha256"] = sha256_file(path)
    return item


def code_snapshot() -> dict[str, Any]:
    commit = _command_text(["git", "rev-parse", "HEAD"])
    branch = _command_text(["git", "branch", "--show-current"])
    status = _command_text(["git", "status", "--porcelain=v1"]) or ""
    changed_files = []
    for line in status.splitlines():
        # Keep only repository-relative paths.  No diff or file content is
        # stored, and no host/user identity is collected.
        relative = line[3:].strip()
        if " -> " in relative:
            relative = relative.split(" -> ", 1)[1]
        changed_files.append(relative)
    return {
        "git_commit": commit,
        "git_branch": branch,
        "working_tree_dirty": bool(changed_files),
        "changed_files": changed_files,
    }


def environment_snapshot() -> dict[str, Any]:
    dependency_files = [
        PROJECT_ROOT / "requirements.txt",
        PROJECT_ROOT / "docker" / "network.Dockerfile",
        PROJECT_ROOT / "docker" / "demand.Dockerfile",
        PROJECT_ROOT / "docker" / "baseline.Dockerfile",
        PROJECT_ROOT / "vendor" / "network" / "renv.lock",
        PROJECT_ROOT / "vendor" / "demand" / "renv.lock",
        PROJECT_ROOT / "vendor" / "baseline" / "pom.xml",
    ]
    docker_server = _command_text(["docker", "version", "--format", "{{.Server.Version}}"])
    docker_info = _command_text(
        ["docker", "info", "--format", "{{.NCPU}}|{{.MemTotal}}"], timeout=10
    )
    docker_resources: dict[str, Any] | None = None
    if docker_info:
        try:
            cpus, memory = docker_info.split("|", 1)
            docker_resources = {
                "cpus": int(cpus),
                "memory_bytes": int(memory),
            }
        except ValueError:
            docker_resources = {"reported": docker_info}

    image_ids = {}
    for image in ("matsim-network-generator", "matsim-demand-generator", "matsim-baseline"):
        image_ids[image] = _command_text(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image]
        )

    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "operating_system": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "docker_server_version": docker_server,
        "docker_resources": docker_resources,
        "docker_images": image_ids,
        "dependency_files": [
            file_evidence(path, checksum=True) for path in dependency_files if path.is_file()
        ],
    }


class RunRecorder:
    """Atomically maintain one run manifest plus a concise pipeline log."""

    def __init__(
        self,
        run_id: str,
        *,
        job_id: str | None,
        profile: dict[str, Any],
        configuration: dict[str, Any],
        inputs: dict[str, Any],
        outputs: dict[str, str],
        random_seeds: dict[str, int | None],
        output_dir: Path = OUTPUT_DIR,
    ) -> None:
        self.run_id = run_id
        self.output_dir = output_dir
        self.record_dir = output_dir / "run_records" / run_id
        self.record_dir.mkdir(parents=True, exist_ok=False)
        self.manifest_path = self.record_dir / "run_manifest.json"
        self.log_path = self.record_dir / "pipeline.log"
        self.data: dict[str, Any] = {
            "schema_version": 1,
            "run_id": run_id,
            "job_id": job_id,
            "status": "running",
            "stage": "initializing",
            "started_at": utc_now(),
            "finished_at": None,
            "code": code_snapshot(),
            "environment": environment_snapshot(),
            "profile": profile,
            "configuration": configuration,
            "random_seeds": random_seeds,
            "inputs": inputs,
            "outputs": outputs,
            "logs": {
                "pipeline": _project_path(self.log_path),
                "network": f"output/{run_id}_network/makeMatsimNetwork.log",
                "demand": f"output/{run_id}_demand/makeExamplePopulation.log",
                "simulation": f"output/{run_id}_sim/logfile.log",
            },
            "steps": [],
            "artifacts": {},
            "verification": None,
            "error": None,
        }
        self._write()
        self.log("Run record created")

    def _write(self) -> None:
        temporary = self.manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, default=str))
        temporary.replace(self.manifest_path)

    def log(self, message: str) -> None:
        with self.log_path.open("a") as stream:
            stream.write(f"{utc_now()} | {message}\n")

    def stage(self, name: str, status: str, detail: str | None = None) -> None:
        now = utc_now()
        existing = next((row for row in self.data["steps"] if row["name"] == name), None)
        if existing is None:
            existing = {"name": name, "started_at": now, "finished_at": None}
            self.data["steps"].append(existing)
        existing["status"] = status
        if detail:
            existing["detail"] = detail
        if status in {"completed", "failed"}:
            existing["finished_at"] = now
        self.data["stage"] = name
        self._write()
        self.log(f"{name}: {status}" + (f" - {detail}" if detail else ""))

    def add_input(self, key: str, evidence: dict[str, Any]) -> None:
        self.data["inputs"][key] = evidence
        self._write()

    def set_artifacts(self, artifacts: dict[str, Any]) -> None:
        self.data["artifacts"] = artifacts
        # Images may have been built after the initial snapshot.
        self.data["environment"] = environment_snapshot()
        self._write()

    def complete(self, verification: dict[str, Any]) -> None:
        finished_at = utc_now()
        duration_seconds = (
            datetime.fromisoformat(finished_at)
            - datetime.fromisoformat(self.data["started_at"])
        ).total_seconds()
        self.data.update({
            "status": "completed",
            "stage": "completed",
            "finished_at": finished_at,
            "duration_seconds": round(duration_seconds, 3),
            "verification": verification,
            "error": None,
        })
        self._write()
        self.log("Run completed and required artifacts verified")

    def fail(self, exc: BaseException) -> None:
        now = utc_now()
        duration_seconds = (
            datetime.fromisoformat(now)
            - datetime.fromisoformat(self.data["started_at"])
        ).total_seconds()
        self.data.update({
            "status": "failed",
            "stage": self.data.get("stage") or "failed",
            "finished_at": now,
            "duration_seconds": round(duration_seconds, 3),
            "verification": {"passed": False},
            "error": {"type": type(exc).__name__, "message": _sanitized(str(exc))},
        })
        for step in reversed(self.data["steps"]):
            if step.get("status") == "running":
                step.update({"status": "failed", "finished_at": now})
                break
        self._write()
        self.log("Run failed\n" + _sanitized(traceback.format_exc()))
