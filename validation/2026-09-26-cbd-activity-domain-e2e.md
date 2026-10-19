# Fresh normal-API CBD activity-domain run — 26 September 2026

## What was actually executed

After the nine-run study completed and the job queue was idle, the local service
was restarted to load the new normal CBD pipeline. One request was submitted to
`POST /pipeline/run` with `{"region":"cbd"}`. This is the website's normal API,
not the separate expanded-network study script and not an existing-result replay.

- Job: `05316510-b43e-47f5-bb0a-66f385f554e0`
- Run: `cbd_demo_20260926T063657Z_2dde1f`
- Profile: `cbd_activity_domain_v2`, **experimental**
- Run-record start: 2026-09-26T06:36:57.673796+00:00
- Run-record finish: 2026-09-26T06:48:29.249131+00:00
- Elapsed: approximately 11 minutes 32 seconds
- API job: `completed`, `error: null`, result source `new_run`

The request generated fresh demand, fresh network, a fresh MATSim run and fresh
analysis in previously unused directories. It did not overwrite historical
outputs, clip/delete activity points or reuse a previous run's result on failure.
The existing Python environment, local source data and source-matching cached
Docker images were reused; no installation or cold-machine reproduction occurred.

## Actual results and domain gate

| Evidence | Observed result |
|---|---:|
| Synthetic persons | 1,037 |
| Selected plans / activity occurrences | 1,037 / 4,660 |
| Missing, invalid or nonfinite activity coordinates | 0 |
| Activities inside cleaned network node bbox | 4,660 / 4,660 (100%) |
| Cleaned network nodes / directed links | 3,129 / 11,331 |
| Usable explicitly car-enabled segments | 6,427 |
| Geometric nearest-car-segment distance, mean / p95 / max | 5.764 / 22.832 / 206.982 m |
| Activity occurrences more than 100 m / 500 m from those segments | 10 / 0 |
| MATSim iterations | 0, 1, 2 |
| Output trips | 3,623 |
| Car / bike / PT / walk trips | 934 / 114 / 977 / 1,598 |
| Required artifacts | 18/18 present and nonempty |
| Native shutdown | Normal; no unexpected-termination marker |

The domain manifest verifies finite coordinates, unchanged plans and region,
unchanged activity count, finite network nodes, usable car links and 100% bbox
inclusion **before** simulation. The pipeline then rechecks plans/network hashes
at the simulation boundary. Saved copies of the domain manifest and audit match
their originals. All SHA-256-bearing run artifacts were independently rechecked.

The generated demand's hash happens to equal the earlier frozen demand under the
same seed and inputs; that equality was measured, not assumed or achieved by
copying the earlier file. Hashes:

| Artifact | SHA-256 |
|---|---|
| New demand `8.xml/plan.xml` | `3b886ede8f0d5fac1fb17bf3602d2b09d0ada3dd986f231c5a00d0bbffaf872c` |
| New network `network.xml` | `48d745864812fc5b50f36f09f2975a2baf1ef1dc86b25bb5ac08b176bd269532` |
| Post-cleaning coverage audit | `3441d9615f1a9545ef94599b8ca6d00d0b590e5672fbb7398d5bf6e364cca7b6` |

The plain XML geometry audit deliberately does not infer a CRS from coordinates;
metre interpretation here additionally relies on the workflow's recorded
EPSG:7899 input/output contract. Nearest-segment distance ignores barriers,
direction and actual MATSim activity-link assignment. Bbox inclusion is not
route feasibility, source completeness, calibration or policy-effect validation.

## Where to verify locally

- `output/run_records/cbd_demo_20260926T063657Z_2dde1f/run_manifest.json`
- `output/run_records/cbd_demo_20260926T063657Z_2dde1f/pipeline.log`
- `output/cbd_demo_20260926T063657Z_2dde1f_domain/domain_manifest.json`
- `output/cbd_demo_20260926T063657Z_2dde1f_domain/coverage_after.json`
- `output/network_work/cbd_demo_20260926T063657Z_2dde1f_network/runner_manifest.json`
- `output/cbd_demo_20260926T063657Z_2dde1f_sim/summary.md`
- Native `logfile.log`, `scorestats.txt`, trip/event outputs and scene in that
  same simulation directory; process logs use the same unique run prefix.

Opening `/?run=cbd_demo_20260926T063657Z_2dde1f_sim` after completion is explicitly
**recorded-result replay**, not a new simulation. The API submission above did
not exercise a physical mouse click on the Generate button; job/state fixtures
and actual replay-browser checks are distinct verification layers.

Actual in-app Chromium verification displayed that exact run identifier and
the 1,037-person / 3,623-trip / three-iteration values. Both charts loaded,
the city and new network rendered, and the replay label was present. No browser
console warning/error was recorded during these checks.

The recorded Git HEAD is `55a3dd89931dce44b0c92f6cf9b3a44dca38eebf`, with a dirty
working tree. It is not an immutable release tag. Generator source/image hashes,
dependency fingerprints and exact execution inputs are retained in the records;
the integration is not claimed to be reproducible from that commit alone.

This completes the new-entry execution check deferred in
[the domain implementation handoff](2026-09-26-normal-activity-domain.md).
The old geometry-only smoke and separate nine-run experiment remain separate
evidence. See [workbench verification](2026-09-26-impact-workbench.md) for UI and
deterministic tests. No calibration, convergence, engineering-design or
long-term development inference follows from successful execution.
