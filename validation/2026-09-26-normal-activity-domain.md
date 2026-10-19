# Normal CBD activity-domain workflow v2 — implementation handoff

**Follow-up:** the handoff below records the implementation/smoke checkpoint.
A separate fresh normal API run subsequently completed at 06:48:29 UTC:
[actual end-to-end evidence](2026-09-26-cbd-activity-domain-e2e.md). Its successful
execution does not promote the experimental profile to a calibrated model.

## Status and scope

Implemented and ready for a separately authorized normal-pipeline end-to-end
regression. **No full network generation, demand generation, or MATSim run was
executed for this change.** Existing cases, original PBF/plans/networks, old run
records, vendor R source, dependency manifests, READMEs and UI were not edited by
this task. Unit-test messages mentioning generators/simulation come from mocks.

The normal CBD profile is `cbd_activity_domain_v2`, with `experimental` status.
Other region profiles retain their region-first strategy and explicitly remain
experimental. Historical `cbd_small_v1` records are not migrated or relabelled.
Passing output/coverage checks is not transport validity or convergence evidence.

## Public interface and ownership

`wrapper.network_domain.prepare_activity_domain(plans_path, *, output_name,
plans_crs, max_buffered_area_km2, network_buffer_m=500) -> ActivityDomain`

The frozen result contains `region_file` (relative to data/), `evidence_path`,
`plans_path`, `plans_sha256`, `region_sha256`, `network_buffer_m`, and a
`coverage_path` property. Preparation never calls Docker/R/MATSim.

Initial supported demand is EPSG:7899, one selected or unmarked single plan per
person, finite-coordinate activities, and no old-network link/route bindings.
Ambiguous/multiple plans, empty persons/plans, degenerate or over-budget domains,
nonfinite/invalid/missing coordinates and bound plans fail explicitly rather than
being skipped. No person identifiers or individual activity coordinates are put
in public aggregate evidence or console summaries.

Python computes the native bbox, densifies edges at <=100 m spacing and uses
existing rasterio to serialize an unbuffered EPSG:4326 GeoJSON. It checks the
projection roundtrip within 0.1 m. The generator alone applies the network-only
buffer in EPSG:7899, followed by its existing 1 m grid. A 2 m conservative
rounding allowance is used **only in the area-budget calculation**, not added to
the emitted geometry or the 500 m network buffer. CBD's explicit budget is
25 km²; this is not a universal city limit.

`run_scenario(..., *, network_domain="region", network_buffer_m=500,
max_network_area_km2=None)` keeps its `(network_dir, demand_dir)` return contract.
CBD pipeline explicitly opts into `activity_bbox`; old callers remain region-first.

New-strategy ordering:

1. Validate options/local PBF and source-matching cached network image **before
   any SA1/demand work**. Missing/stale image or unavailable Docker gives an
   actionable explicit-build/start-Docker error; no hidden network-image build.
2. Select whole SA1s using the original region and original demand buffer.
3. Generate demand once, then prepare/freeze the activity domain and plans hash.
4. Build the network using the generated GeoJSON and independent 500 m buffer.
5. Save the cleaned-network coverage audit, then require unchanged inputs,
   matching activity count, all finite activities inside final node bbox (100%),
   finite network nodes and a usable explicit-car network.
6. Only on success may the caller cross into MATSim. Pipeline rechecks the exact
   plans and network hashes at that seam.

Low coverage or nonfinite coordinates are fatal workflow precondition failures,
not warnings and not an automatic claim that a transport model is invalid.
The generic `audit_coverage()` remains read-only and makes no pass/fail decision.

## Durable artifacts and failure recovery

- `data/<run_name>_activity_bbox_<unique>.geojson`: new unbuffered input geometry.
- `output/<run_name>_domain/domain_manifest.json`: aggregate inventory, source
  hashes, CRS/method, domain budget, lifecycle, failure and post-cleaning gate.
- `output/<run_name>_domain/coverage_after.json`: generic aggregate audit, written
  **before** applying the strict gate. Absent if generation never reached audit.
- `output/run_records/<run_name>/artifacts/domain_manifest.json` and
  `coverage_after.json`: byte/hash-checked copies of available evidence on success
  **and failure**. Referenced by `network_domain_manifest` and
  `network_coverage_after` run-record artifact keys. Missing files are recorded as
  missing rather than invented.
