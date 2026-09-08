"""Auditable one-click pipeline: matched inputs -> MATSim -> analysis -> 3D.

The CBD profile is the deliberately small, documented demonstration. Other
presets remain available as experimental regions, but they are not presented
as equivalent validation evidence until each has its own successful run record.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from wrapper.analyze import compute_summary_data, summarize
from wrapper.baseline_runner import run as run_simulation
from wrapper.jobs import set_stage
from wrapper.preflight import DEMAND_DATA_FILES, check_system
from wrapper.provenance import OUTPUT_DIR, RunRecorder, file_evidence
from wrapper.scenario import cross_check_coverage, run_scenario
from wrapper.skyline import render_skyline_scene

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

AVAILABLE_REGIONS = {
    "cbd": {
        "label": "墨尔本市中心 CBD",
        "file": "sample_region.geojson",
        "validation": "verified_demo",
    },
    "inner_north": {
        "label": "内城北区（实验）",
        "file": "region_inner_north.geojson",
        "validation": "experimental",
    },
    "inner_east": {
        "label": "内城东区（实验）",
        "file": "region_inner_east.geojson",
        "validation": "experimental",
    },
    "inner_south": {
        "label": "内城南区（实验）",
        "file": "region_inner_south.geojson",
        "validation": "experimental",
    },
    "inner_northeast": {
        "label": "内城东北区（实验）",
        "file": "region_inner_northeast.geojson",
        "validation": "experimental",
    },
    "inner_southeast": {
        "label": "内城东南区（实验）",
        "file": "region_inner_southeast.geojson",
        "validation": "experimental",
    },
}
DEFAULT_REGION_KEY = "cbd"

VERIFIED_DEMO_PROFILE_ID = "cbd_small_v1"
DEFAULT_SAMPLE_PERCENT = 5
DEFAULT_NUM_PLANS = 500
DEFAULT_BUFFER_DIST = 500
# MATSim's lastIteration is inclusive: 2 means iterations 0, 1 and 2.
DEFAULT_LAST_ITERATION = 2
DEFAULT_DEMAND_RANDOM_SEED = 4711
DEFAULT_MATSIM_RANDOM_SEED = 4711
VICTORIA_OSM_PBF = "geofabrik_victoria-latest.osm.pbf"


def new_run_name(region_key: str = DEFAULT_REGION_KEY) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{region_key}_demo_{stamp}_{uuid.uuid4().hex[:6]}"


def _input_snapshot(region_key: str) -> dict:
    region_file = AVAILABLE_REGIONS[region_key]["file"]
    return {
        "region_boundary": file_evidence(DATA_DIR / region_file, checksum=True),
        "demand_data": [file_evidence(DATA_DIR / relative) for relative in DEMAND_DATA_FILES],
        "osm_extract_cache": file_evidence(DATA_DIR / "geofabrik_victoria-latest.osm.pbf"),
        "terrain": file_evidence(DATA_DIR / "dem" / "fabdem_melbourne.tif"),
        "landmarks": file_evidence(DATA_DIR / "landmarks" / f"{region_key}.json"),
        "note": (
            "ABS/VISTA-derived inputs generate synthetic agents; they are not individual "
            "people or observed personal trajectories."
        ),
    }


def _artifacts(run_name: str) -> dict:
    paths = {
        "network_xml": OUTPUT_DIR / f"{run_name}_network" / "network.xml",
        "network_log": OUTPUT_DIR / f"{run_name}_network" / "makeMatsimNetwork.log",
        "sa1_subset": DATA_DIR / f"{run_name}_sa1_subset.csv",
        "plans_xml": OUTPUT_DIR / f"{run_name}_demand" / "8.xml" / "plan.xml",
        "demand_log": OUTPUT_DIR / f"{run_name}_demand" / "makeExamplePopulation.log",
        "generated_config": OUTPUT_DIR / f"{run_name}_sim_config" / "config.xml",
        "output_config": OUTPUT_DIR / f"{run_name}_sim" / "output_config.xml",
        "events": OUTPUT_DIR / f"{run_name}_sim" / "output_events.xml.gz",
        "persons": OUTPUT_DIR / f"{run_name}_sim" / "output_persons.csv.gz",
        "trips": OUTPUT_DIR / f"{run_name}_sim" / "output_trips.csv.gz",
        "scorestats": OUTPUT_DIR / f"{run_name}_sim" / "scorestats.txt",
        "simulation_log": OUTPUT_DIR / f"{run_name}_sim" / "logfile.log",
        "summary": OUTPUT_DIR / f"{run_name}_sim" / "summary.md",
        "mode_chart": OUTPUT_DIR / f"{run_name}_sim" / "modestats.png",
        "score_chart": OUTPUT_DIR / f"{run_name}_sim" / "scorestats.png",
        "scene": OUTPUT_DIR / f"{run_name}_sim" / "skyline_scene.json",
    }
    checksummed = {"sa1_subset", "generated_config"}
    return {
        key: file_evidence(path, checksum=key in checksummed)
        for key, path in paths.items()
    }


def _verify_completed_run(run_name: str, summary: dict, artifacts: dict) -> dict:
    missing = [
        key for key, item in artifacts.items()
        if not item.get("exists") or item.get("size_bytes", 0) <= 0
    ]
    if missing:
        raise RuntimeError("Required run artifacts are missing or empty: " + ", ".join(missing))

    expected_iterations = DEFAULT_LAST_ITERATION + 1
    if summary["person_count"] <= 0 or summary["total_trips"] <= 0:
        raise RuntimeError("Simulation produced no agents or trips")
    if summary["num_iterations"] != expected_iterations:
        raise RuntimeError(
            f"Expected {expected_iterations} score rows (iterations 0..{DEFAULT_LAST_ITERATION}), "
            f"found {summary['num_iterations']}"
        )

    sim_log = OUTPUT_DIR / f"{run_name}_sim" / "logfile.log"
    log_tail = sim_log.read_text(errors="replace")[-20_000:]
    if "shutdown completed" not in log_tail.lower():
        raise RuntimeError("MATSim log does not contain the successful shutdown marker")
    if "unexpectedly terminated" in log_tail.lower():
        raise RuntimeError("MATSim log contains an unexpected termination marker")

    return {
        "passed": True,
        "checks": {
            "required_artifacts_present": True,
            "positive_agent_count": summary["person_count"],
            "positive_trip_count": summary["total_trips"],
            "iteration_rows": summary["num_iterations"],
            "expected_iteration_rows": expected_iterations,
            "matsim_clean_shutdown": True,
        },
    }


def run_full_pipeline(
    region_key: str = DEFAULT_REGION_KEY,
    job_id: Optional[str] = None,
    run_name: Optional[str] = None,
) -> dict:
    if region_key not in AVAILABLE_REGIONS:
        raise ValueError(f"Unknown region_key '{region_key}'; available: {list(AVAILABLE_REGIONS)}")
    run_name = run_name or new_run_name(region_key)
    region = AVAILABLE_REGIONS[region_key]
    profile_id = (
        VERIFIED_DEMO_PROFILE_ID
        if region["validation"] == "verified_demo"
        else f"experimental_{region_key}_v1"
    )

    configuration = {
        "region_key": region_key,
        "region_file": region["file"],
        "osm_pbf_file": VICTORIA_OSM_PBF,
        "output_crs": 7899,
        "buffer_distance_m": DEFAULT_BUFFER_DIST,
        "sample_percent": DEFAULT_SAMPLE_PERCENT,
        "planned_num_plans": DEFAULT_NUM_PLANS,
        "planned_num_plans_semantics": (
            "Parameter passed to the upstream plan generator; it is not a hard cap on "
            "the final synthetic-agent count, which is data- and subset-dependent."
        ),
        "matsim_first_iteration": 0,
        "matsim_last_iteration": DEFAULT_LAST_ITERATION,
        "matsim_actual_iteration_count_expected": DEFAULT_LAST_ITERATION + 1,
        "public_transport_model": "teleported fixed-speed pt; no GTFS transit vehicles",
    }
    outputs = {
        "network": f"output/{run_name}_network",
        "demand": f"output/{run_name}_demand",
        "simulation": f"output/{run_name}_sim",
        "simulation_config": f"output/{run_name}_sim_config/config.xml",
        "run_record": f"output/run_records/{run_name}/run_manifest.json",
    }
    recorder = RunRecorder(
        run_name,
        job_id=job_id,
        profile={
            "id": profile_id,
            "label": region["label"],
            "validation_status": region["validation"],
        },
        configuration=configuration,
        inputs=_input_snapshot(region_key),
        outputs=outputs,
        random_seeds={
            "demand": DEFAULT_DEMAND_RANDOM_SEED,
            "matsim": DEFAULT_MATSIM_RANDOM_SEED,
        },
        output_dir=OUTPUT_DIR,
    )

    def ui_stage(text: str) -> None:
        if job_id:
            set_stage(job_id, text)

    try:
        ui_stage("生成路网和人口数据中...")
        recorder.stage("network_and_demand", "running")
        network_dir, demand_dir = run_scenario(
            region_file=region["file"],
            output_name=run_name,
            buffer_dist=DEFAULT_BUFFER_DIST,
            num_plans=DEFAULT_NUM_PLANS,
            sample_percent=DEFAULT_SAMPLE_PERCENT,
            demand_random_seed=DEFAULT_DEMAND_RANDOM_SEED,
            osm_pbf_file=VICTORIA_OSM_PBF,
        )
        coverage = cross_check_coverage(network_dir, demand_dir)
        recorder.add_input(
            "generated_sa1_subset",
            file_evidence(DATA_DIR / f"{run_name}_sa1_subset.csv", checksum=True),
        )
        recorder.stage(
            "network_and_demand",
            "completed",
            f"Bounding-box coverage check: {coverage:.1%}",
        )

        ui_stage("跑仿真中...")
        recorder.stage("simulation", "running")
        sim_dir = run_simulation(
            network_output_subdir=f"{run_name}_network",
            demand_output_subdir=f"{run_name}_demand",
            output_subdir=f"{run_name}_sim",
            last_iteration=DEFAULT_LAST_ITERATION,
            random_seed=DEFAULT_MATSIM_RANDOM_SEED,
        )
        recorder.stage("simulation", "completed")

        ui_stage("整理并核对结果中...")
        recorder.stage("analysis_and_visualization", "running")
        summarize(f"{run_name}_sim")
        summary = compute_summary_data(f"{run_name}_sim")
        render_skyline_scene(f"{run_name}_sim", region_key=region_key)
        artifacts = _artifacts(run_name)
        recorder.set_artifacts(artifacts)
        verification = _verify_completed_run(run_name, summary, artifacts)
        verification["checks"]["network_demand_bbox_coverage"] = round(coverage, 6)
        recorder.stage("analysis_and_visualization", "completed")
        recorder.complete(verification)

        # Keep a copy next to MATSim outputs for humans and the result browser.
        metadata_path = sim_dir / "run_metadata.json"
        metadata_path.write_text(recorder.manifest_path.read_text())

        summary.update({
            "run_id": run_name,
            "result_source": "new_run",
            "profile_id": profile_id,
            "validation_status": region["validation"],
            "run_record_path": outputs["run_record"],
            "run_record_url": f"/results/run_records/{run_name}/run_manifest.json",
            "modestats_chart_url": f"/results/{run_name}_sim/modestats.png",
            "scorestats_chart_url": f"/results/{run_name}_sim/scorestats.png",
            "skyline_scene_url": f"/results/{run_name}_sim/skyline_scene.json",
        })
        ui_stage("完成并通过产物核对")
        return summary
    except BaseException as exc:
        recorder.fail(exc)
        ui_stage("失败；已保存运行记录")
        raise


def run_verified_demo() -> dict:
    """Run only the fixed CBD profile after the same preflight used by the UI."""
    readiness = check_system()
    if not readiness["can_run_pipeline"]:
        blocked = [
            item["detail"] for item in readiness["checks"] if item["status"] == "blocked"
        ]
        raise RuntimeError("Environment is not ready: " + "; ".join(blocked))
    return run_full_pipeline(region_key=DEFAULT_REGION_KEY)
