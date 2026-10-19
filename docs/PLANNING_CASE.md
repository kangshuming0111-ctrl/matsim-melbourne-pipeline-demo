# Repeated-seed closure and alternative-road case

`scripts/run_planning_case.py` prepares and explicitly executes a bounded local
MATSim experiment. Each seed has a **fresh baseline → closure → closure plus new
ground road** triple. Both branches anchor the fresh baseline; the alternative
contains both operations. One frozen copy of the existing network and one frozen
copy of the existing demand plans are reused throughout. Demand is never regenerated.

This is conceptual option screening with fixed synthetic people and activity
locations. More iterations and seeds do not establish convergence, engineering
feasibility, calibrated traffic forecasts, or long-term urban development.

The source uses a small CBD network with population/activity geography inherited
from whole SA1 areas. A separate coverage audit flagged geographic mismatch; the
original source record reports network/demand **bounding-box coverage 0.691416**,
which is not proof of connected route coverage. This original-input case may
demonstrate the workflow, but cannot establish geographically sound CBD policy
benefits. Expanded-network preparation/checks are a separate experiment and must
not be mixed into these fixed triples. Executions, results and aggregates retain
this geographic caveat explicitly.

## Current decision: expanded network, fixed population, geometric detour

The old small-network batch is stopped and must not be resumed for this study.
Its seed 4711 baseline completed; its seed 4711 closure was interrupted at
2026-09-26T05:57:56Z. No old-scope alternative or other-seed run started. The case
manifest says `interrupted`; every native output, failed attempt, and log is
preserved. The completed baseline visible in the UI is real, but is not a completed
three-scenario experiment.

The coverage agent generated a separate activity-bounding-box +500 m network
in EPSG:7899 (about 22.7 km²), retaining the same 1,037 people and all 4,660 activity
occurrences. The completed generation attempt is
`output/domain_experiments/cbd_fixed1037_bbox500_20260926_r03/`; its manifest
records completion at 2026-09-26T06:09:52.705565Z and all original input hashes
unchanged. Readiness means `manifest.json` says `completed`, not merely that a
directory exists.
Earlier failed attempts remain preserved under their original names.

The cleaned network contains 3,129 finite nodes and 11,331 directed links,
including 6,427 usable car links. All 4,660 activities fall within its node bbox;
nearest-car-segment distances have mean 5.764 m, p95 22.832 m and maximum
206.982 m (10 activity occurrences exceed 100 m; none exceed 500 m). These remain
planar coverage diagnostics. All four corridor anchors map at exactly 0 m:
8844→28333, 8954→29264, 8695→27931 and 9032→29548. The closure is now
3734/9256, and the alternative endpoints are 27931/29548.

The one bootstrap baseline **completed** at 2026-09-26T06:12:25.609098Z after
approximately 98 seconds: `cbd_expanded1037_bootstrap_baseline_sim`, seed 4711,
iterations 0–9, all 1,037 original people. Its native results, run record and
skyline pass the case runner's verification and `resolve_run_assets`.

The review-ready case is `cbd_expanded1037_detour_10it_review_r02`. It preserves
the same predeclared geometry, adding uncapped building-source evidence after
discovering the display-scene limit. The first prepared expanded case without
`_r02` remains unchanged for audit; the strengthened loader rejects its incomplete
clearance evidence before any simulation. Do not run that first preparation.
The main agent authorized the nine-run batch after the checks below passed.
It completed all nine runs on their first attempts at
**2026-09-26T06:32:36.065605Z** (16:32:36 Melbourne), after starting at
06:17:50.460529Z: 885.605 seconds total. Every seed, including 4711, received a
fresh baseline; bootstrap was not substituted for one of the nine runs.
The r02 manifest is `completed`, with no error and no incomplete seed.

```sh
.venv/bin/python scripts/run_planning_case.py --bootstrap \
  --network-dir output/domain_experiments/cbd_fixed1037_bbox500_20260926_r03/expanded_network \
  --source-run cbd_demo_20260926T050044Z_a805bd_sim \
  --case-id cbd_expanded1037_bootstrap

.venv/bin/python scripts/run_planning_case.py --prepare \
  --source-run cbd_expanded1037_bootstrap_baseline_sim \
  --network-dir output/domain_experiments/cbd_fixed1037_bbox500_20260926_r03/expanded_network \
  --alternative-route detour \
  --case-id cbd_expanded1037_detour_10it_review_r02
```

