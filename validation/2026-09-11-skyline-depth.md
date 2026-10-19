# Step 1 — city depth / occlusion regression

Validated on 2026-09-11 (Australia/Melbourne), against the working tree based
on `55a3dd8`. This repository has pre-existing uncommitted work; this is not a
claim that the complete working tree is represented by that commit.

## Scope

Only the renderer/camera setup changed. No MATSim simulation was run. Existing
scene files, land-use filtering, building footprints, rooftop geometry, traffic
colours and simulation parameters were not changed by this fix.

The old page was loaded before the edit and replayed
`cbd_demo_20260910T001314Z_0d6a3f_sim`. Its full-screen view reproduced rear roads
and building fragments showing through nearer buildings. The same replay was
then opened after reloading the modified page.

## Cause and change

The bundled Three.js is r128. EffectComposer's default offscreen targets request
16-bit depth, independently of the canvas's depth precision. The old perspective
camera used near=0.12 and far=1800, further concentrating precision near the eye.

`wrapper/static/skyline-rendering.js` now provides the production camera and
pipeline shared with the regression fixture:

- near=1, far=1800; existing field of view and camera presets retained.
- Explicit packed depth/stencil scene targets. Both composer targets measure
  24 depth bits and 8 stencil bits on the tested contexts, with complete FBOs.
- Preserve device pixel ratio when constructing/resizing an explicit target.
- Clamp the eye above terrain **after** OrbitControls updates, translating the
  target with the eye so the look direction is preserved.
- Release the per-view composer/bloom targets and materials when replacing a
  scene (r128 has no EffectComposer.dispose()).

## Executed WebGL regression

`tests/browser/skyline_depth.html` runs against the **same production helper and
bundled Three.js**, inside the real in-app browser, not mocked WebGL.

It draws two parallel surfaces 0.18 scene units apart (the city ground-to-road
offset), deliberately draws the rear blue surface after the near red surface,
and checks an 8x8 centre pixel patch. The near surface must remain red regardless
of draw order. Both paths include RenderPass and UnrealBloomPass. Distances:
50, 130, 460, 900. Camera angles: -60, -30, 0, 30, 60 degrees.

| Context | Old depth | New depth (both targets) | Old failed views | New failed views |
| --- | --- | --- | --- | --- |
| WebGL 2 | 16 | 24 | 18 / 20 | 0 / 20 |
| WebGL 1 | 16 | 24 | 18 / 20 | 0 / 20 |

Additional checks passed in both contexts:

- Resize with pixelRatio=2: 96x80 logical -> 192x160 target; depth remains >=24,
  near-surface colour remains correct.
- Terrain clearance and preservation of camera-to-target direction.
- Target texture release and repeated disposal without an exception.
- No WebGL error from the test operations.

The first fixture execution caught a misspelled r128 bloom material property
in cleanup; it was corrected before the successful full rerun above.

To reproduce locally (two terminals, from the project root):

```sh
.venv/bin/python -m uvicorn wrapper.api:app --host 127.0.0.1 --port 8000
```

```sh
.venv/bin/python -m http.server 8765 --bind 127.0.0.1 --directory tests/browser
```

Open `http://127.0.0.1:8765/skyline_depth.html`. The page reports measured depth,
failure counts, resize and cleanup results. Unsupported contexts are explicitly
reported as skipped; failure to create any WebGL context is not a pass.

## Application / static checks

- Same existing CBD replay: city preset, rotation to other sides, low-angle
  skyline, overhead preset and repeated scroll zoom. Previously visible
  through-building strips / view-dependent fragmentation were no longer seen
  in these checks.
- Exit and reopen the planning studio: scene loads again, vehicle count/time
  continue updating, no captured browser warning/error entries.
- Node syntax checks passed for the production helper and inline scripts in
  the application and browser fixture. `git diff --check` passed.

## Limits / following steps

The pixel test is a rendering regression, **not** a simulation or traffic-model
validation. Application views were inspected manually, not exhaustively checked
pixel-by-pixel. Other GPUs/browsers have not been validated. This does not provide
building collision avoidance for a camera moved inside a building.

Missing/cross-boundary land parcels and the protruding procedural rooftop boxes
remain separate, pending steps. Neither was hidden or deleted to make this test
pass.
