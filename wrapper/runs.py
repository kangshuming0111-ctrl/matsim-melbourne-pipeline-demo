"""Discovery and loading of completed MATSim runs.

The output directory is intentionally machine-local and can contain dozens of
large demo runs.  This module gives the UI a stable, read-only catalogue so a
user can reopen an existing result without spending another 20 minutes rerunning
the pipeline.
"""

from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from wrapper.analyze import compute_summary_data

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
SAFE_RUN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
REQUIRED_RESULT_FILES = (
    "output_config.xml",
    "output_trips.csv.gz",
    "output_persons.csv.gz",
    "scorestats.txt",
)


def validate_run_name(name: str) -> str:
    if not SAFE_RUN_NAME.fullmatch(name) or ".." in name:
        raise ValueError("Invalid run name")
    return name


def _directory_size(path: Path) -> int:
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
    except OSError:
        pass
    return total


def _metadata(path: Path) -> dict:
    metadata_path = path / "run_metadata.json"
    if not metadata_path.is_file():
        return {}
    try:
        data = json.loads(metadata_path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _run_record(path: Path) -> dict:
    base_name = path.name[:-4] if path.name.endswith("_sim") else path.name
    record_path = OUTPUT_DIR / "run_records" / base_name / "run_manifest.json"
    if not record_path.is_file():
        return {}
    try:
        record = json.loads(record_path.read_text())
        return record if isinstance(record, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _ifline_record(path: Path) -> dict:
    base_name = path.name[:-4] if path.name.endswith("_sim") else path.name
    scenario_path = OUTPUT_DIR / "ifline" / base_name / "scenario.json"
    if not scenario_path.is_file():
        return {}
    try:
        scenario = json.loads(scenario_path.read_text())
        return scenario if isinstance(scenario, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _display_name(path: Path, metadata: dict) -> str:
    if metadata.get("region_label"):
        return f"{metadata['region_label']} · {path.name}"
    match = re.fullmatch(r"demo_(\d+)_sim", path.name)
    if match:
        try:
            dt = datetime.fromtimestamp(int(match.group(1))).astimezone()
            return f"墨尔本仿真 · {dt:%Y-%m-%d %H:%M}"
        except (ValueError, OSError, OverflowError):
            pass
    return path.name


def list_runs(limit: int = 50) -> list[dict]:
    if not OUTPUT_DIR.is_dir():
        return []
    candidates = [p for p in OUTPUT_DIR.iterdir() if p.is_dir() and p.name.endswith("_sim")]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    runs = []
    for path in candidates[:max(1, min(limit, 200))]:
        missing = [name for name in REQUIRED_RESULT_FILES if not (path / name).is_file()]
        record = _run_record(path)
        metadata = record or _metadata(path)
        profile = record.get("profile", {}) if record else {}
        configuration = record.get("configuration", {}) if record else {}
        display_metadata = {
            **metadata,
            "region_label": profile.get("label", metadata.get("region_label")),
        }
        recorded_failure = bool(record) and record.get("status") != "completed"
        ifline = _ifline_record(path)
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        runs.append({
            "id": path.name,
            "label": _display_name(path, display_metadata),
            "status": "completed" if not missing and not recorded_failure else "incomplete",
            "modified_at": modified,
            "size_bytes": _directory_size(path),
            "has_3d_scene": (path / "skyline_scene.json").is_file(),
            "missing_files": missing,
            "region_key": configuration.get("region_key", metadata.get("region_key")),
            "region_label": profile.get("label", metadata.get("region_label")),
            "record_status": record.get("status") if record else None,
            "has_run_record": bool(record),
            "is_ifline": bool(ifline),
            "baseline_run": ifline.get("baseline_run"),
        })
    return runs


def result_payload(run_name: str) -> dict:
    run_name = validate_run_name(run_name)
    run_dir = OUTPUT_DIR / run_name
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run '{run_name}' does not exist")
    missing = [name for name in REQUIRED_RESULT_FILES if not (run_dir / name).is_file()]
    record = _run_record(run_dir)
    if record and record.get("status") != "completed":
        raise FileNotFoundError(
            f"Run '{run_name}' has a record status of {record.get('status')!r}, not completed"
        )
    if missing:
        raise FileNotFoundError(f"Run '{run_name}' is incomplete; missing: {', '.join(missing)}")

    summary = compute_summary_data(run_name)
    summary["modestats_chart_url"] = (
        f"/results/{run_name}/modestats.png" if (run_dir / "modestats.png").is_file() else None
    )
    summary["scorestats_chart_url"] = (
        f"/results/{run_name}/scorestats.png" if (run_dir / "scorestats.png").is_file() else None
    )
    scene = run_dir / "skyline_scene.json"
    summary["skyline_scene_url"] = f"/results/{run_name}/skyline_scene.json" if scene.is_file() else None
    # Recorded runs use one stable base ID across the job, manifest and UI.
    # The simulation directory adds ``_sim`` only as a storage suffix.
    summary["run_id"] = record.get("run_id", run_name) if record else run_name
    summary["sim_output_subdir"] = run_name
    ifline = _ifline_record(run_dir)
    summary["result_source"] = "existing_ifline_replay" if ifline else "existing_replay"
    if ifline:
        difference_scene = run_dir / "ifline_scene.json"
        if difference_scene.is_file():
            scene = difference_scene
            summary["skyline_scene_url"] = f"/results/{run_name}/ifline_scene.json"
        base_name = run_name[:-4] if run_name.endswith("_sim") else run_name
        summary["ifline_scenario_url"] = f"/results/ifline/{base_name}/scenario.json"
        comparison = ifline.get("comparison")
        if isinstance(comparison, dict):
            summary["recorded_ifline_comparison"] = comparison
            # Recompute summary metrics for replay; never overwrite historical evidence.
            # Import locally because ifline uses this module's catalogue helpers.
            from wrapper.ifline import compare_summaries
            try:
                baseline_name = validate_run_name(ifline.get("baseline_run", ""))
                baseline_record = _run_record(OUTPUT_DIR / baseline_name)
                if baseline_record and baseline_record.get("status") != "completed":
                    raise ValueError("Baseline is not completed")
                current = compare_summaries(compute_summary_data(baseline_name), summary)
            except (OSError, ValueError, KeyError, TypeError) as error:
                summary["comparison_unavailable_reason"] = f"Unable to recompute baseline summary: {error}"
            else:
                summary["ifline_comparison"] = {**comparison, **current}
                summary["ifline_comparison"]["summary_source"] = "Current raw trip tables, summary schema v2; recorded network evidence retained"
            summary["ifline_comparison_url"] = f"/results/ifline/{base_name}/comparison.json"
    refreshed = refreshed_landmark_scene(scene)
    if refreshed:
        scene = refreshed
        summary["skyline_scene_url"] = f"/results/{run_name}/{refreshed.name}"
        summary["visualization_note"] = "地块显示已更新；交通数据仍为这次已有运行的结果"
    buildings = refreshed_building_scene(scene)
    if buildings:
        summary["skyline_scene_url"] = f"/results/{run_name}/{buildings.name}"
        summary["visualization_note"] = "建筑显示已更新；交通数据仍为这次已有运行的结果"
    if record:
        base_name = run_name[:-4] if run_name.endswith("_sim") else run_name
        summary["run_record_url"] = f"/results/run_records/{base_name}/run_manifest.json"
        summary["profile_id"] = record.get("profile", {}).get("id")
        summary["validation_status"] = record.get("profile", {}).get("validation_status")
    return summary


def refreshed_landmark_scene(source: Path) -> Path | None:
    """Only use an explicit sidecar paired to the exact current scene bytes.

    Never use an old baseline sidecar for a new IF Line result. A stale or
    incomplete visualization refresh cannot turn a failed run into success.
    """
    candidate = source.with_name(source.stem + '.landuse-v2.json')
    if not source.is_file() or not candidate.is_file():
        return None
    try:
        data = json.loads(candidate.read_text())
        record = data.get('landmark_refresh', {})
        if (data.get('landmark_geometry_version') == 2
                and all(key in data for key in ('roads', 'terrain', 'landmarks'))
                and record.get('source_file') == source.name
                and record.get('source_sha256') == hashlib.sha256(source.read_bytes()).hexdigest()):
            return candidate
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def refreshed_building_scene(source: Path) -> Path | None:
    candidate = source.with_name(source.stem + '.buildings-v1.json')
    if not source.is_file() or not candidate.is_file():
        return None
    try:
        data = json.loads(candidate.read_text())
        record = data.get('building_refresh', {})
        if (data.get('building_geometry_version') == 1
                and all(key in data for key in ('roads','terrain','landmarks'))
                and record.get('source_file') == source.name
                and record.get('source_sha256') == hashlib.sha256(source.read_bytes()).hexdigest()):
            return candidate
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None
