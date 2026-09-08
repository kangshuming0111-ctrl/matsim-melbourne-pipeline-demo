"""HTTP API over the existing wrapper functions. Thin on purpose - every
endpoint just calls the same Python functions the CLI (cli.py) already uses;
no Docker/orchestration logic is duplicated here.

Run with: python3 -m uvicorn wrapper.api:app --reload
Then open http://127.0.0.1:8000/docs for interactive API docs.
"""

import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from wrapper.runner import NetworkRunConfig, run as run_network
from wrapper.demand_runner import DemandRunConfig, run as run_demand
from wrapper.scenario import run_scenario
from wrapper.baseline_runner import run as run_simulation
from wrapper.analyze import summarize
from wrapper.jobs import submit, submit_with_id, new_job_id, get as get_job, list_recent
from wrapper.pipeline import (
    run_full_pipeline,
    new_run_name,
    AVAILABLE_REGIONS,
    DEFAULT_REGION_KEY,
)
from wrapper.preflight import check_system
from wrapper.runs import list_runs, result_payload

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="MATSim unified framework API")

SAFE_OUTPUT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def _validate_output_name(value: str, field: str = "output") -> str:
    if not SAFE_OUTPUT_NAME.fullmatch(value) or ".." in value:
        raise HTTPException(
            status_code=400,
            detail=f"{field} 只能包含英文字母、数字、点、下划线和连字符",
        )
    return value


def _validate_data_file(value: str, field: str, suffixes: tuple[str, ...]) -> str:
    # Inputs are deliberately restricted to direct children of data/.  This
    # API is local today, but accepting ../../ paths would become dangerous as
    # soon as someone exposes it to a LAN or desktop webview.
    if Path(value).name != value or ".." in value or not value.lower().endswith(suffixes):
        raise HTTPException(status_code=400, detail=f"{field} 必须是 data/ 目录中的有效文件名")
    path = PROJECT_ROOT / "data" / value
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"找不到 {field}：data/{value}")
    return value


def _validate_number(value: float, field: str, minimum: float, maximum: float) -> float:
    if not minimum <= value <= maximum:
        raise HTTPException(status_code=400, detail=f"{field} 必须在 {minimum:g} 到 {maximum:g} 之间")
    return value

# Serves generated chart images etc. so the web UI can <img src="/results/...">
app.mount("/results", StaticFiles(directory=PROJECT_ROOT / "output"), name="results")

# Serves vendored JS libraries (three.js etc.) same-origin, so the 3D viewer
# doesn't depend on external CDNs being reachable.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class NetworkRequest(BaseModel):
    city: str
    region: str
    output: str = "generated_network"
    crs: int = 7899
    buffer_dist: int = 500


class DemandRequest(BaseModel):
    num_plans: int
    sample_percent: float = 0.1
    output: str = "demand_run1"
    sa1_subset: Optional[str] = None
    all_destinations: bool = False
    crs: int = 7899
    random_seed: Optional[int] = None


class ScenarioRequest(BaseModel):
    region: str
    output: str
    buffer_dist: int = 500
    num_plans: int = 500
    sample_percent: float = 0.1
    random_seed: Optional[int] = None


class SimulateRequest(BaseModel):
    network_output: str
    demand_output: str
    output: str
    iterations: int = 2
    random_seed: int = 4711


class AnalyzeRequest(BaseModel):
    sim_output: str


class PipelineRequest(BaseModel):
    region: str = DEFAULT_REGION_KEY


@app.post("/network")
def start_network(req: NetworkRequest):
    _validate_output_name(req.output)
    _validate_data_file(req.region, "region", (".geojson", ".sqlite", ".gpkg"))
    _validate_number(req.buffer_dist, "buffer_dist", 0, 50_000)
    config = NetworkRunConfig(
        city=req.city,
        region_file=req.region,
        output_subdir=req.output,
        output_crs=req.crs,
        region_buffer_dist=req.buffer_dist,
    )
    job_id = submit(lambda: str(run_network(config)))
    return {"job_id": job_id}


@app.post("/demand")
def start_demand(req: DemandRequest):
    _validate_output_name(req.output)
    if req.sa1_subset:
        _validate_data_file(req.sa1_subset, "sa1_subset", (".csv",))
    _validate_number(req.num_plans, "num_plans", 1, 1_000_000)
    _validate_number(req.sample_percent, "sample_percent", 0.001, 100)
    if req.random_seed is not None:
        _validate_number(req.random_seed, "random_seed", 0, 2_147_483_647)
    config = DemandRunConfig(
        sample_percent=req.sample_percent,
        num_plans=req.num_plans,
        output_subdir=req.output,
        sa1_subset_file=req.sa1_subset,
        all_destinations=req.all_destinations,
        output_crs=req.crs,
        random_seed=req.random_seed,
    )
    job_id = submit(lambda: str(run_demand(config)))
    return {"job_id": job_id}