These are the recorded bootstrap/preparation commands, not commands to repeat
against their now-existing destinations: the runner refuses to overwrite them.
They require the named generation to have completed. Bootstrap checks
the generation's completion record/log, network XML geometry and references,
positive link attributes, and inclusion of every fixed activity in the network
bounding box. The coverage agent's richer route-distance diagnostics still need
review; a rectangle alone cannot prove a usable connected route.

Nested expanded-network inputs are copied without alteration to a unique
`output/<bootstrap>_inputs_network/network.xml` snapshot to match the existing
runner's basename interface. The original network's path and SHA-256 remain in
the bootstrap record. `--prepare --network-dir` accepts either that recorded
snapshot or its byte-identical recorded origin. It **cannot** relabel an old
simulation as if it used a new network: a mismatched override requires bootstrap
first. The plans' SHA-256 remains
`3b886ede8f0d5fac1fb17bf3602d2b09d0ada3dd986f231c5a00d0bbffaf872c`.

The original corridor is defined by the four coordinates below, not by assuming
regenerated integer IDs remain stable. Each endpoint must resolve to exactly one
car node within 1 m. Each closure direction must have one direct car link between
its mapped endpoints. Ambiguous nodes, more distant matches, missing directions,
or a newly split closure require review; the runner never picks a different
corridor to obtain a desirable result. The new spec records mapped IDs and
displacements, and the alternative ends at the exact mapped nodes.

`--alternative-route detour` selects a **predeclared 14-point, 356.159 m ground
alignment** between the same endpoints. It was chosen before expanded-network
simulation by a geometric visibility graph around known footprints buffered by
6.5 m (4.5 m road half-width +2 m margin), within 150 m of the original chord,
using shortest path length only. Edges shorter than 2 m were rejected. Candidate
edges following an existing car segment within 4.5 m for over 20 m at less than
20° difference were excluded. The selected control points are stored in
`DETOUR_POINTS` in the runner and copied into the immutable case plan. There is
no runtime route optimization or traffic-outcome search.

The expanded baseline's scene contains 2,999 building features after display
capping and duplicate removal. The compiler's 9 m corridor and 13 m margin screen
both report **zero known conflicts**, but the display cap omitted 2,622 source
features. Therefore r02 also checks the **uncapped 5,622-feature source** in
`data/landmarks/v2/cbd.json`, preserving holes, CRS projection and polygon-repair
diagnostics. The local 150 m envelope contains 59 source features / 60 polygon
parts, with no invalid or repaired footprints. Both source-level corridor and
margin checks also return **zero**. The route plus its 6.5 m half-width margin
lies inside the cache's geographic extent. This cache does not cover every
building in the entire expanded network and does not establish OSM completeness.

The report records the source hash
`f212b7f586704103fb829d7f9ec308e88c9b5b1674df1fc8dfb8509a70cedd9f`.
Missing uncapped evidence when the scene is capped, an invalid source footprint,
an out-of-extent corridor, source changes, or changed checks prevent execution.
Detour conflicts write `checks/alternative.json` and `prepare_failed`, without a
runnable spec; acknowledgement cannot override this zero-conflict requirement.
Fresh per-seed baselines recheck both the compiler and frozen clearance evidence.

The compiled alternative has 44 directed-link changes. A separate read-only
geometry check found zero exact line overlap with any source-network link and
a maximum total near-parallel overlap of 4.745 m along a single car link (132),
well below the 20 m duplication threshold. Forward and reverse reachability
checks of the actual compiler-produced car graphs both reach every car node:

| Network | Car nodes | Directed car links | Strongly connected |
| --- | ---: | ---: | --- |
| Fresh baseline input | 2,444 | 6,427 | Yes |
| Closure | 2,444 | 6,425 | Yes |
| Closure + alternative | 2,459 | 6,462 | Yes |

These checks ran before the authorized batch; connectivity does not establish
travel-time benefit or access feasibility.

The candidate has short bends and creates ground intersections. The compiler
introduces a **0.424 m shortest segment** near an intersection: this is explicitly
retained as a conceptual-topology caveat, not an engineered road design. Turning radii,
signals, access, utilities, missing buildings, property ownership, road hierarchy,
and construction feasibility remain unverified. “Zero known footprint conflicts”
does not mean engineering approval or complete building coverage. The fresh
expanded check was returned to the main agent before nine-run authorization.

