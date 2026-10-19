# Smaller vehicles and explicit illustrative density — 26 September 2026

## Scope / contract

Display-only changes in `wrapper/static/index.html`, in the existing dirty working
tree. No new simulation, population generation, server-side result rewrite,
dependency installation or change to policy comparison statistics.

- Vehicle body, cabin and axles are scaled to 0.5 of their preceding dimensions.
  Body length is now 1.925 scene units; these remain legible miniatures, not
  metre-accurate collision envelopes. Wheel-bottom clearance stays at 0.35 scene
  units above `groundY + interpolated relative deck height`, independent of scale.
- `sampleVehicleTrip` uses the saved keyframes with half-open trip intervals and
  binary search. Repeated timestamps use the outgoing segment; stops keep their
  own trip heading, not the previous vehicle's shared transform.
- True playback remains default and resets to 1:1 on each new result. Optional
  3x / 5x modes add **illustrative**, delayed poses from the same currently active
  trip. They cannot bridge a parking gap, predate that trip or survive its end.
  Minimum spacing suppresses overlapping illustrative poses, including poses
  near a real car. Therefore the multiplier is a maximum, not an exact count.
- Live UI counts separate real and illustrative cars. The density setting is
  consumed only by the renderer and is never sent to an analysis/run endpoint.
  This is prevention of statistical contamination (Control); the visible
  illustrative label is a Warning about interpretation, not traffic validation.
- Three InstancedMesh objects remain; capacity is bounded at five times the saved
  vehicles, but submitted counts contain only active/displayed cars. No extra
  per-car scene objects. Cleanup removes the density listener. The toolbar now
  sizes to its contents; the compact parameter drawer shares the canvas grid row
  so it does not cover the footer controls.

## Saved-data inspection

Read with Node `fs.readFileSync` + `JSON.parse` for `output/<run>/skyline_scene.json`:

| Run | Saved car vehicles | Driven trips | Focus time | Recorded peak active |
| --- | ---: | ---: | ---: | ---: |
| `cbd_demo_20260926T063657Z_2dde1f_sim` | 382 | 934 | 30960 | 31 |
| `cbd_expanded1037_detour_10it_review_r02_s4711_closure_a01_sim` | 382 | 934 | 30960 | 31 |

These are existing synthetic-simulation outputs, not new runs or actual users.
Neither exporter nor previous playback sampled away a percentage of car vehicles.

## Executed checks

`node` here is the bundled executable at
`/Users/erickang/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node`.

- `node tests/vehicle_density.cjs`: **46 checks passed**. Production inline code
  with real Three.js matrices: scale, cabin/axle alignment, deck clearance,
  separate counts, bounded modes, pause/change, scrub/start/end/parking,
  stationary duplicates, real-position priority, new-run reset, listener cleanup,
  duplicate timestamps and immutable input. This is not a GPU test.
- `node tests/viewer_playback.cjs`: PASS, preserving paused/new/empty/new states.
- `node tests/viewer_lifecycle.cjs`: PASS, including disposal and hidden-time jumps.
- `node tests/test_studio_viewport.js`: PASS, lifecycle/resize/pan/cleanup/fallback.
- `node tests/static_batches.cjs`: **15 checks passed**, geometry/UV/picking/disposal.
- `new vm.Script(...)` on both nonempty inline scripts: PASS.
- `git diff --check`: PASS.

Connected in-app browser, actual viewport 436x681, real saved baseline:

- At the same paused time 31045: 1:1 = 22 real / 0 illustrative / 22 displayed;
  3x = 22 / 33 / 55; 5x = 22 / 63 / 85. Real counts and time did not change.
- Timeline Home = time 150, one true car. End = 86046, zero real or illustrative
  cars even in 5x. Reload/new viewer reset to 1:1.
- Checked close-up appearance, collapsed and expanded parameter drawer, and slow
  playback. The new toolbar remains inside the narrow viewport. Browser console
  inspection returned no warnings/errors.
- Existing building/ground static diagnostics remained 14,020 source draws,
  434 batches and 566,304 vertices. This vehicle change does not modify those solids.

## Focused read-only coverage audit / limits

The architecture-first and poka-yoke skills guided the rendering/statistics split.
The test-gap-audit coverage-map script was used only as a discovery heuristic;
its filename-match percentage is not code coverage. The audit focused on the
vehicle playback implementation and its direct tests, not the entire repository.

- No measured FPS/frame-time or long-duration GPU-memory soak result is claimed.
- Browser checks cover this connected browser and viewport, not every browser/device.
- Geometry tests prove the authored clearance on a flat reference surface/deck;
  they do not prove lane-level dynamics, collision freedom or every steep terrain
  transition. MATSim link-interpolated poses are not lane-level vehicle physics.
- Illustrative followers do not add demand or predict congestion, and must not be
  used to judge the numerical size of a policy effect. Comparing policies uses 1:1
  plus the unchanged numerical analysis.
- Playwright CLI is unavailable. Its CLI trace was skipped; existing connected
  browser automation was used without installing packages.
