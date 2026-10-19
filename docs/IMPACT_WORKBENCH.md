# IF Line impact workbench

The workbench is a read-only decision-discussion layer over **completed local
MATSim runs**, not a second simulation engine. It answers a bounded question:
with a fixed synthetic population and otherwise matched settings, which observed
trips and network traversals change when a road intervention is simulated?
It does not forecast land development, construction feasibility or real-world
causal benefits. The 3D editor remains a spatial input and review tool.

## Use it

1. Start the application with `./start.command` and open `http://127.0.0.1:8000/`.
   Do not open `wrapper/static/index.html` as a `file://` URL.
2. Open a completed IF Line branch from **打开已有结果**, or a completed stage
   in **成组规划实验**. The page explicitly labels recorded-result replay.
3. In **方案影响工作台**, choose reference A and comparison B, an observation
   window and a baseline trip mode. Apply the conditions. A different seed,
   population or normalized simulation configuration is rejected, not compared.
4. Select **A 延误**, **B 延误**, or **B − A 耗时差**. The scales are fixed across
   runs. Purple-grey dashed lines mean unavailable/non-comparable data, not severe
   congestion. Blue edges indicate selection. Small visual offsets distinguish
   directed segments; they are not physical lane widths.
5. Click a segment for actual counts, travel times and reference-relative delay.
   Enable corridor picking, select up to 100 directed links, and apply again.
   Reverse-direction links remain separate and are linked in the detail panel.
6. **在下方 3D 中定位** locates a selected segment only when the displayed 3D
   scene is the current comparison B. The 3D layer keeps its original whole-run
   pair; workbench time/mode/pair filters do not silently recolour it.
7. Export an HTML discussion report or JSON evidence from the applied snapshot.
   Changed conditions immediately lock export until reapplied. Failed analysis
   clears old conclusions. Late responses cannot replace a newer request.

Direct local replay links can use `/?run=<completed_branch>_sim`. An optional
`&baseline=<completed_reference>_sim` selects a different reference for the
workbench only; original simulation metadata is not rewritten. Neither URL
starts a simulation. Recorded active jobs take precedence over replay links.

## Metrics and safeguards

- **Trip cohort:** A's departure time in `[start, end)` and A's main mode. Pairing
  uses internal synthetic-person and trip-sequence keys, never exported IDs.
  B's corresponding trip may change route, mode or even destination; mode changes
  are counted. Missing/duplicate/invalid trips do not become zero-duration trips.
- **Corridor cohort:** the trip completely traversed a selected link in either
  run. Membership uses its whole observed trip, while the trip's baseline
  departure selects the analysis window. This does not assign unobserved or
  teleported trips to roads by guesswork.
- **Network observations:** complete entered-link/left-link intervals inside a
  vehicle-in-traffic session, bucketed by link-entry time. Exclude parked gaps,
  partial departure/arrival links and unfinished traversals. Counts are traversals,
  not unique people. The all-mode map contains **car and bike only**; walk/PT
  are teleported and do not have link congestion metrics in this scenario.
- **Comparable links:** same directed ID, length and endpoints, with observations
  on both sides. New, removed, split, geometrically changed and unobserved links
  keep null deltas. A new road is not assumed to be a zero-time improvement.
- **Travel-time difference:** B's mean actual traversal time minus A's. These
  link averages are not paired-driver estimates. Fixed thresholds are 1, 15 and
  60 seconds; the 1-second display tolerance is not statistical significance.
- **Delay:** each run's traversal time minus its own length/free-speed reference.
  Changing speed limits changes that reference, so the difference map compares
  actual traversal time instead. Signed negative delay values are retained.
- **Completion events:** departures, arrivals and stuck events are independently
  windowed. Their ratio is not a completion rate for trips crossing the window.
- **Coverage:** input activity points versus the network node rectangle, plus
  nearest-car-segment diagnostics in the audit artifact. A rectangle does not
  establish route connectivity, calibration or complete environmental coverage.

Every analysis hashes actual input plans and reads actual output configurations.
Only network path and output-directory fields are ignored for configuration
equality. Seed/iteration settings must match. Source artifacts are stamped before
and after reading; changed artifacts cause rejection. Responses omit synthetic
person and vehicle IDs. Full raw native outputs remain local and should not be
published without separate data review.

## Module ownership

| Owner | Responsibility |
|---|---|
| `wrapper/impact.py` | Authoritative comparisons, cohorts, fixed bins and provenance |
| `wrapper/coverage_audit.py` | Read-only geography diagnostics without deleting demand |
| `wrapper/planning_catalog.py` | Read-only experiment listing; verify result identity and checksums |
| `wrapper/api.py` | Thin GET adapters and error status mapping; never enqueue analysis |
| `wrapper/static/impact-ui.js` | Applied-request state, maps, filters, safe exports and 3D navigation adapter |
| `wrapper/static/planning-cases.js` | Read-only seed/stage catalogue and completed-result navigation |
| `scripts/run_planning_case.py` | Explicit preparation/execution of immutable, repeated-seed triples |

The existing single-branch whole-day summary is retained in a collapsed section
labelled as the **original replay pair**. It does not own workbench state. Historic
rank-coloured 3D JSON is preserved on disk but its old congestion ribbons are
hidden by the current viewer, rather than relabelled as absolute measurements.

See [planning-case protocol](PLANNING_CASE.md),
[domain audit](../validation/2026-09-26-coverage-audit.md), and
[domain expansion](../validation/2026-09-26-domain-expansion.md).
The original small-network run remains workflow evidence, not proof of adequate
geographic scope. Multi-seed minimum/maximum/mean are descriptive values, not
confidence intervals, convergence checks or calibrated forecasts.

## Verification entry points

Python: `python -m unittest discover -s tests -v`. Focused files include
`test_impact.py`, `test_impact_api.py`, `test_traffic_scale.py`,
`test_coverage_audit.py`, `test_planning_catalog.py` and `test_planning_case.py`.
Tests do not automatically execute the expensive experiment.

For the deterministic browser fixture, serve the repository root using
`python -m http.server 8765 --bind 127.0.0.1` and open
`http://127.0.0.1:8765/tests/browser/impact_workbench.html`. It uses real frontend
modules with intercepted data requests and in-memory downloads: useful for
state/race/export regressions, but not proof that the real API or MATSim ran.
Actual-browser flows against saved runs and real simulation logs must be reported
separately from these fixtures.
