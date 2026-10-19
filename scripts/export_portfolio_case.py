"""Export reviewed aggregate results without running MATSim or exporting trip rows."""
import argparse
import csv
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from wrapper.analyze import compute_summary_data
from wrapper.planning_catalog import planning_cases

ROOT=Path(__file__).resolve().parents[1]
CASE="cbd_expanded1037_detour_10it_review_r02"

def digest(path):
    with path.open("rb") as stream:
        result=hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            result.update(chunk)
        return result.hexdigest()

def export(destination):
    if destination.exists():
        raise FileExistsError("Choose a new export directory; existing evidence is preserved")
    case=next(item for item in planning_cases()["cases"] if item["id"]==CASE)
    if not case["controls_verified"] or case["status"]!="completed":
        raise ValueError("The featured case does not have verified completed controls")
    rows=[]
    for seed in (4711,4712,4713):
        for scenario in ("baseline","closure","alternative"):
            run=f"{CASE}_s{seed}_{scenario}_a01_sim"
            summary=compute_summary_data(run)
            car=next(row for row in summary["mode_rows"] if row["mode"]=="car")
            if (summary["person_count"],summary["total_trips"],summary["num_iterations"],car["count"]) != (1037,3623,10,934):
                raise ValueError(f"Unexpected featured-case counts: {run}")
            rows.append({"seed":seed,"scenario":scenario,"run":run,
                         "persons":summary["person_count"],"trips":summary["total_trips"],
                         "iterations":summary["num_iterations"],"car_trips":car["count"],
                         "car_mean_seconds":car["avg_time_seconds"],
                         "car_mean_distance_m":car["avg_distance_m"],
                         "car_time_quality":car["time_quality"],
                         "car_distance_quality":car["distance_quality"],
                         "all_trip_quality":summary["data_quality"],
                         "artifact_sha256":{name:digest(ROOT/"output"/run/name) for name in
                            ("output_trips.csv.gz","output_persons.csv.gz","scorestats.txt")}})
    differences=[]
    for seed in (4711,4712,4713):
        group={row["scenario"]:row["car_mean_seconds"] for row in rows if row["seed"]==seed}
        differences.append({"seed":seed,
            "closure_minus_baseline_s":group["closure"]-group["baseline"],
            "alternative_minus_baseline_s":group["alternative"]-group["baseline"],
            "alternative_minus_closure_s":group["alternative"]-group["closure"]})
    data={"release":"2026.10-p0","case_id":CASE,"exported_at_utc":datetime.now(timezone.utc).isoformat(),
          "scope":"Recomputed from nine saved native trip tables; no new simulation or real-traffic calibration",
          "metric":"Arithmetic mean of valid car-trip durations in seconds; each seed weighted equally in the descriptive mean difference",
          "measurement_policy":"Finite nonnegative measurements only; real zero valid; missing/invalid excluded separately per metric; all missing means null",
          "controls_verification":case["controls_verification"],"runs":rows,"differences":differences,
          "descriptive_mean_differences":{key:statistics.mean(row[key] for row in differences) for key in differences[0] if key!="seed"},
          "limitations":["Synthetic agents; not observed individual travel", "No observed-traffic calibration or predictive accuracy claim",
                         "Teleported public transport, not GTFS vehicles/timetables", "Three seeds are descriptive, not confidence intervals or convergence evidence",
                         "The same people recur across seeds; do not treat them as independent samples", "Bounding-box coverage is not connectivity or transport validity"],
          "analysis_source_sha256":{str(path.relative_to(ROOT)):digest(path) for path in
              [ROOT/"wrapper/analyze.py",ROOT/"wrapper/measurements.py",Path(__file__)]}}
    destination.mkdir(parents=True)
    (destination/"case.json").write_text(json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")
    fields=["seed","scenario","run","persons","trips","iterations","car_trips","car_mean_seconds","car_mean_distance_m"]
    with (destination/"case.csv").open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)
    return data

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination",type=Path,required=True)
    args=parser.parse_args()
    result=export(args.destination)
    print(json.dumps({"runs":len(result["runs"]),"differences":result["descriptive_mean_differences"]},indent=2))
