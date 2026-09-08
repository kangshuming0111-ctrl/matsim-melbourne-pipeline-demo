"""Builds and runs the `demand` R population generator inside Docker, hiding
R/Docker details behind a plain Python function call. Mirrors wrapper/runner.py
(the `network` equivalent) but kept as a separate module so tuning one doesn't
risk regressing the other.
"""

import subprocess
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from wrapper.docker_image import fingerprint_build_args, image_matches_source, source_fingerprint

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGE_TAG = "matsim-demand-generator"
DOCKERFILE = PROJECT_ROOT / "docker" / "demand.Dockerfile"
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
IMAGE_SOURCE_PATHS = (DOCKERFILE, PROJECT_ROOT / "vendor" / "demand")


@lru_cache(maxsize=1)
def image_fingerprint() -> str:
    return source_fingerprint(IMAGE_SOURCE_PATHS)


@dataclass
class DemandRunConfig:
    sample_percent: float
    num_plans: int
    output_subdir: str = "demand_run1"
    sa1_subset_file: str | None = None  # path relative to data/, e.g. "small_sa1_subset.csv"
    all_destinations: bool = False
    output_crs: int = 7899
    random_seed: int | None = None

    def to_env(self) -> dict:
        env = {
            "DEMAND_SAMPLE_PERCENT": str(self.sample_percent),
            "DEMAND_NUM_PLANS": str(self.num_plans),
            "DEMAND_OUTPUT_DIR": f"output/{self.output_subdir}",
            "DEMAND_ALL_DESTINATIONS": "true" if self.all_destinations else "false",
            "DEMAND_OUTPUT_CRS": str(self.output_crs),
        }
        if self.sa1_subset_file:
            # R runs with cwd=/app/R (see demand.Dockerfile), so paths need
            # one more "../" than network's (which runs with cwd=/app).
            env["DEMAND_SA1_SUBSET"] = f"../data/{self.sa1_subset_file}"
        if self.random_seed is not None:
            env["DEMAND_RANDOM_SEED"] = str(self.random_seed)
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


def run(config: DemandRunConfig) -> Path:
    """Runs the demand generator container and returns the output directory."""
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
        *env_args,
        IMAGE_TAG,
    ]

    print(f"Running demand generator (sample={config.sample_percent}%, numPlans={config.num_plans})... this can take a while.")
    subprocess.run(cmd, check=True)

    return OUTPUT_DIR / config.output_subdir
