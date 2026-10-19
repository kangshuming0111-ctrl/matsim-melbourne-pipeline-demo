# Demand/network coverage audit — 26 September 2026

## Result and scope

For existing baseline `cbd_demo_20260926T050044Z_a805bd`, **3,222 of 4,660
selected-plan activity occurrences are inside the network node bounding box:
69.14163090128755%**. The other 1,438 occurrences are outside. All coordinates
are finite. This reproduces the existing 69.1% diagnostic; it is not polygon
coverage, routing success, data accuracy or a simulation validity score.

The observed mismatch is consistent with selecting **whole intersecting SA1s**
for demand, then sampling addresses across those SA1s, while generating a road
network around a much smaller buffered study region. All 4,660 upstream activity
rows, including all 1,438 outside-bbox occurrences, carry SA1 codes inside the
selected 83-SA1 subset. There is no observed destination-SA1 leakage beyond that
subset in this baseline. This does not prove that every address is geometrically
inside its recorded SA1, nor that outside-bbox activities are inherently invalid.

This investigation read existing XML, CSV, SQLite metadata, logs and vendor
source. It ran no simulation, Docker job, installation, demand regeneration or
network regeneration. The reusable audit reads only its two supplied XML files.
No person identifiers, individual records or raw activity coordinates are
returned or retained in this report.

## Input identity and coordinate provenance

| Input | SHA-256 |
| --- | --- |
| `output/cbd_demo_20260926T050044Z_a805bd_network/network.xml` | `a1c20f60224f892b7ef1adc9bcde585ba9f0b5b8a1f74b00514c5df2eaec7473` |
| `output/cbd_demo_20260926T050044Z_a805bd_demand/8.xml/plan.xml` | `3b886ede8f0d5fac1fb17bf3602d2b09d0ada3dd986f231c5a00d0bbffaf872c` |
| `output/cbd_demo_20260926T050044Z_a805bd_demand/6.place/plan.csv` | `bddf8759360791fc6d1e638059895374742c4dda94e93991a694b74e0ba7f66c` |
| `data/cbd_demo_20260926T050044Z_a805bd_sa1_subset.csv` | `2e3cf566d1a670724b07393ca1bb28c4911f973712bbc34e8678c3af39075865` |

Both XML hashes were identical before and after the audit. The manifest records
`output_crs=7899`, `buffer_distance_m=500`, demand seed 4711 and sample percent 5.
Read-only SQLite `geometry_columns` queries independently found SRID 7899 for
network nodes/links and placed-demand points/lines. Existing Rasterio identifies
EPSG:7899 linear units as `metre`. All 4,660 XML activity types and numeric x/y
pairs exactly match the corresponding ordered `6.place/plan.csv` rows.

These provenance checks support interpreting this baseline's distances in metres.
The general two-path interface cannot establish CRS from arbitrary XML files and
deliberately returns `coordinate_units="input_coordinate_units"` and
`crs_verified=false`. It performs no reprojection or coordinate inference.

## Aggregate evidence

- Network: 684 nodes, all finite with identifiers; 2,464 directed links; 1,083
  explicitly permit `car`. Every car link has usable endpoints; none has zero
  geometric length. No links lack mode declarations.
- Node bbox, ordered `[xmin, ymin, xmax, ymax]`:
  `[2495547, 2408309, 2497672, 2410359]` (2,125 by 2,050 coordinate units).
- Population: 1,037 persons, 1,037 plans, all `selected="yes"`; no ambiguous
  selection, fallback, unaudited persons or empty plans. Thus the old first-plan
  check and new selected-plan check use identical plans for this baseline.
- Activities: 4,660 total and finite; missing, invalid numeric text and
  NaN/infinite coordinate-pair counts are all zero.
- 699 persons have at least one outside-bbox activity; 195 have an outside-bbox
  Home; 632 have an outside-bbox non-Home; 504 have outside non-Home activities
  without an outside Home. Person counts overlap as stated and are not additive.
- 404 of 2,140 Home occurrences are outside; 1,034 of 2,520 non-Home occurrences
  are outside. Repeated home visits are separate occurrences, not distinct homes.
- 82 of the 83 selected SA1s occur in the placement rows. The 1,438 outside-bbox
  occurrences are assigned to 25 distinct selected SA1s. Both `5.locate/plan.csv`
  and `6.place/plan.csv` have 4,660 rows and zero SA1 codes outside the subset.

