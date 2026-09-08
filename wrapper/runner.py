"""Builds and runs the `network` R generator inside Docker, hiding R/Docker
details behind a plain Python function call."""

import subprocess
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from wrapper.docker_image import fingerprint_build_args, image_matches_source, source_fingerprint

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


def build_image() -> None:
    print(f"Building docker image '{IMAGE_TAG}' (first run only, this can take a few minutes)...")
    subprocess.run(
        [
            "docker", "build", *fingerprint_build_args(image_fingerprint()),
            "-f", str(DOCKERFILE), "-t", IMAGE_TAG, str(PROJECT_ROOT),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )


def run(config: NetworkRunConfig) -> Path:
    """Runs the network generator container and returns the output directory."""
    if not image_exists():
        build_image()

    DATA_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    env_args = []
    for key, value in config.to_env().items():
        env_args += ["-e", f"{key}={value}"]

    cmd = [
        "docker", "run", "--rm",
        "--memory", "32g",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-v", f"{DATA_DIR}:/app/data",
        "-v", f"{OUTPUT_DIR}:/app/output",
        "-e", "RENV_CONFIG_AUTOLOADER_ENABLED=false",
        # GDAL's OSM driver spills large node/way caches to disk once they
        # exceed its in-memory threshold, using a path relative to cwd
        # (/app, owned by root - not writable by --user above). This only
        # bites on large regions (small test areas never hit the threshold),
        # surfacing as an empty "lines" layer and a downstream crash rather
        # than a clear permission error. Point GDAL's temp dir somewhere
        # actually writable.
        "-e", "CPL_TMPDIR=/app/output",
        *env_args,
        IMAGE_TAG,
    ]

    print(f"Running network generator for city='{config.city}'... (this can take a while: OSM download + processing)")
    subprocess.run(cmd, check=True)

    return OUTPUT_DIR / config.output_subdir
