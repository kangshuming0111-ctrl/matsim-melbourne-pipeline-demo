# IF Line workbench verification — 26 September 2026

## Scope and boundaries

This change makes completed controlled runs inspectable by time, baseline mode
and selected directed links. The analytical module owns metric definitions;
the frontend owns one applied-request snapshot, not a second calculation engine.
The experiment catalogue is read-only and has no runner import. Actual simulation
is explicitly initiated by the separate case runner. Existing outputs remain
preserved, including failed/interrupted preparations and attempts.

Files: `wrapper/impact.py`, `coverage_audit.py`, `planning_catalog.py`, thin API
adapters, `static/impact-ui.js`, `planning-cases.js`, `impact.css`, and integration
in `static/index.html`. Fixed traffic scales replace scene-relative ranking;
historic rank-coloured scene files remain intact but their old ribbons are not
displayed as absolute measurements. No renderer geometry rewrite is part of this
workbench change.

## Actual browser checks

The bundled Playwright CLI was not available; no browser dependency was installed.
The checks below were actually executed through the existing in-app Chromium
browser, not reported as a Playwright CLI suite or cross-browser certification.

`tests/browser/impact_workbench.html` loads the actual module and CSS, intercepts
requests and captures exports in memory. It completed **285 assertions in
17 scenarios**. These cover:

- Peak/custom times (including hours after midnight), all five mode choices,
  empty cohorts and actual zero versus unavailable observations.
- Multi-link corridors, contextual outside links, selected-new-link totals,
  car/bike-only all-mode map labels, source-file quality counters.
- HTTP/configuration mismatch and transport failures, retry, export locking on
  unapplied edits, old analysis/coverage responses, closing and reopening.
- HTML export retains distinct A/B completion-table cells, nullable coverage
  and readable provenance; JSON retains full link context and nulls.
- Actual iframe widths 375, 760 and 1280 pixels: selectors, actions, map and detail
  fit; wide link tables scroll locally. A browser viewport capability did not
  resize the initial tab, so it was reset and **not** counted as responsive evidence.

Real API + saved native MATSim results were separately exercised:

- Historical capacity case `if_20260926T050734Z_a9b72b_sim`: AM/car, 207 paired
  trips, mean difference +0.053 seconds; selecting link 255 yields 57 pairs,
  +0.193 seconds. This is not a claim of practical or significant benefit.
- Its map/table inspection and 3D-location button worked. Selecting walk explains
  unavailable link observations. An invalid 7–1 hour range removed all metric
  cards and disabled both exports instead of showing stale results.
- Expanded case seed 4711 baseline vs closure: AM/car, 207/207 pairs,
  +10.21256038647343 seconds; 29 faster, 76 slower, 102 within 1 second.
  P95 351.8→359.1 seconds. The webpage matched the independently read API result.
  This is a single-seed check, not the final multi-seed conclusion.
- Case catalogue presented completed baseline/closure buttons while later
  stages remained visibly running/not started. Opening a result did not enqueue
  another simulation. Browser console contained no error/warning entries in
  these checked flows.
- After all nine runs completed, the live catalogue returned 9/9 verified stage
  identities/control-source hashes and a valid 3/3-seed aggregate. The webpage
  displayed the three final car-mean differences (+7.530, +7.628, +0.098 s) and
  preserved the earlier prepared/interrupted cases as distinct records.
- A direct replay link for seed 4711 alternative versus closure selected those
  actual A/B runs. Its AM/car result was 207 paired trips, +0.067632850241546 s,
  one faster, 18 slower and 188 within one second. The original whole-day 3D
  comparison remained labelled separately rather than adopting these filters.

## Existing graphics/editor regression fixtures

Executed in the same browser using the repository-root static test server:

| Fixture | Observed result |
|---|---|
| `plan_workflow.html` | Final PASS, 39 assertions (36 original plus 3 uncapped-source display/failure assertions) |
| `building_geometry.html` | PASS, 21 assertions |
| `landuse_geometry.html` | PASS, 9 assertions |
| `road_geometry.html` | PASS, 373 assertions |
| `road_editor.html` | PASS, 27 assertions |
| `studio_layout.html` | PASS, 86 assertions |
| `skyline_depth.html` | WebGL 1 and 2: production 24-bit target had zero failures over 20 angle/distance probes each; old 16-bit control failed 18 each; resize and clearance checks passed |

These fixtures protect the previously reported clipping/geometry/state bugs;
they do not prove every city asset and every possible user camera position is
free of visual defects. A complete Safari/Firefox/device matrix was not executed.

Node checks separately passed for `plan_state.cjs`, `road_design.cjs` and
`test_studio_viewport.js`, plus syntax checks of the new browser modules.

