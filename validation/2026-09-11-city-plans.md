# City-plan editor verification — 2026-09-11 (Australia/Melbourne)

Implemented in the existing, dirty working tree based on commit `55a3dd8`.
This is not a claim that the commit alone contains this work. Pre-existing changes
and all previous simulation results were retained. No dependency installation,
new model engine, full-city regeneration, or repository push was performed.

## Scope delivered

- Multiple ordered road operations (1–12), individual edit/removal, bounded
  undo/redo, browser-local drafts including unfinished drawing.
- Insert/move control points and terrain-relative heights. Ground crossings
  split car links into shared nodes; elevated/ramp interiors remain separated.
- Width-based building-footprint conflicts, stable numbered labels, clickable
  camera focus; explicit acknowledgement before conceptual trial runs.
- Server check token ties the normalized plan to network and scene bytes.
  Rechecked before queueing and in the worker; rejection is not shown as success.
- New-road and vehicle heights survive MATSim XML/event exports. Old scene data
  without height fields remains supported. Terrain/building modules retained.
- New/split or one-sided-observation links are not treated as measured link-delay
  improvements. Overall trip comparisons are separate.

## Automated checks actually executed

Environment: project `.venv`, Python 3.11.9, Shapely 2.1.2; bundled Node runtime;
local application on port 8000 and temporary browser fixture server on 8765.

`python -m unittest discover -s tests -q`: **79 tests, 79 passed**, no failures,
errors or skips in the final run. One initial failure in a legacy mocked scene
was fixed by defaulting missing height fields to ground level, without deleting
or weakening the existing assertions. Later tests additionally reject invalid
building polygons and exclude incomparable link-delay observations.

`node tests/plan_state.cjs`: passed add/copy isolation, undo, redo, divergent edit
invalidation, revision count and 50-step history bound. All inline application
JS and the three new JS modules parsed successfully. `git diff --check` passed.

Actual browser fixtures using production helpers:

| Fixture | Observed result |
|---|---|
| `skyline_depth.html` | WebGL1 and WebGL2: 24-bit depth / 8-bit stencil; 0 fixed-path occlusion failures in 20 views each; resize, ground clearance and disposal passed |
| `landuse_geometry.html` | 9/9 checks passed: holes, winding, fill, tree exclusion and finite extrusion |
| `building_geometry.html` | 21/21 checks passed: footprint-constrained roofs, courtyards, clipping, legacy fallback and no GL error |
| `road_geometry.html` | 373 assertions passed: ground, ramp-up, deck and ramp-down share the terrain sampler; finite vertices/normals, upward top faces and depth-tested solids |

## Real end-to-end runs (not fixture replays)

Baseline: `cbd_demo_20260910T001314Z_0d6a3f_sim`.
Both branches reused its demand and MATSim seed, and ran iterations **0, 1, 2**
with **1,037 synthetic agents / 3,623 recorded trips**.

| New run ID | Concept | Result |
|---|---|---|
| `if_20260910T184236Z_0c1d85` | Four control points at 0/8/8/0 m + link 255 capacity 110% | Completed, 686 nodes / 2,470 directed links; 7 change records; 20 footprint conflicts acknowledged for testing |
| `if_20260910T184500Z_06dad2` | Same endpoints at ground level + link 255 capacity 110% | Completed, 686 nodes / 2,472 directed links; 11 change records; 26 footprint conflicts acknowledged for testing |

The first was submitted through the actual web editor; the second through the
same check/run HTTP API. Each run manifest reports `verification.passed=true`,
same demand/seed, required artifacts present and clean MATSim shutdown. The
first finished at `2026-09-10T18:43:11Z`, the second at `18:45:35Z` (UTC).
Evidence is under `output/ifline/<id>/scenario.json`, `comparison.json`,
`output/run_records/<id>/run_manifest.json` and each new `_sim/logfile.log`.

The elevated export contains six directed ramp/deck links with the correct
0↔8 / 8↔8 m offsets and **172 elevated vehicle keyframes**. Ground and elevated
topology are also tested independently on a small synthetic crossing network.

Both new scenes were compared to the refreshed baseline: **terrain, building,
park and water data were exactly equal**. Counts retained: 2,767 buildings,
228 parks, 22 commercial zones, 19 water polygons, 9 libraries and 3,457 tram
segments. No geometry was erased to accommodate the trial roads.

Mean whole-trip time changes were approximately −0.209 s (elevated) and
−0.232 s (ground). These tiny single-seed differences are **not evidence of
real-world improvement**, calibrated predictions or a preference for either
construction option. These deliberately conflicting alignments are verification
inputs, not recommended designs.

## Interaction / visual checks

Observed in the actual editor: drawing two points, inserting points, setting
height, combining capacity changes, undo/redo, save/reload, conflict list, clicking
“建筑4 · Centrepoint” to focus, run disabled until conflict acknowledgement, then
new job completion and matching result display. Found and fixed a height input
blur/rebuild issue during this exercise. No frontend error logs in the final
check. Rotated the city and inspected roofs/land; no prior fragmentation was
reproduced. Screenshot: [city-plan.png](2026-09-11-city-plan.png).

At a 600 px viewport, fixed a min-content grid overflow, verified the “参数面板”
toggle leaves the map visible, and reset the viewport afterwards. Test fixture
tabs and the temporary fixture server were closed; the main app remains local.

## Remaining limits (not passed off as completed)

- This is a conservative **2D footprint** conflict check, not a general 3D
  collision or structural/clearance solver. Confirmed concept conflicts remain
  conflicts; buildings are not automatically demolished.
- Baseline XML lacks complete existing bridge/tunnel levels. Unmarked links
  are assumed ground-level, so new crossings require manual review.
- Relative height/slope bounds do not include terrain grade or engineering
  standards. No piers, traffic-signal design, costs, land-use/induced-demand
  response, second simulator or installer was added.
- Drafts are browser-local. Legacy 2D single-operation endpoints retain their
  old behavior. No calibrated/observational or multi-seed validation claim.
- Tested viewpoints and fixtures cannot guarantee absence of every rendering
  defect for all data, hardware and camera positions.

Core source SHA-256 at final verification (not a Git authorship claim):

```text
037f0f3b9098fef1d620c5a06943b688dfba7aeee90d43cf3c671df5682bba68  wrapper/planning.py
0e411fe22a372d50901a1f74c93c5bb22daf13a0a2c8d3d3282528f36e388275  wrapper/static/planning-ui.js
f781fd905d18ba814912a2273d4b10cae8d86ed5dd4f5bfb9fa208c9199307b4  wrapper/static/road-mesh.js
a3ba7e9667b8c8b9848bfc8b33ab6b25c41772f81407c979e85474e0c9a0c66e  wrapper/ifline.py
5ea1a6c6b555aaa6b7e462d4c01127310de02ebaadba1a2959d43f551a36a752  wrapper/skyline.py
```
