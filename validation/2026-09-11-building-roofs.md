# Building fragments and roof ornaments — 11 September 2026

Step 3, following depth-buffer and land-polygon fixes. No MATSim, population or
network build was run. These are uncommitted working-tree changes on base
`55a3dd8`; the base commit alone does not contain the tested implementation.

## Diagnosis

The former frontend used a centred, axis-aligned bounding rectangle for roof
ornaments. That rectangle ignored building rotation, concavities and courtyards.
On the CBD land-use-v2 scene, 84 candidates under the former high-rise crown
eligibility/size rules protrude beyond their footprints. This is a candidate
audit, not a claim that all 84 were simultaneously drawn under the old detail cap.
The frontend also added spires based on height, civic domes based on category,
and several cones to separately named Melbourne Central mall outlines.

Of 2,768 building polygons, one pair has identical normalized footprints:
`way/15477564` and `way/784947720`. Their source height values conflict (9 m and
18 m). There are also 63 other positive-area overlap pairs above 0.01 scene-unit²;
some may be legitimate podium/tower geometry, not corrupt duplicates. Four thin
footprints have low bounding-box fill but remain valid and were not discarded.

OSM distinguishes an overall outline from `building:part` volumes; roof height
is part of total building height. Overlapping footprints alone do not establish
that buildings should be merged or deleted. See the primary
[Simple 3D Buildings specification](https://wiki.openstreetmap.org/wiki/Simple_3D_Buildings).

## Changes

- `wrapper/building_geometry.py::prepare_buildings`: one pure interface for
  export and replay updates. It returns models plus diagnostics, leaving inputs
  unchanged. Exact duplicate footprints retain the taller envelope and all source
  IDs/names, with a height-conflict diagnostic. This is a display choice, not a
  resolution of the conflicting source measurements.
- High-rise roof setbacks follow a negative buffer of the footprint. Holes are
  retained; a split/narrow inset falls back to flat, not disconnected islands.
  The cap consumes at most 4.5% of existing height (capped at 1.25 scene units).
  The negative-buffer operation is documented by
  [Shapely](https://shapely.readthedocs.io/en/stable/reference/shapely.buffer.html).
- Simple low-rise gables align to the oriented footprint. Convex hipped/pyramidal
  tags use a contained apex fan, a **schematic approximation**, not a reconstructed
  hip ridge. Complex/non-supported tags fall back to flat. Clipped buildings do
  not receive invented roof details.
- `wrapper/static/building-mesh.js::SkylineBuildings.create` builds the actual
  Three.js solids from that profile, injecting the viewer's terrain-height
  function and materials. It is shared with the browser test, not duplicated.
- `wrapper/static/index.html` removes the bounding-box roof ornaments, arbitrary
  spires and name/category-based domes. Roof colour is closer to the facade colour.
  Legacy scenes safely use flat roofs. Facades and categories remain schematic.
- `scripts/refresh_scene_buildings.py` writes separate display-only sidecars.
  `wrapper/runs.py` selects them only with a matching source filename/SHA-256.
  `wrapper/skyline.py` prepares the same profiles for future scene exports.

## Existing scenes updated and audited

- `cbd_demo_20260910T001314Z_0d6a3f_sim`: skyline sidecar.
- `if_20260910T013146Z_4b24de_sim`: skyline and IF Line sidecars.
- `if_20260910T004425Z_d02682_sim`: skyline and IF Line sidecars.

Each receives 2,767 solids: 2,670 flat, 95 contained setbacks and 2 pitched roofs.
15 non-flat tags fall back to flat. One exact duplicate is suppressed with source
provenance retained. Every exported footprint is valid; all 95 inset polygons and
both pitched-roof projections were checked against the footprint (1e-6 tolerance
for serialized coordinates), and original total heights were retained.

All five sidecars were checked against their source SHA-256. Every original
top-level field except `landmarks` is equal; inside `landmarks`, every field except
`buildings` is equal. This includes traffic roads, vehicles, simulation time range,
terrain, parks, water, labels and IF Line differences where present. Original
scenes and land-use-v2 files remain in place. The webpage explicitly labels the
display as an existing replay with updated buildings, not a new simulation.

## Actual verification

Environment: macOS arm64, Python 3.11.9, Shapely 2.1.2, project `.venv`, local
Three.js r128. No dependencies installed for this step.

```text
.venv/bin/python -m unittest discover -s tests -v
Ran 67 tests in 0.055s
OK — 67 passed, 0 failed, 0 errors, 0 skipped
```

Raw output: [2026-09-11-building-tests.log](2026-09-11-building-tests.log).
The final “Running network generator for city='test'” line is a mocked runner
test's print statement, not an actual network build. No failure was removed or
relaxed to produce this result. The new 16-test file also passed with RuntimeWarning
treated as an error. An initial GEOS oriented-envelope warning for axis-aligned
rectangles was eliminated with explicit hull-edge projections, not suppressed.

Browser fixture reproduction (API already on port 8000):

```sh
.venv/bin/python tests/browser/building_fixture.py
.venv/bin/python -m http.server 8765 --bind 127.0.0.1 --directory tests/browser
# Open http://127.0.0.1:8765/building_geometry.html
```

`building_geometry.html`: **21/21 checks passed** using the production helper and
generated production profiles. Covers finite vertices, exact maximum height,
roof/solid containment, a downward ray through the courtyard with no hit, a ray
through solid with a hit, upward pitch normals, clipped/legacy fallback, and an
actual WebGL draw with no GL error. No browser errors/warnings were captured.
Inline JS and the new helper passed bundled Node syntax parsing.

Actual CBD replay: inspected city view, rotated view, zoom and top-down view at
1280×800 (so the side panel did not cover the whole scene). The selected result
reported “建筑显示已更新”; no oversized roof islands or view-dependent shredded
faces were observed in these views. Browser warnings/errors were empty. This is
a bounded visual check, not proof for every region or GPU.

The existing road-1445 branch was also opened through the normal branch button:
the result identified `if_20260910T013146Z_4b24de`, displayed its own evidence link
and comparison (car time 3 min 39 sec in both baseline and branch), and reported
updated buildings. It was not replaced by a baseline result during refresh.

![Actual CBD replay with contained roofs](2026-09-11-building-roofs.png)

## Remaining limits

The cache does not yet provide a complete `building:part`/`min_height` hierarchy.
The 63 non-identical overlap pairs are not automatically merged or removed.
Missing/complex roof tags use a conservative flat fallback; the removed generic
Melbourne Central cones have not been replaced by a surveyed landmark model.
Other historical replays without a regenerated sidecar use the safe legacy flat
fallback, not the new inset profiles. No claim of complete Melbourne architectural
reconstruction, cadastral accuracy, transport-model calibration or traffic benefit
is made. The earlier depth and land changes are preserved, not reimplemented here.