| Activity type | Total | Inside bbox | Outside bbox | Inside fraction |
| --- | ---: | ---: | ---: | ---: |
| Home | 2,140 | 1,736 | 404 | 81.12% |
| Work | 418 | 220 | 198 | 52.63% |
| Study | 482 | 398 | 84 | 82.57% |
| Personal | 330 | 160 | 170 | 48.48% |
| Shop | 291 | 153 | 138 | 52.58% |
| Social/Recreational | 311 | 156 | 155 | 50.16% |
| Pickup/Dropoff/Deliver | 318 | 186 | 132 | 58.49% |
| Other | 370 | 213 | 157 | 57.57% |
| **All** | **4,660** | **3,222** | **1,438** | **69.14%** |

Mode below is the immediately arriving XML leg, not an inferred trip main mode.
The 1,037 initial activities have no arriving leg; omitting them would change the
denominator. Departing-mode groups are also available from the module.

| Arriving leg mode | Activity occurrences | Inside bbox | Outside bbox |
| --- | ---: | ---: | ---: |
| No adjacent incoming leg | 1,037 | 842 | 195 |
| car | 934 | 649 | 285 |
| pt | 977 | 385 | 592 |
| walk | 1,598 | 1,255 | 343 |
| bike | 114 | 91 | 23 |

| Leg mode | Total legs | Both endpoints inside | Inside to outside | Outside to inside | Both outside |
| --- | ---: | ---: | ---: | ---: | ---: |
| car | 934 | 415 | 220 | 234 | 65 |
| pt | 977 | 142 | 336 | 243 | 256 |
| walk | 1,598 | 932 | 246 | 323 | 97 |
| bike | 114 | 72 | 17 | 19 | 6 |

Therefore **519 / 934 car legs (55.57%) have at least one outside-bbox endpoint**.
These counts do not determine whether MATSim finds a route after assigning
activity links. No leg has missing adjacent activities or unusable coordinates.

## Distance to the car network

Shapely 2.1.2 `STRtree` finds the closest straight segment between each explicit
car link's endpoint nodes. This is distance to a segment, not just to a node,
and excludes walk-only/bike-only links. It ignores direction, connectivity,
barriers, intermediate road geometry and MATSim's own activity-link assignment.
The vendor network pipeline itself simplifies final edges into straight links
at `vendor/network/NetworkGenerator.R:302`, but this does not certify real-road
geometry or pedestrian access. Zero distance is not a routing guarantee.

Quantiles use nearest rank: element `ceil(p * count) - 1` in sorted distances.
Threshold counts use strict `>` and are diagnostic bins, not acceptance limits.
Every finite activity received a finite distance for this baseline.

| Activity group | Count | Mean m | p50 m | p95 m | Max m | >100 m | >500 m | >1,000 m |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| All | 4,660 | 96.50 | 8.74 | 442.89 | 1,497.69 | 1,284 | 153 | 28 |
| Inside bbox | 3,222 | 10.95 | 3.09 | 51.21 | 277.93 | 94 | 0 | 0 |
| Outside bbox | 1,438 | 288.17 | 272.88 | 676.17 | 1,497.69 | 1,190 | 153 | 28 |
| Adjacent to at least one car leg | 1,452 | 83.68 | 8.12 | 377.56 | 1,398.58 | 363 | 31 | 4 |

Each car-endpoint activity occurrence is counted once even if it lies between
two car legs. There are 425 outside-bbox occurrences in this group. Distances to
car infrastructure for other modes provide context, not mode-specific access
quality. In particular, teleported PT does not establish timetable/transit coverage.

## Upstream causes and what remains uncertain

1. **Intersecting SA1 selection is not address containment.**
   `vendor/demand/R/derive_sa1_subset.R:14–20` transforms the study region into
   the SA1 CRS, buffers it, then uses `st_intersects`. It writes whole SA1 codes;
   it does not cut those SA1s or restrict their addresses to the buffered region.
2. **Address filtering operates on SA1 membership.**
   `vendor/demand/R/setup.R:102–119` subsets destination-region data;
   `:158–166` reprojects addresses and filters by SA1 code; `:177–185` does the
   same for centroids. No network bbox or study-region polygon is used there.
3. **Coordinates are chosen within the selected SA1's available address data.**
   `vendor/demand/R/locations.R:347–360` samples by SA1 and category, weighted by
   address count; if that category is absent it falls back to the SA1 centroid.
   `vendor/demand/R/placeParallel.R:29–38` applies this to Home and other
   activities and reuses the Home coordinate. Neither checks road-network extent.
   This audit has not measured how many activities used centroid fallback.
4. **The network uses a different geometric construction.**
   `vendor/network/functions/getOsmExtract.R:15–21,44–67` buffers the study region
   in the output CRS, extracts OSM features, then filters by intersection with
   that region. `NetworkGenerator.R:218,251–252,270–275` retains connected
   structure and removes dangles. Its final node bbox is consequently neither
   the selected SA1 union nor the study-region polygon. The SA1 source SRID is
   28355 while the network output SRID is 7899; both are projected, but no claim
   is made that their buffers are numerically identical. Individual effects of
   network cleaning, projection and centroid fallback have not been isolated.
