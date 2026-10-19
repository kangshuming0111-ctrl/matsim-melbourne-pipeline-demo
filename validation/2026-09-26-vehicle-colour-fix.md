# Vehicle colour regression fix — 26 September 2026

## Scope and cause

Display-only correction in `wrapper/static/index.html`, in the existing dirty
working tree. No simulation, output regeneration, dependency installation,
statistical changes, commit or push. This note supersedes the vehicle appearance
and three-mesh description in `2026-09-26-vehicle-presentation.md`, not its
historical execution results.

The previous compact-instance optimization set `mesh.count=0` before the first
`setColorAt`. Inspection of the bundled Three.js r128 implementation confirmed
that lazy colour allocation uses `new Float32Array(3*this.count)`, not the
instance-matrix capacity. The resulting zero-length attribute silently lost
every paint write. Dark cabin material also dominated the top view, but was not
the only cause. The earlier CPU tests did not assert colour capacity or finite
values; that was a real verification gap.

## Changes

- Painted instances allocate a full-capacity, dynamic RGB attribute before their
  visible count is compacted. Capacity and current draw count are independent.
  This prevents an initially empty/sparse frame from truncating later colours.
- Body and new small roof share paint and per-car colour. The cabin tapers toward
  the roof, with grey-blue glass; tyres remain dark. Paint has low metalness and
  moderate roughness. The palette includes ivory, silver, blue, coral, yellow,
  mint and slate. Paint carries no traffic metric.
- Four instanced meshes, not four objects per car. Existing half-size dimensions,
  ground/deck clearance, trip boundaries, density labelling and cleanup remain.
- Checked other `setColorAt` usage: tree crowns keep their full allocation count
  at initialization and do not have this zero-count sequence.

## Executed checks

Node executable: bundled `codex-primary-runtime/dependencies/node/bin/node`.

- `node tests/vehicle_density.cjs`: **113 checks passed**, including full colour
  capacity, finite paint, distinct colours, body/roof agreement, initial zero
  cars followed by eight arrivals, tapered geometry, roof clearance, playback,
  density, parking gaps and cleanup.
- `node tests/viewer_playback.cjs`: PASS.
- `node tests/static_batches.cjs`: **15 checks passed**.
- `node tests/viewer_lifecycle.cjs`: PASS.
- Inline JavaScript syntax compilation with `vm.Script`: PASS.
- `git diff --check`: PASS.

`tests/browser/vehicle_appearance.html` is an isolated synthetic eight-car WebGL
fixture that loads the production playback function and bundled Three.js. It was
opened via a temporary loopback static server, using the city daylight/tone-mapping
settings. Before the capacity correction all roof probes returned the same glass
colour; after correction **all 11 checks passed**, including distinct actual
render-target RGB samples, no WebGL error and four instanced submissions. Top and
oblique screenshots were visually inspected. This is not a MATSim simulation.

Actual application check: saved baseline `cbd_demo_20260926T063657Z_2dde1f_sim`,
connected in-app browser, 1280x720 viewport. Opened the 3D studio, changed view,
zoomed, paused and resumed slow playback. At paused time 31117, density 1/3/5
showed the same **22 real cars**, with respectively **0/38/72 illustrative cars**.
No captured browser warnings/errors. No run/comparison action was submitted.

## Limits

The tests are focused regressions, not whole-project coverage or a measured FPS
benchmark. Pixel probes use an isolated daylight fixture; they do not promise
identical RGB under every city shadow, angle, GPU or browser. The CLI Playwright
executable was unavailable; connected-browser automation was used instead, with
no new installation or CLI trace. Existing traffic statistics remain unchanged.
