# Static city batching and impact-response refinement — 26 September 2026

Follow-up to `2026-09-26-viewer-performance.md`. This is a local validation record
for uncommitted working-tree changes on top of `55a3dd8`, not a release benchmark.
Other existing working-tree changes were preserved. No MATSim simulation, Docker
build, dependency installation, output regeneration, or result deletion was done.

## Contract and changes

- `wrapper/static/static-batches.js` owns an opt-in render-only batch group and
  its new geometry buffers. It groups opaque, immutable triangle meshes by spatial
  tile, exact material identity, attributes, and render/shadow settings. It does
  not simplify or remove triangles, change footprints, or replace domain IDs.
  Transparent, animated, unsupported, and partially drawn meshes remain on their
  original render path. Invalid batch limits throw; sources are hidden only after
  all batches have been built. Disposal is idempotent and restores the originals.
- `wrapper/static/index.html` opts static building solids, opaque car-road bodies,
  and curbs into batching. Original hidden road meshes remain the picking and
  selection-overlay sources. This is specific to bundled Three.js r128, whose
  raycaster does not exclude an object merely because `visible` is false. Tested
  against the actual bundled engine and by selecting a real road in the UI.
  [r128 Raycaster source](https://github.com/mrdoob/three.js/blob/r128/src/core/Raycaster.js)
- Lane-marking meshes now share one texture/material; length-dependent repeat is
  encoded in each mesh's UVs. Vehicles, traffic ribbons, land-use surfaces, terrain,
  lighting, and D24S8 depth-buffer settings are not changed by batching.
- Playback controls reset when a new run replaces a paused run, and explicitly
  disable playback for a run with no vehicles. This fixes a stale “play” label
  while the replacement scene was already playing.
- `wrapper/api.py:planning_impact` returns the existing JSON-native analysis via
  `JSONResponse`, avoiding FastAPI's redundant recursive conversion. It sends
  `Cache-Control: no-store`, rejects non-finite JSON, and does not add an analysis
  cache or change any analysis formula.

## Measurements on the existing local runs

Run pair:

```
A: cbd_expanded1037_detour_10it_review_r02_s4711_baseline_a01_sim
B: cbd_expanded1037_detour_10it_review_r02_s4711_closure_a01_sim
```

### Rendering

Read from the production page's `#skylineContainer` DOM dataset after loading B:

| Opt-in static geometry | Before batching | After batching |
|---|---:|---:|
| Draw submissions before view culling | 14,018 | 975 |
| Triangle vertices retained | 566,232 | 566,232 |

These are counts for the opted-in static subset, **not** whole-frame GPU calls,
FPS, or a percentage frame-time improvement. Other geometry remains outside this
batch. The latest baseline loaded in the planning studio measured 14,020 → 975
submissions and 566,304 retained vertices.

### Read-only impact API

Same GET `/ifline/impact?baseline=<A>&proposal=<B>`, defaults unchanged. Local
Python `urllib.request.urlopen` wall time, including reading the full response:

| HTTP samples | Seconds | Response bytes |
|---|---|---:|
| Before | 1.338, 1.337 | 11,002,208 |
| After service restart | 0.777, 0.748, 0.732 | 11,002,208 |

The before response and all three after responses had the identical SHA-256:

```
e1aac76495f7d0c74f374c450b7060a94d0d4fdaeef751f680555586d4d53d84
```

A separate pre-change component measurement found approximately 0.607 s in
analysis, 0.599 s in `jsonable_encoder`, and 0.104 s in JSON response encoding;
native and recursively converted payloads encoded to identical bytes. These are
small local samples, not a concurrency/load benchmark or a performance guarantee.
The payload is still approximately 11 MB. A web-service restart was necessary;
no active/queued jobs were present when the previous service was stopped.

## Checks actually executed

Node was the existing bundled executable:
`/Users/erickang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node`.

- `node tests/static_batches.cjs`: **15 checks passed** against bundled r128.
  Triangle/material/normal/UV parity, transformed parents and scene, bounded
  chunks, road identity and raycasting, unsupported-object rejection, and resource
  ownership/disposal. A 1,000-box same-material fixture becomes one batch while
  retaining all 12,000 triangles.
- `node tests/viewer_playback.cjs`: PASS. Paused → replacement run → empty run →
  replacement run; labels, active state, disabled controls, old-listener cleanup.
- `node tests/viewer_lifecycle.cjs`: PASS. Scheduling, cancellation, retry,
  disposal, visibility, and no hidden-time jump.
- `node tests/plan_state.cjs`: PASS. Defensive state, undo/redo and revisions.
- `node tests/test_studio_viewport.js`: PASS. Lifecycle, resize, pan and cleanup.
- `.venv/bin/python -m unittest discover -s tests -p 'test_impact*.py' -q`:
  **47 tests passed**, final run 0.237 s. Includes direct native-JSON response,
  no-store header, exact nested content, and rejection of NaN as a success payload.
- `node --check wrapper/static/static-batches.js`, plus `vm.Script` parsing of
  both nonempty inline scripts in `index.html`: PASS.
- Existing browser `tests/browser/building_geometry.html`: **30 checks passed**.
  Eight before/after views at 400 × 240 pixels: respectively 0, 1, 1, 1, 0, 0, 0,
  0 pixels differed by more than two RGB levels (maximum allowed 96 pixels per
  view). Total renderer draw submissions over those eight fixture views: 184 → 56.
- Existing browser `tests/browser/skyline_depth.html`: WebGL 1 and 2 each passed
  **20 views**, with **zero** fixed-pipeline occlusion failures. Both render
  targets retained depth 24 / stencil 8; resize, clearance and disposal passed.
  The legacy low-depth pipeline failed 18/20 views in each context, confirming
  this fixture still detects the original failure class.
- Existing browser `tests/browser/road_geometry.html`: **373 assertions passed**.
  This covers the existing terrain-relative geometry helper, not engineering
  validation of an independent bridge design.
- `git diff --check`: PASS.

Real application interactions (not just a fixture): opened B, loaded the city,
paused playback, switched camera presets, entered the planning studio, clicked
road 4027 / reverse 9491, and rotated the paused city. The side panel retained
the selected road's 50 m / 40 km/h / one-lane / 600 per hour attributes; buildings,
ground and roads remained visible in the inspected views. No warning or error
appeared in the inspected console entries. No check/compile/run POST was submitted.
The page was then restored to the original A/B comparison URL.

## Focused test-gap review and limitations

The architecture-first / misuse-prevention review kept domain IDs separate from
render batches and made unsupported render states fall back rather than disappear.
The test-gap audit was read-only and scoped to this refinement; its source/test
name-matching output was not treated as a coverage percentage.

- Remaining P2: no controlled production-scale FPS, frame-time, GPU-time, or heap
  benchmark across devices/browsers. No prolonged run-switch/drag stress test.
- Original CPU geometry is retained for selection and merged geometry adds buffers.
  This is a draw-submission optimization, **not** a verified memory reduction.
- Transparent lane markings and traffic ribbons still use their existing render
  path; the whole frame does not become 975 calls.
- Original sources must remain immutable until batches are rebuilt. Future code
  that moves an existing source must rebuild/dispose its batch, not mutate it alone.
- Pixel parity was tested with representative fixtures. The real-city visual and
  picking checks do not prove every possible camera/selection/device combination.
- The Playwright CLI prerequisite is not installed, so CLI traces were skipped.
  The available connected browser performed the checks above; no package was fetched.
- Successful visualization checks do not validate or calibrate the traffic model.

Recovery: revert only this render-batching integration, shared lane UV change,
playback-reset change, and direct impact JSON response if needed. Preserve the
earlier depth/lifecycle fixes, unrelated working-tree edits, and all saved outputs.
