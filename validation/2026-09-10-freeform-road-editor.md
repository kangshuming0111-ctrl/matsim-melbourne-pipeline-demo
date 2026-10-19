# Free-form road editor validation — 2026-09-10

## Scope

This check covered the first non-preset IF Line authoring flow: place multiple
points directly in the 3D city, snap the route to a real MATSim network, choose
road parameters, submit through the API, write a new network, run MATSim, and
open the matching branch comparison. It does not validate civil-engineering
feasibility, model calibration, induced demand or long-term land-use effects.

## Automated checks

- Command: `.venv/bin/python -m unittest discover -s tests -v`
- Result: **34 passed, 0 failed, 0 errors, 0 skipped**
- New coverage includes bidirectional link creation, intermediate geometry
  nodes, endpoint-connection rejection, invalid geometry/parameters, and the
  API path that accepts a free-form road without an existing `link_id`.
- Inline JavaScript in `wrapper/static/index.html` parsed successfully with the
  locally available `esprima` parser.

## Browser authoring check

In a real browser, the full-screen studio was switched to top view and three
points were placed in the 3D city. The editor displayed endpoint connectivity,
an approximately 800 m route length and the chosen bidirectional/two-lane
design. Submission remained disabled until both endpoints were connected and
parameters were valid. The request was sent through the normal `/ifline/run`
job path, not through a test-only backend call.

## Completed branch

- Scenario ID: `if_20260910T000544Z_4b731d`
- Baseline: `cbd_demo_20260909T235440Z_79494b_sim`
- Geometry: three control points, 799.981 m after snapping
- Parameters: 50 km/h, two lanes per direction, capacity 1,800/hour/direction,
  bidirectional, car/bike/walk
- Added links: `ifline_new_1_f1`, `ifline_new_1_r1`,
  `ifline_new_1_f2`, `ifline_new_1_r2`
- Runtime: **completed** with a clean MATSim shutdown
- Output: **1,037 synthetic agents**, **3,623 trips**, iterations **0–2**
- Event evidence: **164** `entered link` events across the four new links
- Recorded deltas: all-mode mean trip time **-0.129 s**, car mean trip time
  **-0.468 s**, average trip distance **-4.069 m**, final mean score **+0.0104**

Primary local evidence:

- `output/ifline/if_20260910T000544Z_4b731d/scenario.json`
- `output/ifline/if_20260910T000544Z_4b731d/comparison.json`
- `output/run_records/if_20260910T000544Z_4b731d/run_manifest.json`
- `output/if_20260910T000544Z_4b731d_sim/output_events.xml.gz`

## Interpretation limits

This branch demonstrates that user-authored geometry was converted into valid
MATSim links, loaded by the simulator and traversed by simulated vehicles. It
does not show that the road should be built or that it would improve observed
traffic. The current editor adds one polyline road per branch. Endpoints must
connect to existing nodes; crossing an existing road does not automatically
split that road into a junction. The comparison is one deterministic run with
fixed synthetic demand and does not include uncertainty intervals, induced
demand or land-use feedback.
