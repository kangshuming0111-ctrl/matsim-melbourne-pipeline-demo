"""Builds and runs a MATSim simulation (the `baseline` Java/Maven project)
inside Docker, given a network.xml + plan.xml already produced by `network`
and `demand`. Generates a trimmed config.xml (no transit - our scenarios
don't have a transit schedule) from a template rather than editing the
vendored scenario/v1/config.xml in place.
"""

import os
from functools import lru_cache
from pathlib import Path

from wrapper.docker_image import fingerprint_build_args, image_matches_source, source_fingerprint
from wrapper.process_logging import announce, process_log_path, run_logged

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGE_TAG = "matsim-baseline"
DOCKERFILE = PROJECT_ROOT / "docker" / "baseline.Dockerfile"
OUTPUT_DIR = PROJECT_ROOT / "output"
IMAGE_SOURCE_PATHS = (DOCKERFILE, PROJECT_ROOT / "vendor" / "baseline")


@lru_cache(maxsize=1)
def image_fingerprint() -> str:
    return source_fingerprint(IMAGE_SOURCE_PATHS)

# All paths are container-absolute: output/ is mounted at /app/output, and
# vendor/baseline is baked into the image at /app during the build, so
# mode-vehicles.xml is always at this fixed path regardless of what's mounted.
CONFIG_TEMPLATE = """<?xml version="1.0" ?>
<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">
<config>

	<module name="global">
		<param name="randomSeed" value="{random_seed}" />
		<param name="coordinateSystem" value="EPSG:7899" />
		<param name="numberOfThreads" value="4"/>
	</module>

	<module name="network">
		<param name="inputNetworkFile" value="{network_file}" />
	</module>

	<module name="plans">
		<param name="inputPlansFile" value="{plans_file}" />
	</module>

	<module name="controler">
		<param name="outputDirectory" value="{output_dir}" />
		<param name="firstIteration" value="0" />
		<param name="lastIteration" value="{last_iteration}" />
		<param name="writeEventsInterval" value="1" />
		<param name="writePlansInterval" value="1" />
	</module>

	<module name="qsim">
		<param name="vehiclesSource" value="modeVehicleTypesFromVehiclesData" />
		<param name="linkDynamics" value="PassingQ" />
		<param name="trafficDynamics" value="kinematicWaves" />
		<param name="numberOfThreads" value="4"/>
	</module>

	<module name="planCalcScore">
		<parameterset type="scoringParameters">
			<param name="earlyDeparture" value="-0.0" />
			<param name="lateArrival" value="-31.27237618" />
			<param name="marginalUtilityOfMoney" value="0.5159" />
			<param name="performing" value="10.42412539" />
			<param name="utilityOfLineSwitch" value="-1.0" />
			<param name="waiting" value="-0.0" />
			<param name="waitingPt" value="-20.84825079" />

			<parameterset type="modeParams"><!-- car -->
				<param name="mode" value="car" />
				<param name="constant" value="0.0" />
				<param name="marginalUtilityOfTraveling_util_hr" value="-0.0" />
				<param name="monetaryDistanceRate" value="-0.0007080" />
			</parameterset>

			<parameterset type="modeParams"><!-- walk -->
				<param name="mode" value="walk" />
				<param name="constant" value="0.38552456" />
				<param name="marginalUtilityOfDistance_util_m" value="0.0" />
				<param name="marginalUtilityOfTraveling_util_hr" value="-0.43375109" />
			</parameterset>

			<parameterset type="modeParams"><!-- bike -->
				<param name="mode" value="bike" />
				<param name="constant" value="-3.03305065" />
				<param name="marginalUtilityOfDistance_util_m" value="0.0" />
				<param name="marginalUtilityOfTraveling_util_hr" value="-2.13717694" />
			</parameterset>

			<!-- demand's plans can assign "pt" as a mode even though this scenario
			     has no transit schedule (see planscalcroute's teleported pt entry) -
			     scoring requires a modeParams block for every mode that appears in
			     the plans, or it throws at runtime, not at config-load time -->
			<parameterset type="modeParams"><!-- pt -->
				<param name="mode" value="pt" />
				<param name="constant" value="-1.48297513" />
				<param name="marginalUtilityOfTraveling_util_hr" value="-0.09461678" />
				<param name="dailyMonetaryConstant" value="-8.6" />
			</parameterset>

			<parameterset type="activityParams"><!-- Home -->
				<param name="activityType" value="Home" />
				<param name="minimalDuration" value="08:00:00" />
				<param name="typicalDuration" value="12:00:00" />
			</parameterset>
			<parameterset type="activityParams"><!-- Work -->
				<param name="activityType" value="Work" />
				<param name="minimalDuration" value="06:00:00" />
				<param name="typicalDuration" value="08:00:00" />
				<param name="openingTime" value="07:00:00" />
				<param name="latestStartTime" value="09:00:00" />
				<param name="closingTime" value="18:00:00" />
			</parameterset>
			<parameterset type="activityParams"><!-- Shop -->
				<param name="activityType" value="Shop" />
				<param name="minimalDuration" value="00:30:00" />
				<param name="typicalDuration" value="01:00:00" />
				<param name="openingTime" value="07:00:00" />
				<param name="latestStartTime" value="09:00:00" />
				<param name="closingTime" value="18:00:00" />
			</parameterset>
			<parameterset type="activityParams"><!-- Study -->
				<param name="activityType" value="Study" />
				<param name="minimalDuration" value="06:00:00" />
				<param name="typicalDuration" value="08:00:00" />
				<param name="openingTime" value="07:00:00" />
				<param name="latestStartTime" value="09:00:00" />
				<param name="closingTime" value="18:00:00" />
			</parameterset>
			<parameterset type="activityParams"><!-- Other -->
				<param name="activityType" value="Other" />
				<param name="minimalDuration" value="06:00:00" />
				<param name="typicalDuration" value="08:00:00" />
				<param name="openingTime" value="07:00:00" />
				<param name="latestStartTime" value="09:00:00" />
				<param name="closingTime" value="18:00:00" />
			</parameterset>
			<parameterset type="activityParams"><!-- Social/Recreational -->
				<param name="activityType" value="Social/Recreational" />
				<param name="minimalDuration" value="06:00:00" />
				<param name="typicalDuration" value="08:00:00" />
				<param name="openingTime" value="07:00:00" />
				<param name="latestStartTime" value="09:00:00" />
				<param name="closingTime" value="18:00:00" />
			</parameterset>
			<parameterset type="activityParams"><!-- Personal -->
				<param name="activityType" value="Personal" />
				<param name="minimalDuration" value="06:00:00" />
				<param name="typicalDuration" value="08:00:00" />
				<param name="openingTime" value="07:00:00" />
				<param name="latestStartTime" value="09:00:00" />
				<param name="closingTime" value="18:00:00" />
			</parameterset>
			<parameterset type="activityParams"><!-- Pickup/Dropoff/Deliver -->
				<param name="activityType" value="Pickup/Dropoff/Deliver" />
				<param name="minimalDuration" value="00:10:00" />
				<param name="typicalDuration" value="00:30:00" />
			</parameterset>
		</parameterset>
	</module>

	<module name="planscalcroute">
		<param name="networkModes" value="car,bike" />
		<parameterset type="teleportedModeParameters">
			<param name="beelineDistanceFactor" value="1.3" />
			<param name="mode" value="walk" />
			<param name="teleportedModeSpeed" value="0.65" />
		</parameterset>
		<!-- demand's plans can assign "pt" as a mode independent of whether this
		     scenario has a transit schedule; since useTransit is off here, treat
		     pt as teleported (beeline at a fixed speed) instead of routed, so
		     PrepareForSim doesn't hit an UnknownModeException for it -->
		<parameterset type="teleportedModeParameters">
			<param name="beelineDistanceFactor" value="1.5" />
			<param name="mode" value="pt" />
			<param name="teleportedModeSpeed" value="8.3" />
		</parameterset>
	</module>

	<module name="vehicles">
		<param name="vehiclesFile" value="/app/scenario/v1/mode-vehicles.xml" />
	</module>

	<module name="strategy">
		<param name="maxAgentPlanMemorySize" value="5" />
		<param name="fractionOfIterationsToDisableInnovation" value="0.8" />
		<parameterset type="strategysettings">
			<param name="strategyName" value="BestScore"/>
			<param name="weight" value="0.8"/>
			<param name="subpopulation" value="Worker"/>
		</parameterset>
		<parameterset type="strategysettings">
			<param name="strategyName" value="BestScore"/>
			<param name="weight" value="0.9"/>
			<param name="subpopulation" value="NonWorker"/>
		</parameterset>
		<parameterset type="strategysettings">
			<param name="strategyName" value="ReRoute"/>
			<param name="weight" value="0.1"/>
			<param name="subpopulation" value="Worker"/>
		</parameterset>
		<parameterset type="strategysettings">
			<param name="strategyName" value="ReRoute"/>
			<param name="weight" value="0.1"/>
			<param name="subpopulation" value="NonWorker"/>
		</parameterset>
	</module>

	<module name="subtourModeChoice">
		<param name="chainBasedModes" value="car,bike" />
		<param name="considerCarAvailability" value="false" />
		<param name="modes" value="car,bike,walk" />
	</module>

	<module name="travelTimeCalculator">
		<param name="analyzedModes" value="car,bike,walk" />
		<param name="separateModes" value="true" />
	</module>

</config>
"""