5. **`allDestinations=TRUE` is not supported as this run's explanation.**
   The vendor function's direct default is TRUE, but
   `wrapper/demand_runner.py:34,43` and `vendor/demand/R/run_from_env.R:19` default
   the wrapper path to FALSE. `makeExamplePopulation.R:95,107` passes the subset
   into both destination setup and population sampling when FALSE. The observed
   absence of out-of-subset SA1 rows supports scoped generation here. Caution for
   future use: setting TRUE also bypasses the population-sampling subset, not
   merely destination filtering. The exact environment of the historical Docker
   process was not independently recovered; do not infer it from defaults alone.

The original `wrapper/scenario.py:48–75` check scans the first plan, treats the
node rectangle as a sanity check, and has no type/mode/distance breakdown. Its
69.1% alone cannot distinguish outside destinations from missing coordinates,
selection mistakes or network geometry. Those diagnostic distinctions now live
in the new module; this isolated task did not change existing orchestration.

## Integration interface

```python
from pathlib import Path
from wrapper.coverage_audit import audit_coverage

report = audit_coverage(
    Path("output/cbd_demo_20260926T050044Z_a805bd_network/network.xml"),
    Path("output/cbd_demo_20260926T050044Z_a805bd_demand/8.xml/plan.xml"),
)
```

`audit_coverage(network_path: str | Path, plans_path: str | Path) -> dict` takes
file paths, not output directories. It supports `.xml` and `.xml.gz`, namespaced
XML, `<activity>` and `<act>`. It does not read adjacent manifests, region files,
databases or global configuration. It returns schema version 1:

| Field | Meaning / integration use |
| --- | --- |
| `method` | Selection policy, coordinate-unit caveat, distance availability, quantile/threshold rules |
| `network` | Coordinate quality, explicit car-link/endpoint counts, node bbox |
| `plans` | Audited/unaudited selection counts and aggregate affected-person counts |
| `activities` | Total/finite/missing/invalid/nonfinite occurrences, bbox counts and distances |
| `activities.inside_node_bbox_fraction_of_finite` | Nullable fraction, **0–1**, denominator explicitly finite selected-plan activities |
| `by_activity_type` | Same occurrence statistics for each XML activity type |
| `by_arriving_leg_mode`, `by_departing_leg_mode` | Same statistics by adjacent leg, including `__no_adjacent_leg__` and `__missing__` |
| `by_bbox` | Separate inside/outside distance summaries |
| `car_endpoint_activities` | Activity occurrences adjacent to one or two car legs, counted once per occurrence |
| `legs_by_mode` | Counts of both-inside, crossing, both-outside and unavailable endpoints |
| `limitations` | Structured `{code, message}` diagnostics; no pass/fail decision |

Each activity summary has `nearest_car_distance` with `count`,
`unavailable_for_finite_coordinates`, nullable `min/mean/p50/p95/max`, and
`count_greater_than` with string keys `"100"`, `"500"`, `"1000"`. The same units
caveat applies to all groups. No distance is fabricated when Shapely is missing,
no usable explicit car links exist, or finite coordinates overflow distance
calculation; availability and limitation fields identify these conditions.

Plan selection uses exactly one explicit `yes/true/1` plan; a single unmarked plan
is a separately counted fallback. Multiple selected plans, unknown flags, or no
unique selection among alternatives are counted as unaudited. A sole explicitly
deselected plan is not used. Unselected alternatives never inflate activity
counts. Home-person diagnostics use case-insensitive exact `home`; richer
activity naming conventions need a separately agreed mapping.

Coordinate quality counts describe **pairs**, with exclusive precedence missing
axis/blank value, invalid numeric text, nonfinite number, finite pair. Link-only
or facility-only activities have missing coordinates; the audit does not impute
their locations. Spatial fractions exclude unusable pairs; a missing bbox or
empty finite denominator returns `None` / JSON `null`, never a misleading zero.
All finite network nodes contribute to the rectangle, including isolated nodes.
The full report serializes with `json.dumps(report, allow_nan=False)`.

Filesystem errors (`OSError`) and malformed XML (`ElementTree.ParseError`)
propagate. Wrong XML roots and duplicate network node IDs raise `ValueError`;
callers should report an unavailable audit rather than convert these to zero
coverage or automatic simulation rejection. A syntactically valid empty network
or population returns explicit empty/unavailable diagnostics. XML is streamed
per person/node/link. Memory grows with network size and audited activity
distance samples, not the complete population XML tree. Full metropolitan-scale
performance was not benchmarked.

