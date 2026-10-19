"""Opt-in lightweight R geometry proof. Never call makeNetwork or MATSim.

Uses the cached source-matching image, disabled network, one CPU, 2 GiB memory,
and only a new smoke directory plus read-only original plans. No PBF is read.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import uuid

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wrapper import network_domain
from wrapper.docker_image import FINGERPRINT_LABEL, source_fingerprint
from wrapper.process_logging import run_logged
from wrapper.provenance import file_evidence, sha256_file, utc_now

ROOT = Path(__file__).resolve().parents[1]
PLANS = ROOT / "output/cbd_demo_20260926T050044Z_a805bd_demand/8.xml/plan.xml"

R_SMOKE = r'''
suppressPackageStartupMessages(library(sf))
suppressPackageStartupMessages(library(lwgeom))
suppressPackageStartupMessages(library(xml2))
suppressPackageStartupMessages(library(jsonlite))
request <- read_json("/smoke/domain/domain_manifest.json", simplifyVector=TRUE)
region <- st_read(file.path("/smoke/data", request$region$data_relative_path), quiet=TRUE)
stopifnot(st_crs(region)$epsg == 4326L, all(st_is_valid(region)))
restored <- st_transform(region, 7899)
doc <- read_xml("/source/plans.xml")
acts <- xml_find_all(doc, "/population/person/plan[@selected='yes']/*[self::activity or self::act]")
xy <- data.frame(x=as.numeric(xml_attr(acts, "x")), y=as.numeric(xml_attr(acts, "y")))
stopifnot(all(is.finite(as.matrix(xy))), nrow(xy) == request$activity_inventory$activities)
points <- st_as_sf(xy, coords=c("x", "y"), crs=7899)
native <- st_as_sfc(st_bbox(points))
buffered <- lwgeom::st_snap_to_grid(st_buffer(restored, request$network_buffer_m), 1)
reference <- lwgeom::st_snap_to_grid(st_buffer(native, request$network_buffer_m), 1)
outside <- sum(lengths(st_intersects(points, buffered)) == 0L)
hausdorff <- as.numeric(st_distance(st_geometry(restored), native, which="Hausdorff", by_element=TRUE))
buffer_hausdorff <- as.numeric(st_distance(st_geometry(buffered), reference, which="Hausdorff", by_element=TRUE))
result <- list(activities=nrow(xy), activities_outside_buffered_domain=outside,
  input_crs=st_crs(region)$epsg, output_crs=st_crs(buffered)$epsg,
  network_buffer_m=request$network_buffer_m, snap_grid_m=1L,
  unbuffered_hausdorff_m=hausdorff, buffered_snapped_hausdorff_m=buffer_hausdorff,
  buffered_area_km2=as.numeric(st_area(buffered))/1e6,
  reference_area_km2=as.numeric(st_area(reference))/1e6,
  symmetric_difference_area_m2=sum(as.numeric(st_area(st_sym_difference(st_geometry(buffered), reference)))),
  R=R.version.string, platform=R.version$platform,
  sf=as.character(packageVersion("sf")), lwgeom=as.character(packageVersion("lwgeom")),
  external_libraries=as.list(sf_extSoftVersion()),
  network_generation_executed=FALSE, simulation_executed=FALSE)
write_json(result, "/smoke/r_geometry_result.json", auto_unbox=TRUE, pretty=TRUE, digits=16)
stopifnot(outside == 0L, hausdorff <= 0.1, buffer_hausdorff <= 2,
          all(st_is_valid(buffered)), as.numeric(st_area(buffered))/1e6 <= request$max_buffered_area_km2)
cat("R geometry-only smoke passed; no OSM extraction or simulation executed.\n")
'''


def run_smoke(experiment_id: str | None = None) -> Path:
    experiment_id = experiment_id or f"geometry_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:6]}"
    network_domain.validate_output_name(experiment_id)
    directory = ROOT / "output/activity_domain_smoke" / experiment_id
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {"status": "preparing", "started_at": utc_now(),
                "network_generation_executed": False, "simulation_executed": False,
                "plans": file_evidence(PLANS, checksum=True), "script": file_evidence(Path(__file__), checksum=True)}
    def save():
        (directory/'smoke_manifest.json').write_text(json.dumps(manifest, indent=2, allow_nan=False)+'\n')
    save()
    old_data, old_output = network_domain.DATA_DIR, network_domain.OUTPUT_DIR
    try:
        inspected = json.loads(subprocess.run(['docker', 'image', 'inspect', 'matsim-network-generator'],
            check=True, capture_output=True, text=True).stdout)[0]
        fingerprint = source_fingerprint([ROOT/'docker/network.Dockerfile', ROOT/'vendor/network'])
        if (inspected.get('Config', {}).get('Labels') or {}).get(FINGERPRINT_LABEL) != fingerprint:
            raise RuntimeError('Cached image does not match R source; no automatic build allowed.')
        manifest.update(image_id=inspected['Id'], image_platform=f"{inspected['Os']}/{inspected['Architecture']}",
                        generator_source_fingerprint=fingerprint,
                        domain_module=file_evidence(ROOT/'wrapper/network_domain.py', checksum=True))
        network_domain.DATA_DIR, network_domain.OUTPUT_DIR = directory/'data', directory
        domain = network_domain.prepare_activity_domain(PLANS, output_name='geometry', plans_crs=7899,
            max_buffered_area_km2=25, network_buffer_m=500)
        # Keep the R mount layout fixed; only this new smoke tree is writable.
        (directory/'domain').mkdir()
        (directory/'domain/domain_manifest.json').write_bytes(domain.evidence_path.read_bytes())
        driver = directory/'geometry_smoke.R'
        driver.write_text(R_SMOKE)
        command = ['docker', 'run', '--rm', '--pull', 'never', '--network', 'none',
            '--cpus', '1', '--memory', '2g', '-v', f'{directory}:/smoke',
            '-v', f'{PLANS}:/source/plans.xml:ro', '-e', 'RENV_CONFIG_AUTOLOADER_ENABLED=false',
            '--entrypoint', 'Rscript', inspected['Id'], '--vanilla', '/smoke/geometry_smoke.R']
        manifest.update(status='running', command=command, driver=file_evidence(driver, checksum=True))
        save()
        run_logged(command, log_path=directory/'console.log', cwd=ROOT)
        manifest['plans_unchanged'] = sha256_file(PLANS) == manifest['plans']['sha256']
        if not manifest['plans_unchanged']:
            raise RuntimeError('Original plans hash changed.')
        manifest.update(status='completed', finished_at=utc_now(), generator_returncode=0,
            result=json.loads((directory/'r_geometry_result.json').read_text()),
            artifacts={name: file_evidence(directory/name, checksum=True) for name in
                       ['r_geometry_result.json', 'console.log', 'geometry_domain/domain_manifest.json',
                        f'data/{domain.region_file}', 'geometry_smoke.R']})
        save()
        return directory
    except BaseException as exc:
        manifest.update(status='failed', finished_at=utc_now(),
                        error={'type': type(exc).__name__, 'message': str(exc)})
        save()
        raise
    finally:
        network_domain.DATA_DIR, network_domain.OUTPUT_DIR = old_data, old_output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Explicitly execute the geometry-only check')
    parser.add_argument('--experiment-id')
    args = parser.parse_args()
    if not args.run:
        parser.error('--run is required; no automatic R execution')
    print(run_smoke(args.experiment_id))