## Independent review and focused test-gap audit

Read-only review identified four display-contract gaps: missing new-link totals
became zero, totals ignored corridor selection, pre-cohort invalid rows were not
visible, and exported completion tables lost column separators. All were fixed;
regression scenarios above now assert those behaviours. All-mode network scope
was also made explicit beside each map. Catalogue evidence/specification hashes,
seed identities and completed-stage references fail closed.

Remaining gaps/limitations, not hidden by green unit tests:

1. The new normal API pipeline now has a separate successful fresh end-to-end
   run, not a reused r03 experiment. See [its evidence](2026-09-26-cbd-activity-domain-e2e.md).
   This closes that execution gap, not model calibration or convergence.
2. No cold-machine dependency/image build, browser-download filesystem roundtrip,
   crash injection during a real nine-run batch, or broad cross-browser matrix
   was performed. Export contents were inspected in-memory by the real browser.
3. The old `wrapper/analyze.py` summary uses zero fallback for some malformed
   durations/distances. The new workbench rejects/excludes invalid observations
   explicitly; actual checked source trip files had zero invalid rows. Do not
   generalize those clean-file checks to arbitrary imported malformed summaries.
4. No observed traffic calibration, convergence study, confidence intervals,
   full transit assignment, cost/emissions/equity analysis, or civil-design
   approval. Fixed demand excludes land-use feedback and induced-demand effects.

## Completed repeated-seed experiment

`output/planning_cases/cbd_expanded1037_detour_10it_review_r02/case_manifest.json`
is completed, 06:17:50–06:32:36 UTC. Its final aggregate is
`aggregate_1658e2904654.json` (SHA-256
`5adc117ca8bd71d7403c31775e03dd3158ad73dbc55c27ec456ed38f3040583b`).
See [the case protocol and numerical results](../docs/PLANNING_CASE.md).
All nine first attempts succeeded; the separately recorded bootstrap is not a
replacement for any fresh baseline. No route was changed to obtain a favourable
traffic result. Original outputs and interrupted attempts remain untouched.

The full Python suite at 06:37 UTC passed **280 tests** in 1.568 s, with no failed
or skipped tests. This is a timestamped checkpoint; any subsequent editor
footprint-check changes require a new final suite result below, not reliance on
that count.

## Final verification after uncapped editor screening

The final command `python -m unittest discover -s tests -v` passed **295 tests**
in 1.715 s (0 failures/errors/skips). The actual, privacy-checked console log is
[`2026-09-26-python-tests.log`](2026-09-26-python-tests.log), SHA-256
`4ca867bd4696eaf89fe978b5248b8a381e54531c328a194dee633727ae04c694`.
Node syntax and pure-state checks passed; `git diff --check` was clean.

The production new-road check now loads uncapped known footprints independently
of the display cap, validates source geometry and the full compiled corridor's
cache extent, and binds source bytes/version to the check token. Fifteen targeted
Python tests cover omitted buildings, holes, bounds, source mutation, invalid
data and no-new-road operations. Old new-road check tokens need rechecking;
historical simulations/specifications were not rewritten.

After safely restarting the idle service, real HTTP requests to
`POST /ifline/plan/check` used the frozen seed-4711 expanded-baseline plans:

- Closure: `building_screen.status = not_required`; explicitly no new footprint.
- Closure plus alternative: `completed`, all **5,622 source features** validated,
  full corridor inside cache extent, zero known footprint conflicts. Source hash
  `f212b7f586704103fb829d7f9ec308e88c9b5b1674df1fc8dfb8509a70cedd9f`.
- The job queue remained at zero active jobs; check requests did not simulate.

The browser displays source-feature counts separately from conflict counts.
The new fixture first caught a cached older `planning-ui.js?v=4`; the application
and fixture were versioned to v5 and rerun, passing all **39** workflow checks.
This preserves the failed-check behaviour: old coverage claims and approvals
are cleared, never shown as zero conflicts. The final workbench fixture was
also rerun successfully: **285 checks / 17 scenarios**.

The fresh normal-flow replay showed the correct new run ID, 1,037/3,623/3 values,
loaded mode/score charts and a rendered 3D scene, labelled as existing-result
replay. Finally the actual seed-4711 closure comparison was opened at AM/car:
207/207 pairs, +10.213 s displayed, 29/76/102 faster/slower/within tolerance.
The browser console had no warnings/errors in those checked flows.

These are actual API checks plus browser rendering and deterministic UI tests;
they are not a claim of a new end-to-end mouse-drawn construction run for every
geometry, or a complete Safari/device matrix. The 3D rendering geometry was not
rewritten as part of this workbench delivery.
