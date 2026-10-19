# Historical protocol: reproduce the small CBD capacity experiment

This is a bounded Data Ops/transport-simulation demonstration, not a production
planning tool, calibrated forecast, or model of long-term city development.

## Current portfolio entry

This capacity-only protocol is retained for reproducibility. The featured
portfolio case is the expanded **three-seed, nine-run, ten-iteration** closure
and alternative-road experiment in [PLANNING_CASE.md](PLANNING_CASE.md).
Start with [RUNNING.md](RUNNING.md) and the [offline showcase](../portfolio/index.html).

The original execution below used a warm Mac environment. The October Windows
migration separately built all three images and completed a fresh short run with
existing network/demand inputs; it did not regenerate every external input.

## What belongs to which project

- Upstream MATSim supplies the Java simulation engine and its native event,
  score and mode-share outputs. The vendored MATSim Melbourne R projects supply
  network and synthetic-demand generation, with local compatibility patches.
- This repository adds Python/Docker orchestration, matched-region preparation,
  API/job management, preflight checks, run evidence, aggregate analysis,
  counterfactual road changes and a browser viewer. Do not describe the engine,
  upstream generators or third-party data as independently authored here.
- This case demonstrates operating and checking those pieces together. Personal
  contribution and AI assistance should be described accurately by the owner.

## Prerequisites and data

1. Use Python 3.10+ and a running Docker Desktop. The local verification uses
   macOS with an existing Python 3.11 environment and cached Docker images.
2. Create/activate a project-local environment and install `requirements.txt`
   as described in the root README. Do not rely on globally installed packages.
   Prepare a source-matching network image explicitly with
   `python -c 'from wrapper.runner import build_image; build_image()'` before the
   cached-only CBD workflow; this build may download dependencies.
3. Prepare the files listed in [DATA_PREPARATION.md](DATA_PREPARATION.md).
   The boundary is `data/sample_region.geojson`; the fixed road input is the
   locally supplied Victoria OpenStreetMap extract. The ABS/VISTA-derived inputs
   generate **synthetic agents**, not identified residents' observed trajectories.
4. Run `python -m wrapper.cli doctor`. Resolve blocked checks before submitting.
   Optional elevation/building data enrich the viewer but are not traffic
   calibration data. Raw data and event streams are not bundled for publication.
5. Run `python -m wrapper.server` and open the local web UI. It waits for
   readiness and writes service logs independently of the terminal.

The historical execution of this protocol reused existing data, Python
dependencies and Docker caches. It was not a clean-machine build. The separate
October Windows check has a different scope, recorded in the current validation notes.

## A. Generate a new baseline

Use the website's CBD option, or this equivalent HTTP request while the service
is running:

```bash
curl --fail-with-body -X POST http://127.0.0.1:8000/pipeline/run \
  -H 'Content-Type: application/json' -d '{"region":"cbd"}'
```

The response contains a new `job_id` and `run_id`. Save both. Check
`GET /jobs/<job_id>` until `completed` or `failed`; do not resubmit merely because
the command returned quickly. Network/demand generation is a background job.
If it fails, inspect the returned error, run manifest and process logs. Do not
replace it with a previous successful result.

The current `cbd_activity_domain_v2` uses the original region with a 500 m SA1
selection buffer, then freezes the generated demand and builds the network around
its activity bbox with an independent 500 m buffer (CBD area budget 25 km²).
Nonfinite or out-of-network-bbox activities stop the flow before simulation.
Demand sample parameter is 5%, plan-generator parameter 500, demand/MATSim seeds
4711, and iterations 0–2 inclusive. The generator parameter is **not** a hard cap
on agents. Only report counts actually produced by this new run. The older
`cbd_small_v1` capacity case remains historical evidence with a known geographic
mismatch; do not attribute its numbers to the new interface.

