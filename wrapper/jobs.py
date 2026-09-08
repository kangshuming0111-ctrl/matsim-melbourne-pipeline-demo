"""Simple in-memory background job manager for the API. Jobs run one at a
time (max_workers=1) - network/demand/simulate Docker containers already use
a lot of memory (16-32GB), so running several concurrently risks exhausting
the host rather than actually finishing faster.
"""

import json
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Optional

_executor = ThreadPoolExecutor(max_workers=1)
_jobs: dict[str, "Job"] = {}
_lock = RLock()
_history_path = Path(__file__).resolve().parent.parent / "output" / ".job_history.json"


@dataclass
class Job:
    id: str
    run_id: Optional[str] = None
    status: str = "pending"  # pending -> running -> completed | failed
    stage: Optional[str] = None  # human-readable "which step is it on" for slow multi-step jobs
    result: Any = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save() -> None:
    """Persist a small bounded history so refreshes/server restarts do not
    make completed jobs disappear.  Output files remain the real source of
    truth; this is UI state, not simulation data."""
    _history_path.parent.mkdir(exist_ok=True)
    rows = [asdict(job) for job in sorted(
        _jobs.values(), key=lambda item: item.created_at, reverse=True
    )[:100]]
    temp = _history_path.with_suffix(".tmp")
    temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
    temp.replace(_history_path)


def _load() -> None:
    if not _history_path.is_file():
        return
    try:
        rows = json.loads(_history_path.read_text())
        for row in rows:
            job = Job(**{key: row.get(key) for key in Job.__dataclass_fields__})
            if job.status in {"pending", "running"}:
                job.status = "failed"
                job.error = "服务曾在任务完成前关闭。请检查 output/ 中是否已有部分结果，然后重新运行。"
                job.finished_at = _now()
            _jobs[job.id] = job
    except (OSError, json.JSONDecodeError, TypeError):
        # A damaged optional history file must never prevent the app starting.
        _jobs.clear()


_load()


def new_job_id() -> str:
    """Reserve a job_id before the job function itself is constructed - lets
    a long-running function (e.g. run_full_pipeline) know its own id upfront
    so it can call set_stage() as it progresses."""
    return str(uuid.uuid4())


def submit_with_id(
    job_id: str,
    fn: Callable,
    *args,
    run_id: Optional[str] = None,
    **kwargs,
) -> str:
    job = Job(id=job_id, run_id=run_id)
    with _lock:
        _jobs[job_id] = job
        _save()

    _executor.submit(_execute, job, fn, args, kwargs, run_id)
    return job_id


def _execute(
    job: Job,
    fn: Callable,
    args: tuple,
    kwargs: dict,
    expected_run_id: Optional[str],
) -> None:
    """Execute one job. Kept separate so failure semantics are unit-testable."""
    with _lock:
        job.status = "running"
        job.started_at = _now()
        _save()
    try:
        result = fn(*args, **kwargs)
        if expected_run_id is not None:
            if not isinstance(result, dict) or result.get("run_id") != expected_run_id:
                raise RuntimeError(
                    f"Job result does not belong to expected run '{expected_run_id}'"
                )
        with _lock:
            job.result = result
            job.status = "completed"
            job.finished_at = _now()
            _save()
    except Exception:
        with _lock:
            job.result = None
            job.error = traceback.format_exc()
            job.status = "failed"
            job.finished_at = _now()
            _save()


def submit(fn: Callable, *args, **kwargs) -> str:
    return submit_with_id(new_job_id(), fn, *args, **kwargs)


def set_stage(job_id: str, stage: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.stage = stage
            _save()


def get(job_id: str) -> Optional[Job]:
    with _lock:
        return _jobs.get(job_id)


def list_recent(limit: int = 20) -> list[Job]:
    with _lock:
        return sorted(_jobs.values(), key=lambda item: item.created_at, reverse=True)[:limit]
