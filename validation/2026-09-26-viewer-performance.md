# Viewer scheduling and selection performance — 26 September 2026

Later follow-up: [static batching and impact-response refinement](2026-09-26-static-batching.md)
addresses the individual-mesh and API-conversion limitations recorded at the end
of this earlier check. The before/after observations below remain this patch's evidence.

## Scope / contract

No simulation, input, output artifact, analysis formula, road identity, footprint,
or depth-buffer change. Existing uncommitted project work was preserved.

- `impact-ui.js` owns its applied analysis snapshot, selected IDs and focus ID.
  A small pointer-inert overlay consumes that state; inspecting/selecting/clearing
  links and resetting the view no longer rebuilds base geometry. A/B layer changes
  still build the appropriate full geometry. All directed links remain selectable.
- `viewer-lifecycle.js` owns coalesced deferred loading and frame scheduling.
  Disposal aborts loading and prevents late publication even when transport ignores
  abort. Offscreen/hidden viewers have no queued animation frame; static paused
  viewers go idle. User input, camera changes and editor overlays invalidate a frame.
  Resume starts with zero elapsed time, avoiding a hidden-time playback jump.
- `index.html` is the adapter: it defers the fallback network/map and 3D creation,
  preserves explicit studio entry and asynchronous workbench-to-3D positioning,
  and disposes the previous viewer/observers/listeners/textures on run replacement.
  Static scene files revalidate with HTTP validators (`no-cache`), not timestamp
  URLs or an unvalidated application cache. No backend analysis cache was added.
- An A/B override is passed to the initial workbench open; it no longer launches
  an immediately superseded default-pair analysis first.

## Direct browser checks

Existing in-app browser, localhost:8000, real completed closure result:
`cbd_expanded1037_detour_10it_review_r02_s4711_closure_a01_sim`.

| Observation | Before | After |
|---|---:|---:|
| Whole-page element count after result load | 58,490 | 35,831 |
| Folded fallback map descendants | 22,662 | 0 |
| 3D canvases before scrolling to the city | 1 | 0 |

Counts include the same full 11,331-link workbench map. They are DOM measurements,
not FPS, GPU timings, process memory, or a causal percentage speedup.

- Clicked real link 8591, then “在下方 3D 中定位”: deferred scene loaded, focused
  on the city, one canvas, running state, no console errors/warnings observed.
- Scrolled away by using the workbench reset button: suspended state and playback
  stayed at 08:38 on two separated checks instead of advancing offscreen.
- Entered the actual planning studio: ready editor message, one canvas, fallback
  SVG still empty. Paused playback: idle state at 08:37. Camera preset remained
  usable and settled back to idle. Exited the studio successfully.
- Expanded fallback editor: 11,331 selectable lines appeared. Closed it again.
- No run/check/compile POST or MATSim job was initiated in these checks.

## Executed checks

Bundled Node executable was used (not installed on ordinary shell PATH):
`/Users/erickang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node`.

- `node tests/viewer_lifecycle.cjs`: PASS; deferred single-flight load, abort with
  late response, retry, idempotent disposal, offscreen scheduling, idle wake-up,
  hidden document, collapsed element, observer cleanup and resume time semantics.
- `node tests/test_studio_viewport.js`: PASS.
- `node tests/plan_state.cjs`: PASS.
- Syntax checks of changed JS and inline application/fixture scripts: PASS.
- `.venv/bin/python -m unittest discover -s tests -p 'test_impact*.py' -v`:
  45 tests passed (0.257 seconds reported by unittest).
- `tests/browser/impact_workbench.html`: 294 checks / 19 scenarios passed using
  the production workbench script, deterministic GET responses, no simulation.
  Added 11,331-link scenario: 20 inspections, same base/hit DOM identities,
  no base-SVG child mutations; handler sample total 8.7 ms on this browser run.
  This synthetic-network handler measurement excludes paint and is NOT real-data
  FPS or a before/after speedup. Lazy 3D focus, retry and retired-session cases pass.
- `tests/browser/skyline_depth.html`: WebGL 1/2 each passed 20 views with zero
  fixed-target occlusion failures. D24S8, resize, clearance, disposal preserved.
- `tests/browser/studio_layout.html`: completed the existing viewport/side-panel
  checks including 320px width and displaced viewport cases.
- `git diff --check`: PASS.

## Focused test-gap audit / limitations

Read-only coverage mapping and caller review were used to identify risk at the
new lifecycle seam; the heuristic source-name map is not line coverage. Deterministic
tests protect cancellation/idle states and unchanged map-node identities; actual
browser checks cover the production adapters. No runtime dependencies installed.
The CLI Playwright prerequisite was absent, so CLI traces were NOT executed;
existing browser automation was used instead, not claimed as a CLI trace.

Remaining P2 gaps: automated production-scale frame-time/heap budgets across
Safari/Chrome/devices and long repeated editor/run-switch sessions; rapid real
pointer dragging while paused is input-wired but not a full end-to-end gesture
matrix. No controlled FPS/GPU benchmark was recorded. Visible animated 3D still
uses the existing individual building/road meshes and bloom. The ~1.35-second
analysis request and ~11 MB response measured in diagnosis are not optimized by
this patch. No claim that all possible sources of lag are fixed.

Recovery: revert only these lifecycle/selection changes and the added script tag
if a regression is found; never restore the whole dirty checkout or delete outputs.
