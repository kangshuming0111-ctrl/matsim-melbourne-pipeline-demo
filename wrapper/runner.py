"""Builds and runs the `network` R generator inside Docker, hiding R/Docker
details behind a plain Python function call."""

import os
import json
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from wrapper.docker_image import fingerprint_build_args, image_matches_source, source_fingerprint
from wrapper.process_logging import announce, process_log_path, run_logged
from wrapper.network_domain import validate_output_name
from wrapper.provenance import file_evidence, sha256_file, utc_now

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGE_TAG = "matsim-network-generator"
DOCKERFILE = PROJECT_ROOT / "docker" / "network.Dockerfile"
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
IMAGE_SOURCE_PATHS = (DOCKERFILE, PROJECT_ROOT / "vendor" / "network")


@lru_cache(maxsize=1)
def image_fingerprint() -> str:
    return source_fingerprint(IMAGE_SOURCE_PATHS)


@dataclass
class NetworkRunConfig:
    city: str
    region_file: str  # path relative to data/, e.g. "melbourne_boundary.sqlite"
    output_subdir: str = "generated_network"
    output_crs: int = 7899
    region_buffer_dist: int = 500  # meters; upstream default (10000) balloons small test areas
    osm_pbf_file: str | None = None  # optional exact file inside data/, avoids provider auto-match drift
    cached_only: bool = False  # activity-domain profile must not build/download implicitly

    def to_env(self) -> dict:
        env = {
            "NETWORK_CITY": self.city,
            "NETWORK_OUTPUT_SUBDIR": self.output_subdir,
            "NETWORK_REGION": f"./data/{self.region_file}",
            "NETWORK_OUTPUT_CRS": str(self.output_crs),
            "NETWORK_REGION_BUFFER_DIST": str(self.region_buffer_dist),
        }
        if self.osm_pbf_file:
            env["NETWORK_OSM_PBF"] = f"./data/{self.osm_pbf_file}"
        return env


def image_exists() -> bool:
    return image_matches_source(IMAGE_TAG, image_fingerprint())


def build_image(*, log_path: Path | None = None) -> None:
    announce(f"Building docker image '{IMAGE_TAG}' (first run only, this can take a few minutes)...")
    run_logged(
        [
            "docker", "build", *fingerprint_build_args(image_fingerprint()),
            "-f", str(DOCKERFILE), "-t", IMAGE_TAG, str(PROJECT_ROOT),
        ],
        cwd=PROJECT_ROOT,
        log_path=log_path or process_log_path(OUTPUT_DIR, IMAGE_TAG + "_build"),
    )


def run(config: NetworkRunConfig) -> Path:
    """Run with exclusively owned scratch; old inputs and outputs are not reused."""
    validate_output_name(config.output_subdir)
    network_dir = OUTPUT_DIR / config.output_subdir
    if network_dir.exists():
        raise FileExistsError("Network output already exists; choose a fresh output name.")
    def data_file(relative):
        path = (DATA_DIR / relative).resolve()
        if not path.is_relative_to(DATA_DIR.resolve()) or not path.is_file():
            raise ValueError("Network input must be an existing file within data/.")
        return path
    region = data_file(config.region_file)
    pbf = data_file(config.osm_pbf_file) if config.osm_pbf_file else None
    if config.cached_only and pbf is None:
        raise ValueError("Cached-only generation requires an explicit local OSM PBF.")
    log_path = process_log_path(OUTPUT_DIR, config.output_subdir)
    # An exclusive directory also prevents two concurrent jobs claiming the
    # same producer-owned output. Failed workspaces are kept, never resumed.
    work = OUTPUT_DIR / "network_work" / config.output_subdir
    work.mkdir(parents=True, exist_ok=False)
    scratch = work / "scratch"
    scratch.mkdir()
    downloads = work / "downloads"
    downloads.mkdir()
    record = {"status": "preparing", "started_at": utc_now(), "cached_only": config.cached_only,
              "inputs": {"region_sha256": sha256_file(region)}, "error": None}
    def save():
        temporary = work / 'runner_manifest.json.tmp'
        temporary.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")
        temporary.replace(work / 'runner_manifest.json')
    save()
    try:
        return _run_isolated(config, region, pbf, work, scratch, downloads, log_path, record, save)
    except BaseException as exc:
        record.update(status="failed", finished_at=utc_now(),
                      error={"type": type(exc).__name__, "message": str(exc)})
        save()
        raise


