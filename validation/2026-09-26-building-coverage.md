# Expanded-city building coverage repair — 26 September 2026

Scope: restore missing visual building coverage, without running MATSim or
altering demand, events, roads, vehicle trajectories, terrain, or comparisons.
Working tree based on `55a3dd89931dce44b0c92f6cf9b3a44dca38eebf` with existing
uncommitted work preserved. This note does not claim the changes are committed.

## Confirmed failure and repair

- The v2 CBD landmark cache covered W/E/S/N
  `[144.945, 144.978, -37.832, -37.802]` and contained 5,622 building features.
- The current activity-domain scene displays approximately
  `[144.927988583, 145.000172241, -37.842553212, -37.797032876]`.
  Much of its outer road network was outside the cached building area.
- `scene_area_layers` also sorted buildings by height and kept at most 3,000,
  omitting 2,622 cached low-rise buildings. The displayed count after deduplication
  was 2,999. This was missing source/display coverage, not evidence of no buildings.
- `wrapper/skyline.py` now shares a validated displayed-extent conversion with
  the extractor, prefers expanded caches, retains all valid clipped footprints,
  and reports complete/partial/unknown source extent. Unknown is not complete.
- `scripts/extract_landmarks.py --scene RUN_sim --region cbd` derives its bounds
  from the actual scene and unions any earlier expanded extent. It preserves
  v2/legacy caches. Data were extracted from the already available local Victoria
  OSM PBF; no data download or dependency installation was needed.
- `scripts/refresh_scene_landmarks.py` updates the visual polygons, labels and
  safe roof profiles together in separate, original-hash-bound sidecars.
  Original result files are retained. Frontend coverage notes explicitly
  distinguish source extent from completeness/accuracy of OSM mapping.

## Actual resulting data

The new `data/landmarks/expanded/cbd.json` contains 28,233 building features.
For the current displayed bounds, 62 are outside; clipping produces 28,176
parts from 28,171 retained features. One exact duplicate footprint is removed,
leaving **28,175 building meshes**, with **zero height-limit omissions**.
Parts/meshes are not an independently verified census of unique buildings.

Cache W/E/S/N:
`[144.92797858265791, 145.0001822413595, -37.842563212326965, -37.797022876459934]`.
Cache SHA-256:
`9faed9ad41f6aa6b504a19969c252899620160f19f7fc640845332122ec67492`.

Refreshed 17 visual scene files across 11 saved runs:

- `cbd_demo_20260926T063657Z_2dde1f_sim` — skyline scene.
- `cbd_expanded1037_bootstrap_baseline_sim` — skyline scene.
- `cbd_expanded1037_detour_10it_review_r02_s{4711,4712,4713}_{baseline,closure,alternative}_a01_sim`:
  skyline scenes for all nine runs, plus IF Line difference scenes for each of
  the six intervention runs.

All have complete extraction-extent coverage. The batch refresh compared
original file bytes and all nonvisual top-level data before/after for the 16
experiment scene files. The demo scene separately retained equal roads,
vehicles, terrain, coordinate transform, time range/focus, traffic metric and
total volume. Existing comparison colours remain the recorded scenario data.
The demo original SHA-256 remains
`b5b4bf4de13b4cb71d0ab5e2bf42294dbdcc8b9d0fdb258f14b11e3852d97639`.

## Checks actually executed

```bash
PYTHONPATH=tests .venv/bin/python -m unittest \
  tests.test_landmark_geometry tests.test_building_geometry \
  tests.test_building_screen tests.test_skyline tests.test_runs \
  tests.test_pipeline_reliability tests.test_planning tests.test_api_validation -q
node tests/static_batches.cjs
node tests/building_style.cjs
git diff --check
```

- Python 3.11.9: **96 tests passed** (0.529 seconds in the final combined run).
  Pipeline messages came from mocked tests; these did not launch a simulation.
- Static batching: **15 checks passed**, including geometry/material/UV parity,
  picking, chunk bounds, rejection and disposal.
- Building style: **65 checks passed**, including unchanged solids and shared
  opaque materials. Node was the existing bundled runtime, not a new install.
- Inline JavaScript syntax checks passed; tracked diff whitespace check passed.
- An earlier test invocation without `PYTHONPATH=tests` hit an existing
  unqualified `test_network_domain` import in the reliability suite. The
  corrected command above executed all 96 tests; none were removed or weakened.

Real connected-browser inspection used the current local server, not mocked
screenshots. The demo displayed 28,175 meshes and complete coverage; zooming and
rotating from overview to closer/overhead/lower angles showed buildings in the
previously uncached neighbourhoods. No browser warning/error logs were reported.
The recorded seed-4711 closure page also loaded 28,175 meshes with its original
comparison legend/workbench, rather than accidentally showing a baseline scene.

Observed DOM batching counters changed from 434 to 857 static batches for the
demo (14,020 to 64,424 source draws; 566,304 to 2,321,385 vertices). This measures
batching structure, **not frame rate** or a performance improvement. The lazy
scene-loading button disappeared during a browser click because scrolling it
into view triggered automatic loading; subsequent DOM/image inspection verified
the loaded scene instead of retrying the missing button blindly.

The idle web process was restarted after checking no jobs were active, so fresh
exports and building screening use the expanded cache selector as well.

## Remaining verification limits

- Extent coverage does not prove every real building is mapped. Missing heights
  still use schematic defaults; footprints/roofs are not surveyed reconstruction.
- This fixes the expanded local CBD case, not all Greater Melbourne or every
  historical scene. Older unrefreshed scenes show an unknown/partial coverage note.
- Full PBF extraction was executed locally, but the CLI path and large-city
  memory/frame-rate behaviour are not yet a hermetic automated regression test.
  Coverage helper validation, >3,000 mixed-height retention, cache selection,
  provenance and sidecar safety have deterministic tests.
- No transport simulation was rerun; no traffic calibration, improved journey
  times or engineering clearance is claimed from this visual repair.
