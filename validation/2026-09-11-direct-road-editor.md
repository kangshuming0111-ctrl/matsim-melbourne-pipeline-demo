# Direct road editor — local verification, 11 September 2026

Working tree based on commit `55a3dd8`, with existing uncommitted project work preserved. No commit or publication made. This record covers the interaction prototype, not a calibrated transport result or an engineering bridge design.

## Delivered

- Width-aware, terrain-sampled mouse preview kept outside the stored plan.
- Direct map-handle dragging, retaining height; native pointer capture separates dragging from camera rotation. Cancel/blur restores the draft and releases camera control.
- Per-point snapping intent persisted in `snap_points`, canonical check reports and check tokens. New free points are not silently moved by the compiler. Legacy plans retain their original snapping default.
- Independent draft undo/redo (50 steps), right-click single-point undo, Escape pause, selectable construction/oblique/side camera views. Existing rendering near/far planes and 24-bit depth pipeline unchanged.
- Relative-height longitudinal preview with movable height handles, locked ground endpoints, and a suggested elevated section with approach transitions. A short route reports an actionable error rather than being stretched. Existing bends are retained.

Core modules: `wrapper/static/road-design.js`, `road-editor.js`, `planning-ui.js`, `index.html`; backend compatibility in `wrapper/planning.py`. Terrain, building, land-use and road-surface implementation files were not edited by this change. The module separation keeps interaction calculations independently testable without changing city geometry.

## Executed checks

- `.venv/bin/python -m unittest discover -s tests -v`: 87 passed, 0 failed/errors/skipped. Includes 8 new snapping tests. External simulation runners in this unit suite are mocked; the suite is not a new MATSim run.
- Bundled Node: `tests/plan_state.cjs` and `tests/road_design.cjs` passed. Inline page scripts and editor JS syntax checked. Pure road tests cover ramp generation, bends, invalid/short inputs, endpoint locks, immutable height edits, bounded profile sampling and history.
- `tests/browser/road_editor.html`: 27 checks passed against bundled Three.js r128 and OrbitControls. Synthetic pointer events exercise preview lifetime, no duplicate points, drag/cancel/undo, snap override, locked busy/result states, detach cleanup, and unchanged terrain vertex buffer. Native pointer capture is checked separately below, not claimed from synthetic events.
- `skyline_depth.html`: WebGL 1 and 2 each tested 20 views; 24-bit depth / 8-bit stencil, zero fixed-path occlusion failures. Resize, camera clearance and repeated disposal passed. The legacy 16-bit path still reproduces 18 failures per context.
- `landuse_geometry.html`: all 9 checks passed.
- `building_geometry.html`: all 21 checks passed.
- `road_geometry.html`: 373 assertions passed.

## Actual application interaction

Opened the existing audited CBD baseline `cbd_demo_20260910T001314Z_0d6a3f_sim` in the in-app browser. No simulation was rerun and no previous output was replaced.

1. Placed two real map clicks: both endpoints connected, displayed length 712 m.
2. Generated a four-point relative-height draft `[0,8,8,0]`; displayed relative-height transition slope 8.0%.
3. Dragged the longitudinal handle from 8 m to 20.7 m. The UI warned about exceeding the prototype 12% relative-height limit. One undo restored 8 m.
4. Dragged an elevated map handle: four points remained, height retained, camera did not orbit, displayed length changed to 717 m.
5. Added the draft to a plan and called the actual `/ifline/plan/check` endpoint. The server returned one operation and 22 building-footprint conflicts. No conflicts were automatically accepted and no buildings were removed.
6. Edited the checked plan again: four points, 717 m and the relative height profile remained consistent. No hidden re-snapping occurred.
7. Inspected top, oblique and side views at a verified 1440×900 desktop viewport. The new panel was also visually inspected in the initial narrow window, but a later controlled 600 px viewport override did not take effect, so narrow-screen interaction is not claimed as fully verified. Temporary viewport override reset and test tabs closed at handoff.

An initial r128 compatibility error (`removeFromParent` unavailable) was found by actual browser interaction, then replaced with `parent.remove` in preview and conflict-highlight cleanup. Subsequent runs and final editor regression passed.

## Deliberate limits

This is the first direct-manipulation version, not the whole researched roadmap. It still uses straight polyline segments and node endpoints; curve handles and connection to the middle of an existing link remain future work. The elevated road remains relative to the displayed terrain, not an independently designed vertical alignment. No bridge piers, structural model, verified clearance, construction cost or code compliance is asserted. Scene terrain has display exaggeration and is not an engineering profile datum. Building conflicts remain conservative footprint checks. Passing the regressions is not a universal guarantee against arbitrary-data or hardware rendering defects.
