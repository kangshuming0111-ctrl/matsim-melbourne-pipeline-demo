# Privacy-reviewed run and test summary

This file summarizes a local validation run without publishing raw source data,
full agent plans, event streams, host names, user names, local absolute paths,
environment variables, credentials or tokens.

## Latest planning-workbench validation: 26 September 2026

The normal CBD API was also freshly rerun under `cbd_activity_domain_v2`:
demand → activity-domain network → MATSim → analysis completed in approximately
11 minutes 32 seconds, with 1,037 synthetic agents, 3,623 trips, iterations 0–2,
18/18 required artifacts and 100% activity-to-node-bbox inclusion.
[The separate normal-flow record](../validation/2026-09-26-cbd-activity-domain-e2e.md)
is not a replay of the study below. The profile remains experimental.

The completed `cbd_expanded1037_detour_10it_review_r02` experiment contains
**nine fresh MATSim runs**: baseline, closure, and closure plus a predeclared
356.159 m alternative road, for seeds 4711, 4712 and 4713. All use the same
1,037-agent input plans and ten iterations (0–9). Every run completed with
3,623 trips, including 934 car trips. Bootstrap preparation is not counted
among those nine runs.

The road network was expanded to the unchanged demand's activity domain:
3,129 nodes and 11,331 directed links. All 4,660 finite activity occurrences
fall inside the cleaned network's node rectangle, compared with 69.1% in
the earlier small-network run. This is a domain diagnostic, not calibration.

The car-mean travel-time differences, averaged descriptively across seeds, are
**+7.530 s** for closure minus baseline, **+7.628 s** for alternative minus
baseline, and **+0.098 s** for alternative minus closure. Positive means slower.
This experiment **does not demonstrate a benefit of the alternative road**;
the small final difference is not evidence of statistical significance or real
traffic harm. Pairing, per-seed ranges, geometry checks and remaining engineering
limitations are documented in [the planning-case protocol](PLANNING_CASE.md).

The new [impact workbench](IMPACT_WORKBENCH.md) supports applied time/mode/corridor
filters, paired-trip summaries, fixed-scale link maps, null-data diagnostics,
3D location and HTML/JSON exports. Actual browser and deterministic regression
results are recorded in [the workbench verification record](../validation/2026-09-26-impact-workbench.md).
This validation still uses the existing local environment and cached Docker
images, not a clean-machine installation or a calibrated government model.

## Earlier same-day small-network validation

A fresh baseline and one capacity-change proposal both completed, with 1,037
synthetic agents, 3,623 trips and three iterations each. The controlled change
produced a near-null travel-time response, not a claimed traffic improvement.
That earlier Python check executed 107 tests, all passing. See the
[dated execution and verification record](../validation/2026-09-26-cbd-demo.md)
and [reproduction guide](REPRODUCIBLE_DEMO.md) for evidence and remaining limits.
This validation reused the existing local environment and Docker caches; it was
not a clean-machine reproduction.

The sections below retain earlier validation history, including the earlier
34-test result; those counts should not be confused with the later execution.

## Earlier end-to-end demo

- Profile: `cbd_small_v1`
- Local run ID: `cbd_demo_20260908T205520Z_16879d`
- Date: 9 September 2026 (Melbourne time)
- Elapsed time: 885.999 seconds
- Network: 684 nodes and 2,464 links
- Synthetic agents: 1,037
- Trips: 3,623
- MATSim score rows: 3 (iterations 0, 1 and 2)
- Required artifacts: 16/16 present and non-empty
- Runtime outcome: normal MATSim shutdown; no unexpected-termination marker
- Network/demand bounding-box diagnostic: 69.1%

The run used a new output directory and preserved prior results. The published
screenshots show a historical replay of this completed run, not a claim that a
simulation completed at the instant the screenshot was taken.

## Python validation

- Python: 3.11.9 in a newly created project-local `.venv`
- Command: `python3 -m unittest discover -s tests -v`
- Discovered: 34
- Passed: 34
- Failed: 0
- Errors: 0
- Skipped: 0

Additional checks passed for Python byte compilation, launcher shell syntax and
Git whitespace errors. API replay assertions confirmed that the displayed run
ID, agent count, trip count, iteration count and run-record link all referred to
the same result directory. Browser acceptance confirmed that the summary table,
charts and 3D scene rendered without console warnings or errors.

## IF Line policy-branch check

Two controlled branches were completed from the same recorded CBD baseline,
plans file, MATSim seed and three-iteration configuration:

- A one-way speed change on link 255 (50 → 30 km/h) completed with 1,037
  synthetic agents and 3,623 trips. Car mean trip time changed by +1.060 s.
- A two-way car closure on links 890/2071 preserved bike/walk access and
  completed with the same 1,037 agents and 3,623 trips. Car mean trip time
  changed by +7.595 s and all-mode trip-weighted mean time by +1.958 s.

Each branch has an independent network, simulation result, scenario record,
comparison record, run manifest and 3D difference scene. Final file checks and
the MATSim clean-shutdown check passed. The browser displayed the matching
branch evidence and comparison without console warnings or errors.

The 3D policy-studio interaction was also checked against the recorded CBD
baseline: all 2,464 scene roads carried stable MATSim link IDs, the editor
exposed 1,083 car-editable links, a road click selected the matching link and
its reverse direction, and speed, capacity and car-closure previews updated
without launching a simulation. An existing completed closure branch opened in
the same studio with its recorded comparison and impact-location control.

## Free-form road editor check

A third controlled branch was submitted from the full-screen 3D editor rather
than selected from a preset list:

- Scenario ID: `if_20260910T000544Z_4b731d`
- Baseline: `cbd_demo_20260909T235440Z_79494b_sim`
- Geometry: three user-placed control points, approximately 800 m total
- Design: 50 km/h, two lanes per direction, 1,800 vehicles/hour/direction,
  bidirectional, with car/bike/walk permitted
- Network result: four directed links added; all three submitted points snapped
  to existing network nodes in this run
- Runtime result: clean MATSim shutdown with 1,037 synthetic agents, 3,623 trips
  and iterations 0, 1 and 2
- Usage evidence: 164 `entered link` events on the four added links

The recorded all-mode mean-trip-time delta was -0.129 seconds and the car delta
was -0.468 seconds. Those tiny deterministic deltas are retained as pipeline
evidence only and must not be described as real-world benefits.

## Upstream test status

The upstream R demand test suite was also executed in its pinned container. Its
unmodified harness first reported an undefined `output_crs` in `testPlace.R` and
a legacy `plan.csv` MD5 mismatch in `testPlan.R`. Supplying EPSG:28355, the CRS
stored in the expected fixture, allowed `testPlace.R` to pass. One byte-level
MD5 snapshot failure and four plotting warnings remained. The failing snapshot
was not removed, regenerated or relaxed.

The single upstream network R test still targets the old hard-coded city setup
and was not executed independently. The current end-to-end demo did exercise the
network generator through the environment-driven wrapper.

## Interpretation limits

This is evidence that the local software pipeline completed and produced the
required files. It is **not** evidence that the transport model is calibrated,
scientifically validated, converged, predictive, or responsible for a measured
improvement in real transport conditions. The 69.1% value is a rectangular
bounds diagnostic, not strict polygon coverage or an accuracy metric.
The IF Line deltas are experimental, deterministic comparisons, not causal or
long-term land-use forecasts.
