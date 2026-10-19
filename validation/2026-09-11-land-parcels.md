# Land polygon recovery — 11 September 2026

Step 2 after `2026-09-11-skyline-depth.md`. This addresses missing/clipped land
polygons, not roof ornament design. No MATSim simulation, demand build or network
build was run. The working tree is uncommitted on base `55a3dd8`; that base commit
alone does **not** contain these changes.

## Evidence and cause

- The legacy extractor read closed ways but did not assemble area relations or
  interior rings. Vertex-inside filtering also missed enclosing/crossing areas.
- The scene exporter rejected an entire park/commercial/building polygon if any
  vertex lay outside the displayed bounds. This is not polygon clipping.
- The frontend additionally hid some valid narrow unnamed footprints using a
  bounding-box fill heuristic. This has been removed, not replaced by a hull.
- Water was not exported. Grey river areas must not be interpreted as missing
  buildings; the update now reads actual OSM water boundaries.
- On the **same legacy CBD cache**, proper clipping retains 223 park parts and
  22 commercial parts, compared with 209 and 16 in the saved scene. This isolates
  the boundary-filtering effect from the new area extraction. The legacy cache
  polygons inspected here were valid: this is not evidence that OSM was corrupt.

## Implementation

- `wrapper/landmark_geometry.py`: finite rings, batched CRS conversion,
  `make_valid` only when needed, true polygon intersection, separate parts and
  holes. Boundary-only lines are not filled land. No convex hull or minimum-fill
  rejection invents area or discards a valid thin polygon.
- `scripts/extract_landmarks.py`: osmium area assembly from ways and multipolygon
  relations, retaining source IDs/holes. One shared area job (internally two
  passes) produces all six caches. `data/landmarks/v2/` leaves legacy files intact.
- `wrapper/skyline.py`: shared polygon export and diagnostics; coordinates retain
  five decimal places in scene units so narrow rings do not collapse by rounding.
- `wrapper/static/landuse-geometry.js`: even-odd Canvas masks, tree placement
  outside holes, and Three.js extrusion with interior paths/opposite winding.
- Land-use masks remain on the terrain's own triangle grid, not separate flat
  slabs. Commercial tint is subdued; parks and water are distinct. Step 1's
  24-bit depth target is unchanged. Roof decoration logic is not redesigned.
- `scripts/refresh_scene_landmarks.py` writes separate visual refresh files.
  `wrapper/runs.py` selects them only when the original scene SHA-256 matches;
  IF Line uses its own difference scene, never a baseline refresh by mistake.
  `wrapper/pipeline.py` records the actual v2/legacy cache path and checksum.

## Actual CBD results

Source: `output/cbd_demo_20260910T001314Z_0d6a3f_sim/skyline_scene.json`.
Displayed scene bounds/CRS/scale are unchanged. Counts below are exported polygon
parts, not unique cadastral lots or rendered model counts.

| Layer | Original scene | v2 refresh | Interior rings in refresh |
| --- | ---: | ---: | ---: |
| Parks | 209 | 228 | 1 |
| Commercial land-use | 16 | 22 | 0 |
| Water | absent | 19 | 1 |
| Building footprints | 2,643 | 2,768 | 15 |

The v2 cache has 348 parks, 38 commercial areas, 33 water parts and 5,622 building
footprints before scene clipping. After projection, repair and clipping, all
3,037 exported polygons are valid and within the displayed bounds (1e-5 scene
unit tolerance for rounding). No CBD polygon was omitted by the 3,000-building
limit. Clipping split two building footprints into separate parts.

Refreshed replays (original JSON preserved):

- `cbd_demo_20260910T001314Z_0d6a3f_sim`
- `if_20260910T013146Z_4b24de_sim`
- `if_20260910T004425Z_d02682_sim`

All five sidecars' original-file hashes were checked. Every original top-level
field other than visual landmarks/geometry metadata was compared for equality,
including roads, vehicles, time range, terrain and IF Line data when present.
Existing library/tram layers were also preserved. The UI says this is an existing
replay with updated land display, not a newly completed traffic simulation.

## Verification

Environment: macOS arm64, Python 3.11.9 in `.venv`, Shapely 2.1.2, osmium 4.3.1.
Shapely was added to runtime requirements; osmium is a data-preparation dependency.

```
.venv/bin/python -m unittest discover -s tests -v
Ran 51 tests
OK — 51 passed, 0 failures, 0 errors, 0 skipped
```

17 new tests cover crossing/enclosing/outside areas, boundary touches, concave
split intersections, holes, bowtie repair, non-finite vertices, thin polygons,
legacy rings, CRS projection, a real osmium tiny-XML multipolygon fixture, full
scene export with synthetic inputs, source preservation, stale refresh rejection,
cache provenance and IF Line scene selection. External simulator stages are mocked.
The first provenance test draft failed because the temporary directory was
outside the test project root and its path was intentionally sanitized. The
fixture now sets its project root; the production privacy behavior was retained.

Browser checks, served on loopback with production Three.js r128/helpers:

- `tests/browser/landuse_geometry.html`: all 9 checks passed, including actual
  Canvas alpha pixels, hole-aware tree exclusion, triangulated area of 7,700
  instead of 8,100, finite extrusion vertices and winding independence.
- `tests/browser/skyline_depth.html`: WebGL1 and WebGL2 each retained 24-bit
  depth/8-bit stencil; 0/20 corrected-view occlusion failures (old reference
  18/20), resize/ground-clearance/disposal checks passed.
- Actual CBD app at 1280×800: city view, rotated view and top-down view inspected.
  River and clipped parks remain visible. No browser warnings/errors were
  captured during those checks. This is a bounded visual check, not exhaustive
  proof across all devices or all regions.
- Inline JavaScript and shared scripts parsed successfully using bundled Node;
  `git diff --check` passed.

![Actual CBD replay after land polygon refresh](2026-09-11-land-parcels.png)

## Remaining limits / next step

This is OSM thematic geometry, not complete Melbourne cadastral coverage. Unknown
land remains neutral, not fabricated. Relation members may have overlapping
semantic tags; this work does not claim a cadastral topology audit. Other regions
have refreshed caches but have not all undergone this visual acceptance test.
The existing 3,000-building cap remains for large views, with omissions reported
in diagnostics. River color follows the existing terrain, not a hydraulic model.
Building architectural fragments and oversized roof ornaments remain the next
separate visual-model task; this work does not claim they are solved.
