# Local validation report — 2026-09-09

## Execution context

- Latest execution time (UTC): `2026-09-09T23:13Z`
- Base Git commit: `55a3dd89931dce44b0c92f6cf9b3a44dca38eebf`
- Working tree: dirty (the tested reliability and documentation changes were not committed)
- Python: `3.11.9`
- Test command: `.venv/bin/python -m unittest discover -s tests -v`
- Python environment: a newly created project-local `.venv`, populated only
  from `requirements.txt` for this check

## Result

- Discovered: **29** tests
- Passed: **29**
- Failed: **0**
- Errors: **0**
- Skipped: **0**
- Runtime reported by the latest unittest run: **0.018 seconds**

The test names and scope are in `tests/`. They cover API input validation,
preflight checks, durable job history, run/result binding, failed-run handling,
result catalogue behavior, stable run-ID binding, GDAL temporary-directory
configuration, exact OSM input pinning, Docker source-fingerprint invalidation,
deterministic demand seed propagation, selected 3D data-style helpers, IF Line
network edits, illegal intervention values, controlled-comparison aggregation
and IF Line API job/run-ID binding.

## Additional syntax checks

- Creating `.venv` and installing `requirements.txt`: passed.
- `.venv/bin/python -m compileall -q wrapper tests`: passed.
- R parse check for `vendor/demand/R/run_from_env.R` and
  `vendor/demand/R/makeExamplePopulation.R`: passed. The local R process emitted
  locale warnings; these did not indicate an R syntax failure.
- `git diff --check`: passed.

## Upstream R test execution

The demand image's existing `vendor/demand/tests/testthat/` suite was run in
the pinned R container. The first unmodified invocation found two problems:

- `testPlace.R` errored because the upstream test harness does not define
  `output_crs`.
- `testPlan.R` failed because the generated `plan.csv` MD5 did not match the
  stored byte-for-byte snapshot.

The suite was then rerun with `output_crs <- 28355`, the CRS embedded in its
expected SQLite fixture. `testPlace.R` passed; `testPlan.R` remained as **one
failure**, accompanied by four ggplot warnings. The failing snapshot was not
deleted or regenerated. This indicates that the legacy byte-level fixture is
not reproducible in the current pinned container, even though the fixed demo's
actual demand stage completed.

The single `vendor/network/tests/testthat/testMATSimNetworkGenerator.R` test was
not executed independently: it calls the old `makeNetwork("test")` city setup,
whereas the wrapper now requires explicit environment-provided region inputs.
The end-to-end run below exercised network generation with those current inputs.

## Fresh end-to-end execution

- Run ID: `cbd_demo_20260908T205520Z_16879d`
- Started: `2026-09-08T20:55:20.252202+00:00`
- Finished: `2026-09-08T21:10:06.251298+00:00`
- Elapsed: **885.999 seconds**
- Network: **684 nodes, 2,464 links**
- Synthetic agents: **1,037**
- Trips: **3,623**
- Score rows: **3** (iterations 0, 1 and 2)
- Required artifacts: **16/16 present and non-empty**
- MATSim shutdown marker: present; unexpected-termination marker: absent
- Bounding-box coverage diagnostic: **69.1%**

Primary evidence:
`output/run_records/cbd_demo_20260908T205520Z_16879d/run_manifest.json`.
The run used a new output ID and preserved prior outputs. It also rebuilt Docker
images whose recorded source fingerprint did not match current vendored code.

## Web replay acceptance

The local FastAPI service was started from the current working tree and the
browser UI was checked against the fresh run above. The following were observed:

- `/system/status` reported the environment ready and showed Python `3.11.9`,
  Docker `29.6.1`, 14 CPUs and 35.2 GB allocated memory.
- `/runs` listed `cbd_demo_20260908T205520Z_16879d_sim` as completed, with no
  missing required result files, a 3D scene and a completed run record.
- Opening that entry displayed run ID `cbd_demo_20260908T205520Z_16879d`,
  1,037 agents, 3,623 trips and 3 iterations from the same result directory.
- The UI labelled it **“已有结果回放 · 不是刚刚执行的实时仿真”** and linked
  to the matching run manifest; it did not present the replay as a new run.
- The mode table, both charts and the 3D scene rendered. No browser console
  warnings or errors were recorded during this check.

The failure/mismatch paths are covered by automated tests: a failed background
job clears its result, a result with the wrong run ID is rejected, a failed run
record is not treated as completed, and the frontend clears any displayed result
before starting a new run and again when polling reports failure.

## IF Line controlled-branch acceptance

Two new branches were run from the recorded CBD baseline
`cbd_demo_20260908T205520Z_16879d_sim`. Both reused the exact same synthetic
plans file, MATSim seed 4711 and iterations 0–2. They created independent
network/config/simulation directories and finished with MATSim's clean-shutdown
marker.

1. `if_20260909T230052Z_3e668a`: link 255 speed changed from 50 to 30 km/h.
   Only that directed link differed in the proposal network. The proposal kept
   1,037 agents and 3,623 trips; car mean trip time changed by +1.060 seconds
   and all-mode trip-weighted mean time by +0.289 seconds. End-to-end duration
   was 568.317 seconds because the source-fingerprinted MATSim image was rebuilt.
2. `if_20260909T231212Z_ad7789`: car mode removed from both directions of
   links 890 and 2071 while bike and walk remained. Only those two directed
   links differed. The proposal kept 1,037 agents and 3,623 trips; car mean
   trip time changed by +7.595 seconds, all-mode mean time by +1.958 seconds,
   and all-mode mean distance by +23.309 metres. With the image cached, the
   recorded duration was 35.420 seconds.

For both branches, `scenario.json`, `comparison.json`, the run manifest,
modified network, generated config, events, trips, persons, log, summary and 3D
difference scene were present and non-empty. The web UI was opened against the
second branch: it displayed the matching run ID, four summary deltas, per-mode
changes, changed link IDs, evidence links and the 3D difference legend. The
scene automatically focused the intervention and rendered direct links blue,
measured delay reductions green and increases red. No browser console warnings
or errors were recorded during the final acceptance check.

## Limits of this report

This is local software/pipeline validation, not transport-model calibration or
scientific validation. The 69.1% figure is a rectangular-bounds diagnostic, not
strict polygon coverage. No observed traffic counts, predictive accuracy,
convergence analysis or real-world transport improvement comparison was made.
The IF Line results are single deterministic counterfactual runs under the
recorded assumptions; they do not establish causality, uncertainty bounds,
induced demand, land-use change or long-term urban-development effects.