## Preserved original straight-chord case

Prepared on 2026-09-26 and subsequently interrupted by the geographic-fix decision.
Read the live manifest for its durable status; preparation itself launched no
simulation:

- Case directory: `output/planning_cases/cbd_closure_alternative_10it_review/`.
- Source: `cbd_demo_20260926T050044Z_a805bd_sim` (completed, verified).
- Population: 1,037 synthetic persons from the same existing `8.xml/plan.xml`.
- MATSim seeds: 4711, 4712, 4713. Each of nine runs uses iterations 0–9, ten total.
- Initial case status: `prepared`; `started_at` and `finished_at` are null;
  every stage's `attempts` list is empty. Read the live manifest for later status.
- Closure compiler check: 0 building conflicts. Combined alternative check: **2**.

Native coordinates are **EPSG:7899, metres**. No road names or construction rights
are inferred from link IDs.

| Role | Node/link | Coordinates or geometry |
| --- | --- | --- |
| Closure north endpoint | node 8844 | (2496581, 2408829) |
| Closure south endpoint | node 8954 | (2496544, 2408715) |
| Closure | links 890 and 2071 | 8844 ↔ 8954, recorded length 120.498 m each |
| Alternative north endpoint | node 8695 | (2496731, 2408809) |
| Alternative south endpoint | node 9032 | (2496648, 2408628) |
| Alternative | straight connecting ground road | 8695 ↔ 9032, 199.123 m |

The closure removes only `car` from those two directed links and retains bike/walk.
The alternative is east of the closure and connects two existing car nodes with
zero elevation offsets, exact endpoint placement (`snap_points=[false,false]`),
30 km/h, one lane per direction, 900 vehicles/hour per direction, and car/bike/walk
access. The compiler screens a 9 m wide corridor; that width and capacity are
concept assumptions, not surveyed or approved engineering parameters.

The route was selected from network geometry before this experiment's outcomes.
It is not a duplicate of an existing direct link. The existing nearby car path
uses 8695 → 9019 → 9032 (links 1069 and 1167, with reverse links 2199 and 2280).
A read-only intersection check against **all** source-network line segments
found no overlap longer than 0.1 m with the proposed chord.

**The straight chord is obstructed by existing building footprints. Its
buildability as drawn has not been established.** The conflicts are substantial
enough that they must not be described as minor edge contacts:

| Building identifier | Recorded height | Centreline inside footprint | 9 m corridor overlap |
| --- | ---: | ---: | ---: |
| way/109034676 | 5.27 m | 55.60 m | 506.36 m² |
| way/154296883 | 19.01 m | 41.18 m | 351.35 m² |

These are calculations from existing planar footprints, not a site survey.
They establish conflicts, not demolition scope, cost, property rights, or safety.
The route is retained transparently as an obstructed conceptual stress test;
no alternative alignment was searched for favourable traffic results. The full
compiler report, polygons, IDs, labels, warnings, and token are retained in
`checks/alternative.json`. A different alignment requires a separately reviewed,
new case; do not edit a prepared specification in place.

## Preparation and execution interface

Run from `/Users/erickang/Documents/matsim`. Preparation has no Docker/MATSim calls:

```sh
.venv/bin/python scripts/run_planning_case.py --prepare \
  --case-id cbd_closure_alternative_10it_review
```

That case already exists; repeating this command deliberately refuses to overwrite
it. Omit `--case-id` to prepare a new uniquely named case. Optional prepare-only
controls are `--source-run`, `--seeds 4711 4712 4713`, and `--last-iteration 9`.
The supplied source must geometrically resolve the predeclared corridor and CRS.
Limits are 1–10 distinct seeds in [1, 2147483647], last iteration 1–49, and three
attempts per stage. Runs execute sequentially. Defaults launch nine simulations;
with ten seeds the first attempt can launch at most thirty simulations.

**After expanded-plan review and explicit authorization**, the separate batch command is:

```sh
.venv/bin/python scripts/run_planning_case.py \
  --run output/planning_cases/cbd_expanded1037_detour_10it_review_r02
```

For a separate explicitly approved straight/conceptual case, the CLI requires
`--acknowledge-conceptual-conflicts` whenever its prepared report has conflicts;
this does not approve construction. Preparation cannot grant acknowledgement for
later execution. The obstructed old chord is preserved, not selected for the new
policy example. Run controls are frozen; run-time seed/iteration overrides fail.

