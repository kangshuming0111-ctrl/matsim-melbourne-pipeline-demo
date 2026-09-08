"""Orchestrates `network` + `demand` for one matched region ("scenario"),
so the two outputs actually cover the same area instead of being generated
independently with mismatched defaults."""

import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from wrapper.runner import NetworkRunConfig, run as run_network
from wrapper.demand_runner import (
    DemandRunConfig,
    run as run_demand,
    IMAGE_TAG as DEMAND_IMAGE_TAG,
    DATA_DIR,
    image_exists as demand_image_exists,
    build_image as build_demand_image,
)


def derive_sa1_subset(region_file: str, buffer_dist: int, output_csv_name: str) -> Path:
    """Runs derive_sa1_subset.R inside the demand image to find which SA1
    regions overlap the given (buffered) region polygon."""
    if not demand_image_exists():
        build_demand_image()

    DATA_DIR.mkdir(exist_ok=True)

    cmd = [
        "docker", "run", "--rm",
        "--entrypoint", "Rscript",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-v", f"{DATA_DIR}:/app/data",
        "-e", f"SCENARIO_REGION_FILE=../data/{region_file}",
        "-e", f"SCENARIO_REGION_BUFFER_DIST={buffer_dist}",
        "-e", f"SA1_SUBSET_OUTPUT=../data/{output_csv_name}",
        DEMAND_IMAGE_TAG,
        "derive_sa1_subset.R",
    ]
    print(f"Deriving SA1 subset for region '{region_file}' (buffer {buffer_dist}m)...")
    subprocess.run(cmd, check=True)

    return DATA_DIR / output_csv_name


def cross_check_coverage(network_output_dir: Path, demand_output_dir: Path) -> float:
    """Fraction of demand activity coordinates that fall inside network's
    node bounding box — a sanity check that the two outputs are scoped to
    the same area, not a rigorous polygon-containment check."""
    network_tree = ET.parse(network_output_dir / "network.xml")
    nodes = network_tree.getroot().find("nodes")
    xs = [float(n.get("x")) for n in nodes]
    ys = [float(n.get("y")) for n in nodes]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)

    demand_tree = ET.parse(demand_output_dir / "8.xml" / "plan.xml")
    persons = demand_tree.getroot().findall(".//person")

    total = 0
    inside = 0
    for person in persons:
        plan = person.find("plan")
        if plan is None:
            continue
        for act in plan.findall("activity"):
            x, y = float(act.get("x")), float(act.get("y"))
            total += 1
            if xmin <= x <= xmax and ymin <= y <= ymax:
                inside += 1

    return inside / total if total else 0.0


def run_scenario(region_file: str, output_name: str, buffer_dist: int = 500,
                  num_plans: int = 500, sample_percent: float = 0.1,
                  demand_random_seed: int | None = None,
                  osm_pbf_file: str | None = None) -> tuple[Path, Path]:
    print("=== Step 1/3: building network ===")
    network_config = NetworkRunConfig(
        city=output_name,
        region_file=region_file,
        output_subdir=f"{output_name}_network",
        region_buffer_dist=buffer_dist,
        osm_pbf_file=osm_pbf_file,
    )
    network_output_dir = run_network(network_config)

    print("\n=== Step 2/3: deriving matching SA1 subset ===")
    sa1_csv_name = f"{output_name}_sa1_subset.csv"
    derive_sa1_subset(region_file, buffer_dist, sa1_csv_name)

    print("\n=== Step 3/3: building demand for the same SA1 subset ===")
    demand_config = DemandRunConfig(
        sample_percent=sample_percent,
        num_plans=num_plans,
        output_subdir=f"{output_name}_demand",
        sa1_subset_file=sa1_csv_name,
        random_seed=demand_random_seed,
    )
    demand_output_dir = run_demand(demand_config)

    print("\n=== Cross-checking coverage ===")
    coverage = cross_check_coverage(network_output_dir, demand_output_dir)
    print(f"{coverage:.1%} of demand activity locations fall inside network's coverage area")
    if coverage < 0.5:
        print("Warning: low overlap — network and demand may still be scoped to different areas.")

    return network_output_dir, demand_output_dir
