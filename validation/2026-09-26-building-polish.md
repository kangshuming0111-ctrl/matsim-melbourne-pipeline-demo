# Daylight architecture presentation — 26 September 2026

## Scope and contract

This is a display-only refinement of the existing local city viewer, in the
uncommitted working tree. No simulation, output regeneration, geometry source
download, dependency installation, or change to traffic analysis was performed.
The previous depth-buffer, land-use surface, picking and static-batching fixes
remain in place.

- `wrapper/static/building-style.js` owns a bounded, shared architectural material
  palette. Office glass/mullions, residential window frames/recesses, retail ground
  floor glazing/awnings, civic stone colours and industrial bays are schematic.
  These are **not** surveyed facades, verified uses, or exact floor counts. Window
  row counts use display buckets; the legend now states that uses are illustrative.
- `building-mesh.js` continues to own building solids and constrained roofs. Only
  wall UVs change: project onto each wall's tangent, scale bays by scene height /
  metre height, and normalize vertical UVs over the wall. No extra solids, vertices,
  raised lawn patches, roof boxes, footprint changes or courtyard infill. Existing
  setback crowns use the quiet roof material, not many compressed window rows.
- `index.html` uses the shared palette instead of the former inline texture and
  material factories. Daylight/fill lighting, roof/tree colour-space handling,
  road/ground colour balance and landmark label sizes are refined. Traffic colours
  and their meaning are unchanged. Materials remain opaque and batchable.
- “街区细看” is a camera-only preset centred on this scene's tall buildings. It
  does not modify the selected road, draft, result data, or current time. Its event
  handler is removed on viewer disposal; the button is disabled without buildings.

## Executed verification

`node` below is the already-installed bundled executable at
`/Users/erickang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node`.

- `node tests/building_style.cjs`: **65 checks passed**. Shared material identity,
  bounded textures, input immutability, invalid-height rejection, sRGB texture
  encoding, and exact unchanged position/normal arrays with styling enabled.
  Fixtures cover rotated, courtyard, concave, pitched, clipped and legacy solids;
  horizontal UV distance matches physical wall distance on diagonal walls too.
- `node tests/static_batches.cjs`: **15 checks passed**, retaining geometry/UV and
  picking/disposal contracts.
- `node tests/viewer_playback.cjs`: PASS.
- `node tests/test_studio_viewport.js`: PASS.
- `.venv/bin/python -m unittest discover -s tests -p 'test_building*.py' -q`:
  **31 tests passed**, 0.197 seconds reported. No traffic simulation was run.
- Syntax parsing for both edited JS modules and the application/browser fixture
  inline scripts: PASS. `git diff --check`: PASS.
- `tests/browser/building_geometry.html?review=facade2`: **30 checks passed** using
  the production new textured materials. Batching pixel differences at eight
  views: 0, 1, 1, 2, 0, 0, 0, 0 of 96,000 pixels above the two-level RGB tolerance;
  maximum allowed 96 per view. Fixture draw submissions: 184 → 56.
- `tests/browser/skyline_depth.html?review=facade2`: WebGL 1 and 2 each passed
  **20 views**, zero fixed-pipeline occlusion failures. Depth 24 / stencil 8,
  resize, camera clearance and disposal remained valid.

Connected-browser review of the real existing baseline
`cbd_demo_20260926T063657Z_2dde1f_sim`: full-city view, paused close-up, collapsed
side panel on the current narrow viewport, a second rotated view, and final
close-up after roof/greenery/label adjustment. No errors or warnings appeared in
the inspected console. No run/check/compile submission was made.

Final DOM diagnostics: `appearanceVersion=daylight-facades-1`, `renderState=idle`,
`staticSourceDraws=14020`, `staticBatchDraws=434`, `staticVertices=566304`.
The same baseline's preceding refinement had 975 static batches and the same
vertex count. These are opted-in static counts before culling, **not FPS or total
frame submissions**. Fewer material variants make more solids share a batch.

## Focused coverage review and remaining limitations

The read-only test-gap pass inspected style/UV generation and its direct callers.
The heuristic coverage-map script was run as a discovery aid; its file-name
matching ratio is not a coverage percentage. Pure geometry is verified separately
from browser appearance, following the repository's architecture-first workflow.

- P2: no cross-device screenshot baseline, measured production frame-time budget,
  or prolonged texture-memory/run-switch soak test. Existing cleanup and shared
  material checks do not prove all GPU/driver behaviours.
- The canvas operations in the Node style test are stubbed; the browser fixture
  provides the real texture/WebGL check. Visual quality still needs user review.
- Playwright CLI is unavailable; no CLI trace was produced or package installed.
  Existing connected-browser automation was used instead.
- Roof shapes remain the existing validated, simplified geometry. This is not a
  custom photorealistic reconstruction of each Melbourne landmark. Labels retain
  identification while the facade styling remains illustrative.

Recovery: remove only the new palette integration/UV mapping and cosmetic changes
if necessary, retaining all earlier depth, geometry and lifecycle fixes. Do not
reset the whole dirty worktree or modify stored simulation outputs.