After inspecting an interrupted/failed case and confirming any prior simulator
process has ended, recovery is explicit:

```sh
.venv/bin/python scripts/run_planning_case.py \
  --run output/planning_cases/cbd_expanded1037_detour_10it_review_r02 --resume
```

Recovery verifies the hashes of completed stages, skips those stages, and retries
failed/interrupted stages under new attempt IDs (`a02`, then `a03`). Failed
artifacts remain intact. A process lock prevents simultaneous execution of the
same case. A hard-killed process may leave `running` in the manifest; explicit
recovery retains that attempt as `interrupted`. It never assumes an unrecorded
output directory is a successful run. A pre-existing unexpected output, changed
source/check/config, exhausted retry limit, or changed completed result stops
execution; resolve the cause or prepare a new case. There is no cleanup/delete mode.

## Artifacts and UI integration

`case_spec.json` is the immutable declaration: source evidence, snapshot hashes,
seeds/iterations, geometry, plans, conflict counts/check files, population count,
configuration-template hash, controls, and limitations. `case_manifest.json` is
the only mutable case record. It is replaced atomically and records lifecycle
timestamps, each execution's acknowledgement, per-seed stage attempts, errors,
result evidence, and the latest aggregate path/hash.

The existing `/results` static mount already exposes these files. No wrapper/API/UI
source changes are required by this runner:

```text
/results/planning_cases/cbd_closure_alternative_10it_review/case_spec.json
/results/planning_cases/cbd_closure_alternative_10it_review/case_manifest.json
/results/planning_cases/cbd_closure_alternative_10it_review/checks/closure.json
/results/planning_cases/cbd_closure_alternative_10it_review/checks/alternative.json
/results/planning_cases/cbd_expanded1037_detour_10it_review_r02/case_spec.json
/results/planning_cases/cbd_expanded1037_detour_10it_review_r02/case_manifest.json
/results/planning_cases/cbd_expanded1037_detour_10it_review_r02/checks/alternative.json
/results/planning_bootstraps/cbd_expanded1037_bootstrap/bootstrap_manifest.json
```

The main agent may add an endpoint or UI view that reads these records. For each
`manifest.rows[]`, use `seed`, then `stages.baseline`, `stages.closure`, and
`stages.alternative`. Each stage has append-only `attempts[]` with `run_id`,
`status`, `started_at`, `finished_at`, `result`, and `error`. An empty attempts list
means not started. `manifest.status` can be `preparing`, `prepare_failed`,
`prepared`, `running`, `failed`, `interrupted`, or `completed`.

Every evidence `path` is project-relative and begins `output/`; map that prefix
to `/results/` to obtain the existing read-only URL. `manifest.aggregate` is null
until aggregation is first published. No endpoint should treat a prepared case
as permission to execute it.

Large native artifacts remain in separate top-level output directories because
the existing IF Line runner resolves network/demand directories by basename:

```text
output/<case>_inputs_network/network.xml
output/<case>_inputs_demand/8.xml/plan.xml
output/<case>_s<seed>_baseline_a01_sim/
output/<case>_s<seed>_closure_a01_network/
output/<case>_s<seed>_closure_a01_sim/
output/<case>_s<seed>_alternative_a01_network/
output/<case>_s<seed>_alternative_a01_sim/
output/run_records/<run_id>/run_manifest.json
output/ifline/<branch_run_id>/scenario.json
output/ifline/<branch_run_id>/comparison.json
output/planning_cases/<case>/results/<run_id>.json
output/planning_cases/<case>/aggregate_<unique-id>.json
```

Each fresh baseline uses `run_simulation`, `RunRecorder`, the shared summary
generator and skyline renderer. Its recorded network/demand outputs and
`run_metadata.json` allow `resolve_run_assets()` and existing run discovery to
resolve it. Both branches use `check_plan` followed by its current check token
and `run_ifline_scenario`. The baseline's regenerated geometry/conflicts must
match the prepared report before a branch runs.

Verification checks the exact score-history sequence, population size, clean
baseline shutdown, actual output-config seed/iteration/input paths, frozen plans,
baseline-network hash, and compiled branch-network equality. Configurations
across completed runs must agree apart from the declared seed and network/output
paths. Results fingerprint native configs, plans, network, events, trips,
persons, score history, scene, metadata, run records and branch comparisons.
No existing simulation/config/record/scenario/process-log directory is reused.

