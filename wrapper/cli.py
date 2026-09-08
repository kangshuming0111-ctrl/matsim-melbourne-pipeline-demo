"""Command-line entrypoint:
  python -m wrapper.cli build --city ... --region ... --output ...   (network)
  python -m wrapper.cli demand --sample-percent ... --num-plans ...  (population)
  python -m wrapper.cli scenario --region ... --output ...           (both, matched to one region)
  python -m wrapper.cli simulate --network-output ... --demand-output ... --output ...  (run MATSim)
  python -m wrapper.cli analyze --sim-output ...                    (plain-language summary, no Docker needed)
  python -m wrapper.cli skyline --sim-output ...                    (traffic-volume 3D city scene, no Docker needed)
  python -m wrapper.cli doctor                                      (check readiness without running)
"""

import argparse
import sys

from wrapper.runner import NetworkRunConfig, run as run_network
from wrapper.demand_runner import DemandRunConfig, run as run_demand
from wrapper.scenario import run_scenario
from wrapper.baseline_runner import run as run_simulation
from wrapper.analyze import summarize


def main():
    parser = argparse.ArgumentParser(description="Generate MATSim inputs (network, demand).")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Run the network generator")
    build.add_argument("--city", required=True, help="Label for this city/region (used for logging and output naming)")
    build.add_argument("--region", required=True, help="Boundary file name inside data/, e.g. melbourne_boundary.sqlite")
    build.add_argument("--output", default="generated_network", help="Output subfolder name inside output/")
    build.add_argument("--crs", type=int, default=7899, help="Output coordinate reference system (EPSG code)")
    build.add_argument("--buffer-dist", type=int, default=500, help="Meters to buffer the region before extracting OSM data (upstream default 10000 is too large for small test areas)")

    demand = subparsers.add_parser("demand", help="Run the population/demand generator")
    demand.add_argument("--sample-percent", type=float, default=0.1, help="Percent of the 2016 census-based synthetic population to sample")
    demand.add_argument("--num-plans", type=int, required=True, help="Number of VISTA-like trip chains (plans) to generate")
    demand.add_argument("--output", default="demand_run1", help="Output subfolder name inside output/")
    demand.add_argument("--sa1-subset", default=None, help="CSV file name inside data/ restricting generation to a subset of SA1 regions (omit for all of Melbourne)")
    demand.add_argument("--all-destinations", action="store_true", help="Allow destinations outside the sa1-subset to be reachable")
    demand.add_argument("--crs", type=int, default=7899, help="Output coordinate reference system (EPSG code)")
    demand.add_argument("--seed", type=int, default=None, help="Optional deterministic random seed for demand generation")

    scenario = subparsers.add_parser("scenario", help="Run network + demand together, matched to the same region")
    scenario.add_argument("--region", required=True, help="Boundary file name inside data/, e.g. sample_region.geojson")
    scenario.add_argument("--output", required=True, help="Base name for this scenario's output folders")
    scenario.add_argument("--buffer-dist", type=int, default=500, help="Meters to buffer the region (applies to both network's OSM extraction and the derived SA1 subset)")
    scenario.add_argument("--num-plans", type=int, default=500, help="Number of VISTA-like trip chains to generate for demand")
    scenario.add_argument("--sample-percent", type=float, default=0.1, help="Percent of the 2016 census-based synthetic population to sample")
    scenario.add_argument("--seed", type=int, default=None, help="Optional deterministic random seed for demand generation")

    simulate = subparsers.add_parser("simulate", help="Run a MATSim simulation from existing network + demand output")
    simulate.add_argument("--network-output", required=True, help="Output subfolder name (inside output/) produced by `build`, e.g. scenario1_network")
    simulate.add_argument("--demand-output", required=True, help="Output subfolder name (inside output/) produced by `demand`, e.g. scenario1_demand")
    simulate.add_argument("--output", required=True, help="Output subfolder name for simulation results")
    simulate.add_argument("--iterations", type=int, default=2, help="Number of MATSim iterations to run (kept small for a PoC - full runs use hundreds)")
    simulate.add_argument("--seed", type=int, default=4711, help="MATSim random seed")

    analyze = subparsers.add_parser("analyze", help="Summarize a MATSim run's output in plain language (no Docker needed)")
    analyze.add_argument("--sim-output", required=True, help="Output subfolder name (inside output/) produced by `simulate`, e.g. scenario1_sim")

    skyline = subparsers.add_parser("skyline", help="Export a traffic-volume 3D city scene (JSON) from a MATSim run's output, viewed in the web UI (no Docker needed)")
    skyline.add_argument("--sim-output", required=True, help="Output subfolder name (inside output/) produced by `simulate`, e.g. scenario1_sim")

    subparsers.add_parser("doctor", help="Check Docker, required data, 3D assets and disk space without starting a run")
    subparsers.add_parser(
        "demo",
        help="Run the fixed, documented CBD end-to-end demonstration with a durable run record",
    )

    args = parser.parse_args()

    if args.command == "build":
        config = NetworkRunConfig(
            city=args.city,
            region_file=args.region,
            output_subdir=args.output,
            output_crs=args.crs,
            region_buffer_dist=args.buffer_dist,
        )
        output_dir = run_network(config)
        print(f"\nDone. Output written to: {output_dir}")
        network_xml = output_dir / "network.xml"
        if network_xml.exists():
            print(f"MATSim network file: {network_xml}")
        else:
            print("Warning: network.xml was not found — check the log above for errors.")
            sys.exit(1)

    elif args.command == "demand":
        config = DemandRunConfig(
            sample_percent=args.sample_percent,
            num_plans=args.num_plans,
            output_subdir=args.output,
            sa1_subset_file=args.sa1_subset,
            all_destinations=args.all_destinations,
            output_crs=args.crs,
            random_seed=args.seed,
        )
        output_dir = run_demand(config)
        print(f"\nDone. Output written to: {output_dir}")
        plan_xml = output_dir / "8.xml" / "plan.xml"
        if plan_xml.exists():
            print(f"MATSim population file: {plan_xml}")
        else:
            print("Warning: plan.xml was not found — check the log above for errors.")
            sys.exit(1)

    elif args.command == "scenario":
        run_scenario(
            region_file=args.region,
            output_name=args.output,
            buffer_dist=args.buffer_dist,
            num_plans=args.num_plans,
            sample_percent=args.sample_percent,
            demand_random_seed=args.seed,
        )

    elif args.command == "simulate":
        output_dir = run_simulation(
            network_output_subdir=args.network_output,
            demand_output_subdir=args.demand_output,
            output_subdir=args.output,
            last_iteration=args.iterations,
            random_seed=args.seed,
        )
        print(f"\nDone. Output written to: {output_dir}")
        output_config = output_dir / "output_config.xml"
        if output_config.exists():
            print(f"MATSim run completed - see {output_dir} for results (events, plans, scores).")
        else:
            print("Warning: output_config.xml was not found (MATSim writes this on successful completion) — check the log above for errors.")
            sys.exit(1)

    elif args.command == "analyze":
        summary_path = summarize(args.sim_output)
        print(summary_path.read_text())
        print(f"\n(also written to {summary_path})")

    elif args.command == "skyline":
        # Keep rasterio optional for commands unrelated to 3D and let
        # `doctor` explain if it is missing.
        from wrapper.skyline import render_skyline_scene
        scene_path = render_skyline_scene(args.sim_output)
        print(f"Done. Scene written to: {scene_path}")
        print("Open the web UI's results page to view it in 3D.")

    elif args.command == "doctor":
        from wrapper.preflight import check_system
        data = check_system()
        symbols = {"ready": "OK", "warning": "WARN", "blocked": "FAIL"}
        print("MATSim environment check\n")
        for check in data["checks"]:
            print(f"[{symbols[check['status']]:4}] {check['label']}: {check['detail']}")
        print(f"\nOverall: {data['status']}")
        if not data["can_run_pipeline"]:
            sys.exit(1)

    elif args.command == "demo":
        from wrapper.pipeline import run_verified_demo
        result = run_verified_demo()
        print(f"\nVerified demo completed: {result['run_id']}")
        print(f"Run record: {result['run_record_path']}")


if __name__ == "__main__":
    main()