def _run_isolated(config, region, pbf, work, scratch, downloads, log_path, record, save):
    if not image_exists():
        if config.cached_only:
            raise RuntimeError("Cached network image is missing or stale; no automatic build is permitted.")
        build_image(log_path=log_path)
    inspected = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE_TAG],
                               capture_output=True, text=True, check=True)
    image_id = inspected.stdout.strip()
    if not image_id.startswith("sha256:"):
        raise RuntimeError("Cannot pin cached network image identity.")
    record["image_id"] = image_id
    record["source_fingerprint"] = image_fingerprint()
    work_container = f"/app/output/network_work/{config.output_subdir}"
    env = config.to_env()
    env.update(NETWORK_REGION=f"/source/data/{region.relative_to(DATA_DIR.resolve()).as_posix()}",
               NETWORK_OSM_GPKG=f"{work_container}/scratch/osm_extract.gpkg",
               NETWORK_UNCONFIGURED_SQLITE=f"{work_container}/scratch/network_unconfigured.sqlite",
               CPL_TMPDIR=f"{work_container}/scratch", TMPDIR=f"{work_container}/scratch",
               RENV_CONFIG_AUTOLOADER_ENABLED="false", NETWORK_DOWNLOAD_OSM="TRUE",
               NETWORK_PARALLEL_CORES="2")
    if pbf:
        record["inputs"]["osm_pbf_sha256"] = sha256_file(pbf)
        copied = scratch / pbf.name
        shutil.copyfile(pbf, copied)
        if sha256_file(copied) != record["inputs"]["osm_pbf_sha256"]:
            raise RuntimeError("OSM scratch copy hash mismatch.")
        env["NETWORK_OSM_PBF"] = f"{work_container}/scratch/{pbf.name}"
    env_args = []
    for key, value in env.items():
        env_args += ["-e", f"{key}={value}"]
    cmd = [
        "docker", "run", "--rm", "--pull", "never",
        *(["--network", "none"] if pbf else []),
        "--memory", "32g", "--cpus", "4",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-v", f"{DATA_DIR}:/source/data:ro",
        # Provider auto-downloads (legacy mode only) also stay in owned scratch.
        "-v", f"{downloads}:/app/data",
        "-v", f"{OUTPUT_DIR}:/app/output",
        *env_args,
        "--entrypoint", "Rscript", image_id, "--vanilla", "-e",
        "source('NetworkGenerator.R'); makeNetwork(Sys.getenv('NETWORK_CITY'), Sys.getenv('NETWORK_OUTPUT_SUBDIR'))",
    ]
    record.update(status="running", command=cmd, container_environment=env)
    save()
    announce(f"Running network generator for city='{config.city}' with isolated scratch...")
    run_logged(cmd, log_path=log_path)
    record["inputs_unchanged"] = {
        "region": sha256_file(region) == record["inputs"]["region_sha256"],
        "osm_pbf": pbf is None or sha256_file(pbf) == record["inputs"]["osm_pbf_sha256"],
    }
    if not all(record["inputs_unchanged"].values()):
        raise RuntimeError("An original network input changed during generation.")
    artifacts = {}
    for name in ("network.xml", "network.sqlite"):
        path = OUTPUT_DIR / config.output_subdir / name
        artifacts[name] = file_evidence(path, checksum=True)
    record["artifacts"] = artifacts
    save()
    if any(not item["exists"] or item.get("size_bytes", 0) <= 0 for item in artifacts.values()):
        raise RuntimeError("Network generator exited without nonempty network.xml and network.sqlite.")
    record.update(status="completed", finished_at=utc_now())
    save()
    return OUTPUT_DIR / config.output_subdir