- `output/network_work/<run_name>_network/runner_manifest.json`: pinned image,
  source fingerprint, exact command/environment, input hashes and required output
  artifact hashes. Unique scratch/download directories sit beside it.
- `output/<run_name>_network/network.xml` and `network.sqlite`: both must exist
  and be nonempty before runner completion; the scenario audit handles semantic
  coordinate/coverage conditions. Exit 0 without outputs is a failure.

The network runner exclusively allocates each workspace, rejects existing output
names, copies the original PBF into scratch, and mounts original data read-only.
OSM GPKG/unconfigured SQLite/temp paths no longer share global filenames. With a
fixed PBF it disables container networking/pulls and uses Rscript `--vanilla` plus
disabled renv autoload. Failed workspaces are retained; retry with a new name.
No old directories need deletion or in-place repair.

## Checks actually run

```bash
.venv/bin/python -m unittest discover -s tests -q
```

Final observed result: **257 tests passed**, 1.437 s, 2026-09-26 around 06:31 UTC.
The targeted additions exercise geometry/selection/overflow rejection, source
preservation, buffers/order, strict coverage failures, early cached-image gate,
runner isolation and missing/empty output rejection, run-record failure evidence,
simulation suppression, post-gate input mutation and legacy profile behavior.

```bash
.venv/bin/python scripts/smoke_activity_domain_geometry.py --run \
  --experiment-id cbd_activity_domain_v2_geometry_20260926_r02
```

That name is now used and cannot be overwritten; choose a new name to repeat.
The cached-image geometry-only smoke ran with one CPU, 2 GiB memory, no network,
no pull, no package installation and no PBF mount/read. It called only XML,
GeoJSON, CRS, buffer/grid and geometry operations, never `makeNetwork`/MATSim.

Actual manifest: `output/activity_domain_smoke/cbd_activity_domain_v2_geometry_20260926_r02/smoke_manifest.json`.

| Evidence | Observed value |
| --- | --- |
| UTC started / completed | 06:31:23.586883 / 06:31:26.152242 |
| Status / R exit | completed / 0 |
| Activity occurrences tested | 4,660 |
| Outside final buffered geometry | 0 |
| Unbuffered native vs GeoJSON roundtrip Hausdorff | 3.6369309182775458e-9 m |
| Buffered/snapped Hausdorff | 0 m |
| Buffered geometry symmetric-difference area | 0 m² |
| Both buffered areas | 22.699982 km² |
| Original plans hash unchanged | true |
| Runtime | R 4.2.1, sf 1.0.15, lwgeom 0.2.13 |

The image identity was
`sha256:81312b9c671161a8a8ce8349ab53514396cee30d8389bdd5c4bb1beb24dd1dca`.
The first smoke is also preserved; r02 only normalizes empty symmetric-difference
geometry to scalar area zero and records full numeric precision. Both passed.
Current smoke-script and domain-module hashes were rechecked against r02.

Focused read-only test-gap inspection used
`.venv/bin/python -B .agents/skills/test-gap-audit/scripts/coverage_map.py --top 8`
plus direct source/test inspection. The heuristic map is not coverage percentage
evidence. The key uncovered runner false-success seam was closed with missing/
empty XML/SQLite tests; stale-image rejection now has both scenario and pipeline
tests. `git diff --check` passed for the modified tracked production files.

## End-to-end handoff (command not executed)

After the running case jobs finish, a new normal regression can use the same
entry used by the API:

```bash
.venv/bin/python -c 'from wrapper.pipeline import run_full_pipeline; result = run_full_pipeline(region_key="cbd"); print(result["run_id"])'
```

This is an **expensive full pipeline**: it generates new demand and network,
runs MATSim with current normal defaults (iterations 0..2), and renders analysis.
It does not reuse or alter the frozen nine-run case inputs. Network-image build
is an explicit prerequisite if the cached image is missing/stale. The legacy
CLI function name `run_verified_demo` remains for compatibility only; the profile
identity and run verification status are experimental.

Acceptance requires the recorded v2 profile, a completed 100% post-cleaning gate,
source/artifact hash agreement, required simulation outputs, clean shutdown and
analysis artifacts. Until that run is observed, this change has unit/geometry
verification, **not new-entry end-to-end validation**. Do not automatically
promote the profile based on this smoke or on old r03/case results.

Still untested here: full OSM extraction through the refactored normal runner,
real Docker interruption/daemon loss/disk-full recovery, and actual new-entry
MATSim routing/link assignment. The smoke proves the domain geometry seam only.
