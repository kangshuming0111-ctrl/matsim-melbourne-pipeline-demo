"""Orchestrates `network` + `demand` for one matched region ("scenario"),
so the two outputs actually cover the same area instead of being generated
independently with mismatched defaults."""

import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal

from wrapper.runner import NetworkRunConfig, run as run_network, image_exists as network_image_exists
from wrapper.process_logging import announce, process_log_path, run_logged
from wrapper.network_domain import (
    prepare_activity_domain, audit_activity_network, fail_activity_domain,
    validate_domain_options, validate_output_name,
)
from wrapper.demand_runner import (
    DemandRunConfig,
    run as run_demand,
    IMAGE_TAG as DEMAND_IMAGE_TAG,
    DATA_DIR,
    OUTPUT_DIR,
    image_exists as demand_image_exists,
    build_image as build_demand_image,
)


def derive_sa1_subset(region_file: str, buffer_dist: int, output_csv_name: str) -> Path:
    """Runs derive_sa1_subset.R inside the demand image to find which SA1
    regions overlap the given (buffered) region polygon."""
    log_path = process_log_path(OUTPUT_DIR, output_csv_name)
    if not demand_image_exists():
        build_demand_image(log_path=log_path)

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
    announce(f"Deriving SA1 subset for region '{region_file}' (buffer {buffer_dist}m)...")
    run_logged(cmd, log_path=log_path)

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
                  osm_pbf_file: str | None = None, *,
                  network_domain: Literal["region", "activity_bbox"] = "region",
                  network_buffer_m: int = 500,
                  max_network_area_km2: float | None = None) -> tuple[Path, Path]:
    """Legacy region-first or fixed-demand activity-domain generation.

    In activity_bbox mode buffer_dist selects SA1s only; network_buffer_m is
    independent. A failed domain gate raises before callers can run MATSim.
    """
    validate_output_name(output_name)
    if network_domain not in ("region", "activity_bbox"):
        raise ValueError("Unknown network-domain strategy.")
    if network_domain == "activity_bbox":
        validate_domain_options(7899, network_buffer_m, max_network_area_km2)
        if (not osm_pbf_file or not (DATA_DIR / osm_pbf_file).is_file()
                or not (DATA_DIR / osm_pbf_file).resolve().is_relative_to(DATA_DIR.resolve())):
            raise ValueError("Activity-domain generation requires a cached OSM PBF.")
        # Do not spend a demand-generation run discovering a missing/stale
        # network runtime. Runner checks again immediately before generation.
        try:
            cached_image_ready = network_image_exists()
        except OSError as exc:
            raise RuntimeError("Cannot inspect cached network image; start Docker and explicitly build the current network image before demand generation.") from exc
        if not cached_image_ready:
            raise RuntimeError("Cached network image is missing or stale. Explicitly build matsim-network-generator from current sources before demand generation; automatic builds are disabled for activity_bbox.")
        for suffix in ("network", "demand", "domain"):
            if (OUTPUT_DIR / f"{output_name}_{suffix}").exists():
                raise FileExistsError("Scenario output already exists; use a new output name.")
        if (DATA_DIR / f"{output_name}_sa1_subset.csv").exists():
            raise FileExistsError("Scenario SA1 subset already exists; use a new output name.")
        return _run_activity_scenario(region_file, output_name, buffer_dist, num_plans,
                                      sample_percent, demand_random_seed, osm_pbf_file,
                                      network_buffer_m, max_network_area_km2)

    announce("=== Step 1/3: building network ===")
    network_config = NetworkRunConfig(
        city=output_name,
        region_file=region_file,
        output_subdir=f"{output_name}_network",
        region_buffer_dist=buffer_dist,
        osm_pbf_file=osm_pbf_file,
    )
    network_output_dir = run_network(network_config)

    announce("\n=== Step 2/3: deriving matching SA1 subset ===")
    sa1_csv_name = f"{output_name}_sa1_subset.csv"
    derive_sa1_subset(region_file, buffer_dist, sa1_csv_name)

    announce("\n=== Step 3/3: building demand for the same SA1 subset ===")
    demand_config = DemandRunConfig(
        sample_percent=sample_percent,
        num_plans=num_plans,
        output_subdir=f"{output_name}_demand",
        sa1_subset_file=sa1_csv_name,
        random_seed=demand_random_seed,
    )
    demand_output_dir = run_demand(demand_config)

    announce("\n=== Cross-checking coverage ===")
    coverage = cross_check_coverage(network_output_dir, demand_output_dir)
    announce(f"{coverage:.1%} of demand activity locations fall inside network's coverage area")
    if coverage < 0.5:
        announce("Warning: low overlap — network and demand may still be scoped to different areas.")

    return network_output_dir, demand_output_dir


def _run_activity_scenario(region_file, output_name, buffer_dist, num_plans,
                           sample_percent, demand_random_seed, osm_pbf_file,
                           network_buffer_m, max_network_area_km2):
    announce("=== Step 1/4: selecting whole SA1s from the original demand region ===")
    sa1_csv_name = f"{output_name}_sa1_subset.csv"
    derive_sa1_subset(region_file, buffer_dist, sa1_csv_name)
    announce("=== Step 2/4: generating and freezing demand ===")
    demand_config = DemandRunConfig(sample_percent=sample_percent, num_plans=num_plans,
        output_subdir=f"{output_name}_demand", sa1_subset_file=sa1_csv_name,
        random_seed=demand_random_seed, output_crs=7899)
    demand_output_dir = run_demand(demand_config)
    domain = prepare_activity_domain(demand_output_dir / "8.xml/plan.xml",
        output_name=output_name, plans_crs=demand_config.output_crs,
        network_buffer_m=network_buffer_m, max_buffered_area_km2=max_network_area_km2)
    try:
        announce("=== Step 3/4: generating the network around unchanged demand ===")
        network_output_dir = run_network(NetworkRunConfig(city=output_name,
            region_file=domain.region_file, output_subdir=f"{output_name}_network",
            output_crs=demand_config.output_crs, region_buffer_dist=domain.network_buffer_m,
            osm_pbf_file=osm_pbf_file, cached_only=True))
        announce("=== Step 4/4: post-cleaning activity-domain gate (required 100%) ===")
        audit_activity_network(domain, network_output_dir / "network.xml")
    except BaseException as exc:
        fail_activity_domain(domain, exc)
        raise
    announce("Activity-domain precondition passed; transport/simulation validity is not established.")
    return network_output_dir, demand_output_dir