## Interpretation and aggregation

Per seed, `aggregate_*.json` retains three comparisons:

1. Closure minus fresh baseline.
2. Closure plus alternative minus fresh baseline.
3. Closure plus alternative minus closure.

Percentages for the third comparison use the closure denominator directly;
percentages from two baseline comparisons are never subtracted. Each comparison
retains native mode changes and overall mean travel time/distance, score, and
trip-count deltas. Across completed seed triples, `descriptive_ranges` reports
count, missing count, minimum, maximum, mean, and median. Partial aggregates list
incomplete seeds explicitly. Unavailable percentages remain null, never zero.

For each comparison label, `descriptive_ranges[label].car_mean_travel_time_s`
additionally summarizes the car row's `avg_time_delta_seconds`. It is available
only when **both** sides have positive car trip counts; absent/zero-count car
modes remain missing rather than receiving a fabricated zero. The UI label is
“全天汽车均耗时差”: a full-population, car-mode mean difference from the complete
native trip tables, **not a paired-trip estimate** and not the optional impact
analyzer's 0–30 h departure-window measure. `metric_definitions` records these
units and population/time bases explicitly.

No confidence intervals, p-values, significance, convergence, or automatic
“benefit” verdict are produced from three seeds. Changes in whole-population
means can include mode/completion composition changes and are not paired-person
causal effects.

The native fallback uses `wrapper.ifline.compare_summaries` and checks published
branch comparisons against summaries. If `wrapper.impact` is available, each
branch result additionally retains `analyze_impact(fresh_baseline, branch,
start_s=0, end_s=108000, mode="all")`: a 0–30 h half-open window, with all its
comparability checks, trip matching, network/completion diagnostics and caveats.
This window differs from an unrestricted native trip-table summary. Absence of
that module is explicitly recorded; an installed analyzer's failure is propagated
and retained rather than silently treated as no impact. No stable aggregate
schema depends on undocumented `wrapper.impact` fields.

### Paired trips are a different measurement

`impact.trips` matches **person + trip_number**, selecting the left/baseline
run's departure time and mode. It reports the mean, median and p95 of individual
duration differences, matched/eligible counts, missing or invalid pairs, mode
switches and the distribution of faster/slower trips. These keys do not assert
identical OD locations or routes, and the analysis is not a causal forecast.
Faster means delta ≤ −1 second, slower means delta ≥ +1 second, and unchanged
means absolute delta <1 second. Missing trips never receive zero duration.

In contrast, the native mean difference subtracts two independently aggregated
trip-table means; the number or identity of included trips can differ. Even if
their numerical means happen to agree for a fully matched cohort, that does not
make the definitions interchangeable. In particular, p95 of **paired changes**
is not a subtraction of two travel-time p95 values. Do not derive a third
comparison's percentiles by subtracting the two baseline comparisons.

The batch's saved optional impact reports use **all modes, [0,108000) seconds**.
The car-paired checks in the result discussion use the same window with
`mode="car"`, through a separate read-only `analyze_impact(left, right, ...)`
call for each comparison. A morning-peak report is a further distinct selection;
always show its window and mode, rather than relabelling it as all-day evidence.

The CLI does not call `wrapper.runner`, `wrapper.scenario`, `wrapper.pipeline`
or the demand generator. It consumes frozen XML, compiles the two plan branches
and calls `wrapper.baseline_runner` directly (also through IF Line). It has no
Web job ID; an idle-only Web restart does not own or cancel this CLI process.

### Completed results: the alternative did not improve this screening metric

All nine results contain 1,037 persons, iterations 0–9 and 3,623 trips: 934 car,
114 bike, 977 pt and 1,598 walk. Their original input plans have the same SHA-256.
The final audit rechecked 124 recorded file-hash references (including repeated
shared-input references), as well as the frozen case/clearance evidence. The
authoritative final aggregate is:

`output/planning_cases/cbd_expanded1037_detour_10it_review_r02/aggregate_1658e2904654.json`

SHA-256: `5adc117ca8bd71d7403c31775e03dd3158ad73dbc55c27ec456ed38f3040583b`.

**Native full-population car mean difference, seconds** (positive = slower):

