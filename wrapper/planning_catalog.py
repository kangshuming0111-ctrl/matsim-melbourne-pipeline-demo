"""Read-only catalogue of locally recorded planning experiments, never a runner."""
import hashlib
import json
import math
from pathlib import Path

from wrapper.ifline import OUTPUT_DIR as OUTPUT, resolve_run_assets

_STAGES = ("baseline", "closure", "alternative")
_STATUSES = {"prepared", "preparing", "running", "completed", "failed", "interrupted", "not_started"}
_DATA_ERRORS = (OSError, ValueError, KeyError, TypeError, RuntimeError, OverflowError)
_COMPARISONS = {"closure_vs_baseline", "alternative_vs_baseline", "alternative_vs_closure"}


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _list(value, label):
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _seeds(value, label):
    values = _list(value, label)
    for seed in values:
        _integer(seed, label)
    if len(set(values)) != len(values):
        raise ValueError(f"{label} contains duplicate seeds")
    return values


def _status(value):
    if not isinstance(value, str) or value not in _STATUSES:
        raise ValueError("Unknown case or attempt status")
    return value


def _inside(path, root):
    path = Path(path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Case evidence is outside its permitted directory")
    return path


def _evidence_path(evidence, root):
    _object(evidence, "File evidence")
    if not isinstance(evidence["path"], str) or not evidence["path"]:
        raise ValueError("File evidence must identify a path")
    checksum = evidence["sha256"]
    if not isinstance(checksum, str) or len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
        raise ValueError("File evidence must contain a SHA-256 checksum")
    return _inside(OUTPUT.parent / evidence["path"], root)


def _invalid_constant(value):
    raise ValueError(f"Non-finite JSON constant: {value}")


def _json_object(payload, label):
    return _object(json.loads(payload, parse_constant=_invalid_constant), label)


def _read_evidence(case_dir, evidence):
    path = _evidence_path(evidence, case_dir)
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != evidence["sha256"]:
        raise ValueError("Case evidence checksum mismatch")
    return _json_object(payload, "Case evidence")


def _file_stamp(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _verify_file(evidence, expected, hashes):
    """Hash control sources only; request-local caching never skips a new stat."""
    path = _evidence_path(evidence, OUTPUT)
    if path != _inside(expected, OUTPUT):
        raise ValueError("Control evidence path does not match the resolved run source")
    stamp = _file_stamp(path)
    key = (path, stamp)
    if key not in hashes:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if _file_stamp(path) != stamp:
            raise ValueError("Control source changed while being verified")
        hashes[key] = digest.hexdigest()
    if hashes[key] != evidence["sha256"]:
        raise ValueError("Control source checksum mismatch")
    return hashes[key]


def _verify_run(*, spec, seed, name, latest, result, hashes):
    run_id = latest["run_id"]
    if result["run_id"] != run_id or result["seed"] != seed or result["stage"] != name:
        raise ValueError("Completed attempt identity mismatch")
    run = f"{run_id}_sim"
    assets = _object(resolve_run_assets(run), "Resolved run")
    record = _object(assets["record"], "Run record")
    config = _object(record["configuration"], "Run configuration")
    seeds = _object(record["random_seeds"], "Run random seeds")
    last = _integer(spec.get("last_iteration", spec["total_iterations"] - 1), "last_iteration")
    if last + 1 != spec["total_iterations"]:
        raise ValueError("Case iteration range and total disagree")
    if (assets["run_name"] != run or assets["run_id"] != run_id or record["run_id"] != run_id
            or record["status"] != "completed"):
        raise ValueError("Resolved run identity or completion status mismatch")
    controls = ((assets["matsim_seed"], seed), (seeds["matsim"], seed),
                (assets["last_iteration"], last), (config["matsim_last_iteration"], last),
                (config["matsim_first_iteration"], 0), (result["last_iteration"], last))
    if any(type(actual) is not int or actual != expected for actual, expected in controls):
        raise ValueError("Resolved run seed/iteration controls mismatch")
    files = _object(result["files"], "Completed source files")
    expected_files = {"plans": assets["plans_file"], "network": assets["network_file"],
                      "run_record": assets["record_path"], "output_config.xml": Path(assets["sim_dir"]) / "output_config.xml"}
    verified = {key: _verify_file(files[key], path, hashes) for key, path in expected_files.items()}
    inputs = _object(spec["inputs"], "Case inputs")
    plans = inputs["plans_file"]
    _verify_file(plans, _evidence_path(plans, OUTPUT), hashes)
    if verified["plans"] != plans["sha256"]:
        raise ValueError("Completed stage population differs from the frozen case plans")
    if name == "baseline":
        network = inputs["network_file"]
        _verify_file(network, _evidence_path(network, OUTPUT), hashes)
        if verified["network"] != network["sha256"]:
            raise ValueError("Baseline network differs from the frozen case network")
    return run


def _aggregate(case_dir, manifest, rows):
    """A bad/stale aggregate cannot revoke independently verified stage links."""
    try:
        if not manifest.get("aggregate"):
            raise ValueError("Aggregate has not been published or is unavailable")
        aggregate = _read_evidence(case_dir, manifest["aggregate"])
        expected = [row["seed"] for row in rows]
        completed = [row["seed"] for row in rows if all(stage["run"] for stage in row["stages"].values())]
        incomplete = [seed for seed in expected if seed not in completed]
        for key, value in (("expected_seeds", expected), ("completed_seeds", completed), ("incomplete_seeds", incomplete)):
            if _seeds(aggregate[key], key) != value:
                raise ValueError(f"Aggregate {key} does not match verified stages")
        paired = _list(aggregate["paired_results"], "Aggregate paired_results")
        if _seeds([_object(row, "Aggregate paired row")["seed"] for row in paired], "Aggregate paired row seeds") != completed:
            raise ValueError("Aggregate paired rows do not match verified completed seeds")
        ranges = _object(aggregate["descriptive_ranges"], "Aggregate descriptive_ranges")
        if set(ranges) != (_COMPARISONS if completed else set()):
            raise ValueError("Aggregate comparison groups do not match completed groups")
        for group in ranges.values():
            _object(group, "Aggregate comparison")
            if "car_mean_travel_time_s" not in group:
                raise ValueError("Aggregate car measurement is missing")
            for measurement in group.values():
                _object(measurement, "Aggregate measurement")
                n = _integer(measurement["n"], "Aggregate n")
                missing = _integer(measurement["missing"], "Aggregate missing")
                if n + missing != len(completed):
                    raise ValueError("Aggregate observed/missing counts do not match completed groups")
                values = [measurement[key] for key in ("min", "max", "mean", "median")]
                if (n == 0 and any(value is not None for value in values)) or (n > 0 and any(
                        type(value) not in (float, int) or not math.isfinite(value) for value in values)):
                    raise ValueError("Aggregate missing/non-finite measurements must not be represented as observations")
        return aggregate, None
    except _DATA_ERRORS as error:
        return None, str(error)


def _verification(rows):
    verified = sum(stage["controls_verified"] for row in rows for stage in row["stages"].values())
    expected = len(rows) * len(_STAGES)
    return {"scope": "completed_stage_metadata_and_control_source_hashes",
            "verified_stage_count": verified, "expected_stage_count": expected,
            "not_checked": ["normalized_config_comparability", "trip_event_data_quality",
                            "aggregate_metric_recomputation", "calibration"]}


def planning_cases(limit=20):
    """Read-only snapshots; controls_verified is limited to the declared scope.

    No trip/event scans or simulations. Workbench remains responsible for actual
    pair comparability. Aggregate failures are separate from stage availability.
    """
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("limit must be an integer from 1 to 50")
    root = OUTPUT / "planning_cases"
    paths = []
    for path in root.glob("*/case_manifest.json"):
        try:
            paths.append((path.stat().st_mtime, path, None))
        except OSError as error:
            paths.append((float("-inf"), path, str(error)))
    paths.sort(key=lambda item: (-item[0], str(item[1])))
    cases = []
    hashes = {}
    for _, path, stat_error in paths[:limit]:
        directory = path.parent
        try:
            if stat_error is not None:
                raise ValueError(f"Cannot stat case manifest: {stat_error}")
            _inside(directory, root)
            manifest = _json_object(_inside(path, directory).read_bytes(), "Case manifest")
            spec_bytes = _inside(directory / "case_spec.json", directory).read_bytes()
            if hashlib.sha256(spec_bytes).hexdigest() != manifest.get("spec_sha256"):
                raise ValueError("Case specification checksum mismatch")
            spec = _json_object(spec_bytes, "Case specification")
            if manifest["case_id"] != directory.name or spec["case_id"] != directory.name:
                raise ValueError("Case identity mismatch")
            _status(manifest["status"])
            _integer(spec["population_count"], "population_count", 1)
            _integer(spec["total_iterations"], "total_iterations", 1)
            for count in _object(spec["conflict_count"], "Conflict counts").values():
                _integer(count, "Conflict count")
            for name in ("closure", "alternative"):
                _integer(spec["conflict_count"][name], "Conflict count")
            _object(spec.get("geometry", {}), "Case geometry")
            raw_rows = _list(manifest["rows"], "Case rows")
            seeds = _seeds([_object(row, "Case seed row")["seed"] for row in raw_rows], "Case seed rows")
            if "seeds" in spec and seeds != _seeds(spec["seeds"], "Case specification seeds"):
                raise ValueError("Case seed rows do not match its specification")
            rows = []
            for row in raw_rows:
                stages = {}
                raw_stages = _object(row["stages"], "Case stages")
                for name in _STAGES:
                    attempts = _list(_object(raw_stages[name], "Case stage")["attempts"], "Stage attempts")
                    latest = _object(attempts[-1], "Latest attempt") if attempts else None
                    status = _status(latest["status"]) if latest is not None else "not_started"
                    run = None
                    if status == "completed":
                        result = _read_evidence(directory, latest["result"])
                        run = _verify_run(spec=spec, seed=row["seed"], name=name,
                                          latest=latest, result=result, hashes=hashes)
                    stages[name] = {"status": status, "run": run, "controls_verified": run is not None}
                rows.append({"seed": row["seed"], "stages": stages})
            if manifest["status"] == "completed" and (
                not rows or any(not s["run"] for row in rows for s in row["stages"].values())
            ):
                raise ValueError("Completed case is missing verified completed stages")
            aggregate, aggregate_error = _aggregate(directory, manifest, rows)
            verification = _verification(rows)
            cases.append({"id": directory.name, "status": manifest["status"],
                          "started_at": manifest.get("started_at"), "finished_at": manifest.get("finished_at"),
                          "population_count": spec["population_count"], "total_iterations": spec["total_iterations"],
                          "rows": rows, "aggregate": aggregate, "aggregate_error": aggregate_error,
                          "controls_verified": bool(rows) and verification["verified_stage_count"] == verification["expected_stage_count"],
                          "controls_verification": verification, "limitations": spec["limitations"],
                          "conflict_count": spec["conflict_count"],
                          "region": spec.get("region_key"), "scope": spec.get("scope"),
                          "geometry": {key: spec.get("geometry", {}).get(key) for key in
                                       ("alternative_length_m", "alternative_route", "closure_links")},
                          "record_url": f"/results/planning_cases/{directory.name}/case_manifest.json"})
        except _DATA_ERRORS as error:
            cases.append({"id": directory.name, "status": "unavailable", "error": str(error), "rows": [],
                          "aggregate": None, "aggregate_error": "Case evidence could not be verified",
                          "controls_verified": False, "controls_verification": _verification([])})
    return {"cases": cases}
