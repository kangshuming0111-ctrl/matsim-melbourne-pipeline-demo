"""Fast, read-only readiness checks for the web UI and API.

The original pipeline used to discover missing Docker/data only after a
15-minute job had started.  These checks make failures actionable before a
user presses Run.  They intentionally do not build images, download data, or
modify the machine.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# This mirrors vendor/demand/R/checksum.R.  Checking existence here is quick;
# the upstream R checksum remains the final integrity check inside Docker.
DEMAND_DATA_FILES = (
    "VISTA_12_18_CSV.zip.dir/T_VISTA1218_V1.csv",
    "absRegionsReprojected.sqlite",
    "distanceMatrix.rds",
    "distanceMatrixIndex.csv",
    "SA1attributed.csv.gz",
    "SA1centroids.csv.gz",
    "addresses.csv.gz",
    "vistaCohorts.csv.gz",
    "expectedDistances.rds",
    "vistaSummaries/destinationProbabilitiesSA3.rds",
    "vistaSummaries/distanceDistributionsSA3.rds",
    "vistaSummaries/distanceHistograms.rds",
    "vistaSummaries/modeChoiceProbabilitiesSA3.rds",
)
PRESET_LANDMARK_KEYS = (
    "cbd", "inner_north", "inner_east", "inner_south",
    "inner_northeast", "inner_southeast",
)


def _item(key: str, label: str, status: str, detail: str) -> dict:
    return {"key": key, "label": label, "status": status, "detail": detail}


def _docker_check() -> tuple[dict, dict | None]:
    if shutil.which("docker") is None:
        return _item("docker", "Docker", "blocked", "尚未安装 Docker Desktop"), None

    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}|{{.NCPU}}|{{.MemTotal}}"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _item("docker", "Docker", "blocked", "Docker Desktop 没有响应"), None

    if proc.returncode != 0:
        return _item("docker", "Docker", "blocked", "Docker Desktop 未启动"), None

    try:
        version, cpus, memory_raw = proc.stdout.strip().split("|")
        memory_gb = int(memory_raw) / (1024 ** 3)
        details = {"version": version, "cpus": int(cpus), "memory_gb": round(memory_gb, 1)}
    except (TypeError, ValueError):
        return _item("docker", "Docker", "warning", "Docker 正在运行，但资源信息无法读取"), None

    if memory_gb < 8:
        status = "blocked"
        message = f"仅分配 {memory_gb:.1f}GB 内存；至少需要 8GB，建议 24GB 以上"
    elif memory_gb < 24:
        status = "warning"
        message = f"已启动，内存 {memory_gb:.1f}GB；小区域可跑，大区域建议 24GB 以上"
    else:
        status = "ready"
        message = f"已启动 · {memory_gb:.1f}GB · {cpus} CPU"
    return _item("docker", "Docker", status, message), details


def check_system() -> dict:
    checks: list[dict] = []

    python_ok = sys.version_info >= (3, 10)
    checks.append(_item(
        "python", "Python", "ready" if python_ok else "blocked",
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        + ("" if python_ok else "；需要 Python 3.10 或更高版本"),
    ))

    missing_packages = [name for name in ("fastapi", "uvicorn", "rasterio", "shapely")
                        if importlib.util.find_spec(name) is None]
    checks.append(_item(
        "packages", "Python 依赖", "ready" if not missing_packages else "blocked",
        "已安装" if not missing_packages else "缺少：" + "、".join(missing_packages),
    ))

    docker_item, docker_details = _docker_check()
    checks.append(docker_item)

    missing_data = [name for name in DEMAND_DATA_FILES if not (DATA_DIR / name).is_file()]
    checks.append(_item(
        "demand_data", "人口与出行数据", "ready" if not missing_data else "blocked",
        "13 项必需数据均已就绪" if not missing_data
        else f"缺少 {len(missing_data)} 项：" + "、".join(missing_data[:3])
             + ("…" if len(missing_data) > 3 else ""),
    ))

    osm_cache = DATA_DIR / "geofabrik_victoria-latest.osm.pbf"
    checks.append(_item(
        "osm_data", "Victoria OSM 路网",
        "ready" if osm_cache.is_file() else "blocked",
        "固定演示使用本地 Victoria PBF，避免自动匹配成整个澳大利亚"
        if osm_cache.is_file()
        else "缺少 data/geofabrik_victoria-latest.osm.pbf；固定演示不会改用全国数据",
    ))

    region_count = len(list(DATA_DIR.glob("*.geojson")))
    checks.append(_item(
        "regions", "区域边界", "ready" if region_count else "blocked",
        f"发现 {region_count} 个 GeoJSON 边界" if region_count else "没有可用区域边界",
    ))

    visual_missing = []
    if not (DATA_DIR / "dem" / "fabdem_melbourne.tif").is_file():
        visual_missing.append("FABDEM 地形")
    missing_landmarks = [key for key in PRESET_LANDMARK_KEYS
                         if not any(p.is_file() for p in (
                             DATA_DIR / "landmarks" / "v2" / f"{key}.json",
                             DATA_DIR / "landmarks" / f"{key}.json"))]
    if missing_landmarks:
        visual_missing.append(f"{len(missing_landmarks)} 个区域的建筑地标")
    checks.append(_item(
        "visual_data", "3D 城市数据", "ready" if not visual_missing else "warning",
        "地形与 6 个区域的建筑地标已就绪" if not visual_missing
        else "缺少：" + "、".join(visual_missing) + "；仿真仍可运行，但 3D 内容会减少",
    ))

    try:
        free_gb = shutil.disk_usage(PROJECT_ROOT).free / (1024 ** 3)
        disk_status = "blocked" if free_gb < 3 else "warning" if free_gb < 10 else "ready"
        disk_detail = f"可用 {free_gb:.1f}GB" + ("；建议清理旧运行" if free_gb < 10 else "")
    except OSError:
        free_gb, disk_status, disk_detail = None, "warning", "无法读取剩余空间"
    checks.append(_item("disk", "磁盘空间", disk_status, disk_detail))

    blocked = [check for check in checks if check["status"] == "blocked"]
    warnings = [check for check in checks if check["status"] == "warning"]
    overall = "blocked" if blocked else "warning" if warnings else "ready"
    return {
        "status": overall,
        "can_run_pipeline": not blocked,
        "checks": checks,
        "docker": docker_details,
        "missing_data": missing_data,
        "free_disk_gb": round(free_gb, 1) if free_gb is not None else None,
    }