| Seed | Closure − baseline | Alternative − baseline | Alternative − closure |
| --- | ---: | ---: | ---: |
| 4711 | +7.705567 | +7.822270 | +0.116702 |
| 4712 | +7.523555 | +7.620985 | +0.097430 |
| 4713 | +7.360814 | +7.440043 | +0.079229 |
| Descriptive mean across seeds | +7.529979 | +7.627766 | +0.097787 |

The corresponding three-seed ranges are [7.360814, 7.705567],
[7.440043, 7.822270] and [0.079229, 0.116702] seconds. These are descriptive
ranges, not confidence intervals. All-mode native means show smaller differences
(mean +1.941209, +1.966418 and +0.025209 seconds respectively); unaffected modes
dilute a network-car effect, so an all-mode mean alone is not an adequate review.

**Read-only paired car-trip review, baseline departures in [0,30 h):** each row
has 934 paired trips, no unmatched/invalid pairs, no mode switches and median
change 0 seconds. The event-based car stuck count is 0 on each side; it is an
event diagnostic, not itself a paired completion-rate estimator.

| Seed | Comparison | Faster ≥1 s | Slower ≥1 s | Absolute change <1 s | p95 of paired change (s) |
| --- | --- | ---: | ---: | ---: | ---: |
| 4711 | Closure − baseline | 122 | 284 | 528 | +62.05 |
| 4712 | Closure − baseline | 121 | 279 | 534 | +62.05 |
| 4713 | Closure − baseline | 122 | 280 | 532 | +62.05 |
| 4711 | Alternative − baseline | 134 | 326 | 474 | +64.35 |
| 4712 | Alternative − baseline | 133 | 322 | 479 | +64.35 |
| 4713 | Alternative − baseline | 134 | 321 | 479 | +64.35 |
| 4711 | Alternative − closure | 13 | 65 | 856 | +1.00 |
| 4712 | Alternative − closure | 13 | 63 | 858 | +1.00 |
| 4713 | Alternative − closure | 14 | 61 | 859 | +1.00 |

The paired car means happen to equal the native car differences in the first
table, up to floating-point rounding: every car trip is included and matched,
without mode switches. This observed equality is not a general equivalence of
the two estimators. Do not pool repeated seeds as 2,802 independent observations;
they reuse the same synthetic people and starting plans.

The saved **all-mode** optional reports separately pair 3,623 trips per branch
against its fresh baseline. Their paired mean changes by seed are
+1.986475/+1.939553/+1.897599 seconds for closure and
+2.016561/+1.964670/+1.918024 for alternative. Their larger unaffected cohort
explains why those numbers must not be labelled as paired **car** impacts.

Reproduce the car-paired review without launching any simulation:

```sh
.venv/bin/python - <<'PY'
import json
from wrapper.impact import analyze_impact
for seed in (4711, 4712, 4713):
    prefix = f"cbd_expanded1037_detour_10it_review_r02_s{seed}"
    for left, right in (("baseline", "closure"), ("baseline", "alternative"),
                        ("closure", "alternative")):
        report = analyze_impact(f"{prefix}_{left}_a01_sim",
                                f"{prefix}_{right}_a01_sim",
                                start_s=0, end_s=108000, mode="car")
        print(seed, f"{right} minus {left}", json.dumps(report["trips"]))
PY
```

This bounded experiment does **not** support a travel-time benefit for the chosen
detour. The alignment, capacities, seeds and iteration controls were not changed
after seeing outcomes. Its small additional mean delay is not a statistical or
causal claim about a real project, and the p95/affected-trip distribution must be
read alongside the mean. No construction, safety, emissions, equity or economic
benefit is inferred. Native logs retain warnings about QSim capacity/storage
adjustments and an inherited final-activity end-time correction; successful
completion does not mean warning-free inputs or convergence.

## Deterministic verification

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_planning_case.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_planning.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_ifline.py' -v
```

Tests use temporary fixtures with a replaced simulator and skyline renderer;
they exercise the real plan compiler, baseline recorder/asset resolver, IF Line
branch orchestration, summaries, failure/recovery and hash checks. Their synthetic
travel outputs are test data, not outcomes for the prepared CBD case. Real Docker,
MATSim convergence and the main UI workflow are not established by fixture tests.
After the uncapped-source gate and car-mode aggregate changes, the focused suite
has 32 passing tests and the final full deterministic suite has 280 passing tests
(`.venv/bin/python -m unittest discover -s tests -q`, 2026-09-26 06:34 UTC).