The main integration can store this dict in run evidence and present its named
limitations. The legacy scalar path should be migrated to this single result
where integration is authorized, with missing evidence distinguished from low
overlap. Do not add a coverage cutoff that automatically declares a run invalid.
This task changed only the audit module, its tests and this document; it did not
edit `scenario.py`, `pipeline.py`, `api.py`, UI or vendor code.

## Actionable next planning decisions

- Choose an explicit modeled population and destination scope. For a CBD policy
  study, retaining all activities and enlarging the modeled network to cover
  their intended geography is one option; an explicit boundary-demand treatment
  is another. Either changes the experiment and needs its own comparison.
- If choosing a strictly local population, define that at generation time and
  report exclusions and representativeness. Do not silently clip coordinates,
  remove persons/activities or shrink to whole-contained SA1s merely to raise a
  coverage percentage.
- Keep network extent and demand-population extent independently controllable.
  Raising the current shared buffer also selects more SA1s, potentially creating
  another ring of boundary addresses rather than resolving the mismatch.
- Review the 519 car legs with an outside endpoint and the aggregate distance
  distributions, then inspect actual MATSim activity-link assignment/routing
  separately before transport interpretation. Bbox and Euclidean distance alone
  cannot settle connectivity, access, congestion validity or external-trip intent.

## Verification and reproduction

Using the existing `.venv` (Python 3.11.9, Shapely 2.1.2), the focused suite
completed with **15 passed, 0 failures, 0 errors, 0 skipped** (0.073 seconds).
It checks selected-plan exclusion and ambiguity, home/person counting,
mode/leg transitions, inclusive bbox edges, point-to-segment geometry rather than
node distance, car-mode token filtering, empty inputs, missing/nonfinite values,
unusable network endpoints, zero-length links, gzip/namespaces, absent Shapely,
numeric overflow, strict JSON serialization, malformed input errors, exclusion
of person identifiers, and source-file SHA-256 preservation.

An independent NumPy calculation projected every one of the 4,660 activity
points onto all 1,083 car segments, using the endpoint-vector formula and
choosing the minimum Euclidean distance. It agreed with the indexed Shapely
distances to a maximum absolute difference of `1.1368683772161603e-13` coordinate
units. Mean and all three threshold counts agreed; activity-type, arriving-mode
and leg-mode totals also reconciled. NumPy was used only for this independent
verification, not added as a production dependency. New-file whitespace checks
passed using `git diff --no-index --check` against `/dev/null`.

```bash
.venv/bin/python -m unittest discover -s tests -p test_coverage_audit.py -v
.venv/bin/python - <<'PY'
import json
from wrapper.coverage_audit import audit_coverage

prefix = "output/cbd_demo_20260926T050044Z_a805bd"
report = audit_coverage(prefix + "_network/network.xml",
                        prefix + "_demand/8.xml/plan.xml")
print(json.dumps(report, indent=2, allow_nan=False))
PY
```

Independent read-only reproduction of the upstream subset and XML/placement
agreement, printing only aggregates:

```python
import csv
from pathlib import Path
import xml.etree.ElementTree as ET

prefix = "cbd_demo_20260926T050044Z_a805bd"
demand = Path("output") / (prefix + "_demand")
with (Path("data") / (prefix + "_sa1_subset.csv")).open() as stream:
    subset = {row["SA1_MAINCODE_2016"] for row in csv.DictReader(stream)}
with (demand / "6.place/plan.csv").open() as stream:
    rows = list(csv.DictReader(stream))
acts = ET.parse(demand / "8.xml/plan.xml").getroot().findall("./person/plan/activity")
outside = [row for row in rows if not (
    2495547 <= float(row["x"]) <= 2497672 and
    2408309 <= float(row["y"]) <= 2410359)]
print({
    "subset_sa1_count": len(subset),
    "row_count": len(rows),
    "outside_subset": sum(row["SA1_MAINCODE_2016"] not in subset for row in rows),
    "outside_bbox": len(outside),
    "outside_bbox_sa1_count": len({row["SA1_MAINCODE_2016"] for row in outside}),
    "xml_matches_placement": len(acts) == len(rows) and all(
        (act.get("type"), float(act.get("x")), float(act.get("y"))) ==
        (row["Activity"], float(row["x"]), float(row["y"]))
        for act, row in zip(acts, rows)),
})
```

Expected result: `83`, `4660`, `0`, `1438`, `25`, `True`, respectively. Existing
simulation success, convergence, routing correctness, polygon membership and
clean-environment installation were not tested by this audit.
