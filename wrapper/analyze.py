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
import statistics
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"


def _parse_hms(value: str) -> float:
    """'00:40:59' -> seconds. Returns 0 for empty/malformed values."""
    parts = value.split(":")
    if len(parts) != 3:
        return 0.0
    h, m, s = parts
    return int(h) * 3600 + int(m) * 60 + float(s)


def _format_seconds(seconds: float) -> str:
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.0f} 分钟"
    return f"{minutes / 60:.1f} 小时"


def _read_trips(sim_dir: Path) -> list[dict]:
    path = sim_dir / "output_trips.csv.gz"
    with gzip.open(path, "rt") as f:
        return list(csv.DictReader(f, delimiter=";"))


def _read_person_count(sim_dir: Path) -> int:
    path = sim_dir / "output_persons.csv.gz"
    with gzip.open(path, "rt") as f:
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
    for trip in trips:
        mode = trip["modes"] or "(未知)"
        by_mode.setdefault(mode, []).append(trip)

    total_trips = len(trips)
    mode_rows = []
    for mode, rows in sorted(by_mode.items(), key=lambda kv: -len(kv[1])):
        share = len(rows) / total_trips if total_trips else 0
        avg_time = statistics.mean(_parse_hms(r["trav_time"]) for r in rows)
        avg_dist = statistics.mean(float(r["traveled_distance"] or 0) for r in rows)
        mode_rows.append({
            "mode": mode,
            "count": len(rows),
            "share": share,
            "avg_time_seconds": avg_time,
            "avg_time_label": _format_seconds(avg_time),
            "avg_distance_m": avg_dist,
        })

    first_iter, first_score = score_rows[0]
    last_iter, last_score = score_rows[-1]

    return {
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
    lines.append("| 方式 | 次数 | 占比 | 平均耗时 | 平均距离 |")
    lines.append("|---|---|---|---|---|")
    for row in data["mode_rows"]:
        lines.append(f"| {row['mode']} | {row['count']} | {row['share']:.1%} | {row['avg_time_label']} | {row['avg_distance_m']:.0f} 米 |")
    lines.append("")
    lines.append("## 图表")
    lines.append("")
    lines.append("MATSim 自己生成了这些图表，可以直接打开看：")
    lines.append(f"- `{data['modestats_chart']}` — 出行方式占比随迭代轮数的变化")
    lines.append(f"- `{data['scorestats_chart']}` — 平均得分随迭代轮数的变化")
    lines.append("")

    content = "\n".join(lines)
    summary_path = OUTPUT_DIR / sim_output_subdir / "summary.md"
    summary_path.write_text(content)
    return summary_path