Outputs are separate under `output/<run_id>_network`, `_demand`, `_sim_config`
and `_sim`. The record is `output/run_records/<run_id>/run_manifest.json`.
External-process console logs live in `output/process_logs/`. Domain preparation
and post-cleaning audit are in `output/<run_id>_domain/` and snapshotted under the
run record; network scratch/provenance is unique to `output/network_work/<run_id>_network/`.

## B. One predeclared intervention

This case is a stress test: reduce one busy road's modelled capacity to **50% of
its baseline value**, including exact reverse car links if present. Do not alter
speed, lane count, geometry, population, seeds or iterations.

After A completes, request `GET /ifline/network/<run_id>_sim`. Among links with
`car_editable=true`, positive `capacity` and positive `volume`, select the
largest `volume`; ties use the lexicographically smallest string `id`.
`volume` is the final event file's entered-link count, not unique vehicles,
real-world observed demand, or a peak-hour rate. This selection uses only the
baseline, before observing any proposal outcome.

Submit to `POST /ifline/run`:

```json
{
  "baseline_run": "REPLACE_WITH_NEW_BASELINE_sim",
  "name": "CBD reproducibility case - busy link capacity 50%",
  "intervention": {
    "type": "capacity_scale",
    "link_id": "REPLACE_WITH_SELECTED_LINK_ID",
    "value": 50,
    "include_reverse": true
  }
}
```

The value is a **percentage**, not a multiplier: use `50`, not `0.5`.
Save the selected link, rule, returned job/run IDs and payload before analysing
results. Monitor this proposal's own job. It reuses baseline plans and writes an
independent network and simulation directory. Never edit the baseline in place.

## C. Verify and export aggregate evidence

When both jobs have completed, run from the repository root:

```bash
python -m scripts.report_demo_comparison \
  --baseline REPLACE_WITH_NEW_BASELINE_sim \
  --proposal REPLACE_WITH_NEW_PROPOSAL_sim \
  --destination validation/REPLACE_WITH_NEW_REPORT_DIRECTORY
```

The reporting command does not run a simulation. It requires successful run
records and clean MATSim shutdowns, checks plan-file hashes, compares actual
configuration except network/output paths, verifies capacity-only XML changes,
and recomputes the stored comparison from the trip outputs. It refuses existing
report destinations. It exports `README.md`, `mode_comparison.csv` and
`evidence.json` containing aggregates, checks and artifact hashes—not agent rows.

Run deterministic checks separately:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

Open the same new proposal in the website's existing-results or scenario list.
Opening it after completion is **existing-result replay**, not another live
simulation. Match the displayed baseline/proposal identifiers with the report.
The web comparison should agree with the CSV (allowing display rounding).

## Interpreting the result

- Report overall and car-mode travel time, trip distance and recorded trip counts.
  The current overall mean is weighted by each metric's valid count, not an
  unweighted mean of mode averages; missing/invalid measurements never become zero.
- Preserve a null, tiny or adverse result; do not rerun alternative roads until
  a favourable headline appears. A capacity change can be non-binding in a small
  sample and can trigger different rerouting choices.
- A single seed and three iterations do not establish convergence, uncertainty,
  statistical significance, causality in real traffic, or long-term development.
- The current public-transport mode is teleported, not a GTFS/timetable simulation.
  QSim may adjust effective capacity; inspect native warnings and output-network
  attributes before interpreting input capacity as realised throughput.
- Source/input snapshots and existing caches constrain reproducibility. Repeating
  the experiment is a workflow check, not a promise of byte-identical outputs.
- Document which tests actually ran and their pass/fail/skip counts. Unit tests
  and a locally completed run are distinct kinds of evidence.

## Defensible portfolio narrative

Describe this as a **personal transport-data pipeline prototype**. A useful
interview story is: define a small scenario, prepare matching inputs, run through
an auditable job, diagnose a failure, verify the repair, then compare one recorded
intervention under explicit controls. Do not call it employment, independent
authorship of upstream tools, or a proven improvement to Melbourne traffic.
