"""Turns raw MATSim output (output_trips.csv.gz, output_persons.csv.gz,
scorestats.txt) into a plain-language summary. Pure standard library
(gzip/csv/statistics) - no pandas/matplotlib, no Docker, runs instantly on
files `simulate` already wrote to output/.

compute_summary_data() returns structured data (used by the web UI to
render its own HTML); summarize() builds the markdown report on top of it
(used by the CLI) so both stay in sync with a single source of truth.
"""

import csv
import gzip
from pathlib import Path

from wrapper.measurements import measurement_stats, nonnegative_number, parse_time, trip_mode

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"


# Kept as an alias for callers; unavailable measurements now return None.
_parse_hms = parse_time


def _format_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "无有效数据"
    if seconds < 60:
        return f"{seconds:g} 秒"
    minutes = seconds / 60
    return f"{minutes:.1f} 分钟" if minutes < 60 else f"{minutes / 60:.1f} 小时"


def _read_trips(sim_dir: Path) -> list[dict]:
    path = sim_dir / "output_trips.csv.gz"
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def _read_person_count(sim_dir: Path) -> int:
    path = sim_dir / "output_persons.csv.gz"
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
        return sum(1 for _ in csv.DictReader(f, delimiter=";"))


def _read_scorestats(sim_dir: Path) -> list[tuple]:
    path = sim_dir / "scorestats.txt"
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append((int(row["ITERATION"]), float(row["avg. EXECUTED"])))
    return rows


def compute_summary_data(sim_output_subdir: str) -> dict:
    sim_dir = OUTPUT_DIR / sim_output_subdir
    trips = _read_trips(sim_dir)
    person_count = _read_person_count(sim_dir)
    score_rows = _read_scorestats(sim_dir)

    by_mode: dict[str, list[dict]] = {}
    mode_quality = {"unknown": 0, "fallback": 0}
    for trip in trips:
        mode, fallback = trip_mode(trip)
        mode_quality["unknown"] += mode is None
        mode_quality["fallback"] += fallback
        mode = mode or "(未知)"
        by_mode.setdefault(mode, []).append(trip)

    total_trips = len(trips)
    mode_rows = []
    for mode, rows in sorted(by_mode.items(), key=lambda kv: -len(kv[1])):
        share = len(rows) / total_trips if total_trips else 0
        avg_time, time_quality = measurement_stats((r.get("trav_time") for r in rows), parse_time)
        avg_dist, distance_quality = measurement_stats((r.get("traveled_distance") for r in rows), nonnegative_number)
        mode_rows.append({
            "mode": mode,
            "count": len(rows),
            "share": share,
            "avg_time_seconds": avg_time,
            "avg_time_label": _format_seconds(avg_time),
            "avg_distance_m": avg_dist,
            "time_quality": time_quality,
            "distance_quality": distance_quality,
        })

    first_iter, first_score = score_rows[0]
    last_iter, last_score = score_rows[-1]

    return {
        "summary_schema_version": 2,
        "measurement_policy": "Available finite nonnegative measurements only; missing/invalid excluded separately per metric; real zero retained; empty means null.",
        "mode_basis": "main_mode, otherwise a single recognized modes value; ambiguous/unsupported modes counted as unknown",
        "units": {"avg_time_seconds": "seconds", "avg_distance_m": "metres"},
        "data_quality": {
            "time": {key: sum(row["time_quality"][key] for row in mode_rows) for key in ("valid", "missing", "invalid")},
            "distance": {key: sum(row["distance_quality"][key] for row in mode_rows) for key in ("valid", "missing", "invalid")},
            "mode": mode_quality,
        },
        "sim_output_subdir": sim_output_subdir,
        "sim_dir": str(sim_dir),
        "person_count": person_count,
        "total_trips": total_trips,
        "first_iteration": first_iter,
        "last_iteration": last_iter,
        "num_iterations": len(score_rows),
        "first_score": first_score,
        "last_score": last_score,
        "mode_rows": mode_rows,
        "modestats_chart": str(sim_dir / "modestats.png"),
        "scorestats_chart": str(sim_dir / "scorestats.png"),
    }


def summarize(sim_output_subdir: str) -> Path:
    data = compute_summary_data(sim_output_subdir)

    score_delta = data["last_score"] - data["first_score"]
    trend = "略有提升" if score_delta > 0.01 else "基本持平" if abs(score_delta) < 0.01 else "略有下降"

    lines = []
    lines.append(f"# 仿真结果摘要 — {sim_output_subdir}")
    lines.append("")
    lines.append("## 总览")
    lines.append(f"- 总人数：{data['person_count']}")
    lines.append(f"- 总出行次数：{data['total_trips']}")
    lines.append(f"- 仿真轮数：第 {data['first_iteration']} 轮到第 {data['last_iteration']} 轮，共 {data['num_iterations']} 轮")
    lines.append(f"- 平均得分：{data['first_score']:.1f} → {data['last_score']:.1f}"
                 f"（{trend}，轮数少，不代表长期收敛趋势）")
    lines.append("")
    lines.append("## 出行方式占比")
    lines.append("")
    lines.append("均值按各指标有效记录计算；缺失和非法值不计为零。有效/缺失/非法数量分别列出。")
    lines.append("| 方式 | 次数 | 占比 | 平均耗时 | 平均距离 | 时间有效/缺失/非法 | 距离有效/缺失/非法 |")
    lines.append("|---|---|---|---|---|---|---|")
    for row in data["mode_rows"]:
        distance = "无有效数据" if row["avg_distance_m"] is None else f"{row['avg_distance_m']:.0f} 米"
        counts = ["/".join(str(row[field][key]) for key in ("valid", "missing", "invalid")) for field in ("time_quality", "distance_quality")]
        lines.append(f"| {row['mode']} | {row['count']} | {row['share']:.1%} | {row['avg_time_label']} | {distance} | {counts[0]} | {counts[1]} |")
    lines.append("")
    lines.append("## 图表")
    lines.append("")
    lines.append("MATSim 自己生成了这些图表，可以直接打开看：")
    lines.append(f"- `{data['modestats_chart']}` — 出行方式占比随迭代轮数的变化")
    lines.append(f"- `{data['scorestats_chart']}` — 平均得分随迭代轮数的变化")
    lines.append("")

    content = "\n".join(lines)
    summary_path = OUTPUT_DIR / sim_output_subdir / "summary.md"
    summary_path.write_text(content, encoding="utf-8")
    return summary_path