@app.post("/scenario")
def start_scenario(req: ScenarioRequest):
    _validate_output_name(req.output)
    _validate_data_file(req.region, "region", (".geojson", ".sqlite", ".gpkg"))
    _validate_number(req.buffer_dist, "buffer_dist", 0, 50_000)
    _validate_number(req.num_plans, "num_plans", 1, 1_000_000)
    _validate_number(req.sample_percent, "sample_percent", 0.001, 100)
    if req.random_seed is not None:
        _validate_number(req.random_seed, "random_seed", 0, 2_147_483_647)
    def _run():
        network_dir, demand_dir = run_scenario(
            region_file=req.region,
            output_name=req.output,
            buffer_dist=req.buffer_dist,
            num_plans=req.num_plans,
            sample_percent=req.sample_percent,
            demand_random_seed=req.random_seed,
        )
        return {"network_output": str(network_dir), "demand_output": str(demand_dir)}

    job_id = submit(_run)
    return {"job_id": job_id}


@app.post("/simulate")
def start_simulate(req: SimulateRequest):
    _validate_output_name(req.network_output, "network_output")
    _validate_output_name(req.demand_output, "demand_output")
    _validate_output_name(req.output)
    _validate_number(req.iterations, "iterations", 0, 10_000)
    _validate_number(req.random_seed, "random_seed", 0, 2_147_483_647)
    job_id = submit(lambda: str(run_simulation(
        network_output_subdir=req.network_output,
        demand_output_subdir=req.demand_output,
        output_subdir=req.output,
        last_iteration=req.iterations,
        random_seed=req.random_seed,
    )))
    return {"job_id": job_id}


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    """Synchronous - this is pure stdlib post-processing of already-generated
    files, no Docker involved, so it doesn't need the job queue."""
    _validate_output_name(req.sim_output, "sim_output")
    try:
        summary_path = summarize(req.sim_output)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "summary_path": str(summary_path),
        "summary_markdown": summary_path.read_text(),
    }


@app.get("/system/status")
def system_status():
    """Read-only preflight check used by the UI before starting a long job."""
    return check_system()


@app.get("/runs")
def completed_runs(limit: int = 50):
    """Completed/incomplete MATSim simulation folders, newest first."""
    return {"runs": list_runs(limit=limit)}


@app.get("/runs/{run_name}")
def load_run(run_name: str):
    """Return the same result payload as a newly completed one-click job."""
    try:
        return result_payload(run_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/pipeline/regions")
def list_regions():
    """Preset regions the web UI can offer - single source of truth is
    wrapper/pipeline.py's AVAILABLE_REGIONS, not duplicated in the frontend."""
    return {
        "regions": [{
            "key": key,
            "label": info["label"],
            "validation": info["validation"],
        } for key, info in AVAILABLE_REGIONS.items()],
        "default": DEFAULT_REGION_KEY,
    }


@app.post("/pipeline/run")
def start_pipeline(req: PipelineRequest):
    """One-click endpoint for the web UI: chains scenario -> simulate ->
    analyze into a single job using validated defaults (see wrapper/pipeline.py)."""
    if req.region not in AVAILABLE_REGIONS:
        raise HTTPException(status_code=400, detail=f"Unknown region '{req.region}'")
    readiness = check_system()
    if not readiness["can_run_pipeline"]:
        blocked = [item["detail"] for item in readiness["checks"] if item["status"] == "blocked"]
        raise HTTPException(status_code=503, detail="当前环境不能运行：" + "；".join(blocked))
    job_id = new_job_id()
    run_id = new_run_name(req.region)
    submit_with_id(
        job_id,
        lambda: run_full_pipeline(region_key=req.region, job_id=job_id, run_name=run_id),
        run_id=run_id,
    )
    return {"job_id": job_id, "run_id": run_id}


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return {
        "job_id": job.id,
        "run_id": job.run_id,
        "status": job.status,
        "stage": job.stage,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "result": job.result,
        "error": job.error,
    }


@app.get("/jobs")
def recent_jobs(limit: int = 20):
    return {"jobs": [{
        "job_id": job.id,
        "run_id": job.run_id,
        "status": job.status,
        "stage": job.stage,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error,
    } for job in list_recent(limit=max(1, min(limit, 100)))]}


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text()