def image_exists() -> bool:
    return image_matches_source(IMAGE_TAG, image_fingerprint())


def build_image(*, log_path: Path | None = None) -> None:
    announce(f"Building docker image '{IMAGE_TAG}' (first run only - Maven has to download MATSim + contribs, can take a while)...")
    run_logged(
        [
            "docker", "build", *fingerprint_build_args(image_fingerprint()),
            "-f", str(DOCKERFILE), "-t", IMAGE_TAG, str(PROJECT_ROOT),
        ],
        cwd=PROJECT_ROOT,
        log_path=log_path or process_log_path(OUTPUT_DIR, IMAGE_TAG + "_build"),
    )


def run(network_output_subdir: str, demand_output_subdir: str, output_subdir: str,
        last_iteration: int = 2, random_seed: int = 4711) -> Path:
    """Runs a MATSim simulation using an already-generated network + plans
    output (both under output/), writing results to output/{output_subdir}."""
    log_path = process_log_path(OUTPUT_DIR, output_subdir)
    if not image_exists():
        build_image(log_path=log_path)

    OUTPUT_DIR.mkdir(exist_ok=True)

    network_file = f"/app/output/{network_output_subdir}/network.xml"
    plans_file = f"/app/output/{demand_output_subdir}/8.xml/plan.xml"
    sim_output_dir = f"/app/output/{output_subdir}"

    config_content = CONFIG_TEMPLATE.format(
        network_file=network_file,
        plans_file=plans_file,
        output_dir=sim_output_dir,
        last_iteration=last_iteration,
        random_seed=random_seed,
    )
    config_local_dir = OUTPUT_DIR / f"{output_subdir}_config"
    config_local_dir.mkdir(exist_ok=True)
    config_path = config_local_dir / "config.xml"
    config_path.write_text(config_content)

    cmd = [
        "docker", "run", "--rm",
        "--memory", "16g",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-v", f"{OUTPUT_DIR}:/app/output",
        IMAGE_TAG,
        f"/app/output/{output_subdir}_config/config.xml",
    ]

    announce(f"Running MATSim simulation (iterations 0–{last_iteration})... this can take a while.")
    run_logged(cmd, log_path=log_path)

    return OUTPUT_DIR / output_subdir
