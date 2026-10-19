# Fixed-demand network-domain expansion — 26 September 2026

## Scope and reproducible command

The authorized change generates a new road network for the existing
`cbd_demo_20260926T050044Z_a805bd` demand. It does not regenerate, clip, delete,
snap or otherwise change demand, run MATSim, modify the planning-case script,
change the pipeline, or overwrite the old network. This is a bounded spatial
domain experiment, not a transport-validity or convergence claim.

```bash
cd /Users/erickang/Documents/matsim
.venv/bin/python scripts/expand_demo_network.py --run \
  --experiment-id cbd_fixed1037_bbox500_20260926_r03
```

That ID belongs to the recorded attempt. A reproduction must choose a **new**
`--experiment-id`, or omit the option to allocate a fresh UTC/UUID name. Existing
names are refused, including failed attempts. The generator owns no old output
directories and has no resume/overwrite switch.

The input contract is deliberately narrow: fixed source XML SHA-256, 1,037
persons, exactly one selected plan each, 4,660 finite-coordinate activity
occurrences, EPSG:7899 from the source manifest, a 500 m network-only buffer,
and a maximum proposed extraction area of 25 km². A single function,
`expand_network(experiment_id=..., root=...)`, returns the completed experiment
directory. The public CLI requires `--run`; import and help do not generate data.

## Geometry and preservation

R derives the unbuffered rectangle from all selected-plan activity coordinates.
It writes `activity_bbox.gpkg` in EPSG:7899. The existing vendor generator then
buffers it once by 500 m and snaps the extraction geometry to its existing 1 m
grid. R records only aggregate dimensions/area/counts in `domain_summary.json`.
Neither the console handoff nor the ID mapping prints individual activity
coordinates or person identifiers.

Measured by the actual R environment before generation:

| Measure | Value |
| --- | ---: |
| Unbuffered activity rectangle area | 14.2528 km² |
| Buffered, grid-snapped extraction domain area | approximately 22.7000 km² |
| Buffered extraction envelope width | 5.486 km |
| Buffered extraction envelope height | 4.177 km |
| Activity occurrences outside extraction polygon | 0 / 4,660 |

These extraction-polygon calculations are not a claim of source-boundary
accuracy or final road coverage. The final node bbox and car-segment distances
are audited separately after network cleaning.

The container mounts `data/` read-only and the original plans as a read-only
file. Its only writable host mount is this new experiment directory, mapped to
`/app/output`. A copy of the cached Victoria PBF goes into that directory's
`scratch/`; the original PBF is untouched. This is necessary because
`osmextract` creates a temporary GPKG beside its PBF input. The scoped OSM GPKG,
unconfigured SQLite network and temporary files also use isolated scratch paths.
No old scoped GPKG is reused.

## Runtime and lifecycle evidence

Every attempt retains `manifest.json` with UTC start/end timestamps, current
stage, stage events, exact Docker argv, controlled container environment, input
hashes, script/audit hashes, generator-source fingerprint, immutable image ID,
Python environment, Docker resources, log path, return code and failure state.
The generated R driver has its own hash. R writes package and native-library
versions to `r_environment.json`. On completion, artifact hashes, input hash
rechecks, before/after coverage and case-anchor mappings are added.

The container command uses `--pull never`, `--network none`, Rscript `--vanilla`,
and `RENV_CONFIG_AUTOLOADER_ENABLED=false`. It does not build an image, restore
packages or download data. It uses the already cached source-matching image:

`sha256:81312b9c671161a8a8ce8349ab53514396cee30d8389bdd5c4bb1beb24dd1dca`

Source fingerprint:
`2a757241fbb2f799184dace07d09ce12c11d313cd1f5745aac677e3117ebe271`.

Actual runtime: R 4.2.1 on `x86_64-pc-linux-gnu`, sf 1.0.15, lwgeom 0.2.13,
xml2 1.3.6, jsonlite 1.8.8, osmextract 0.5.0, igraph 1.6.0, data.table 1.14.10;
GEOS 3.8.0, GDAL 3.0.4 and PROJ 6.3.1. Resource limits are 32 GiB memory,
4 CPU quota and 2 explicit path-splitting workers. These limits are not a
prediction of consumption or runtime.

Two startup failures are deliberately retained:

- `output/domain_experiments/cbd_fixed1037_bbox500_20260926`: Docker exit 125,
  before R execution, from explicit platform selection against the cached image.
- `output/domain_experiments/cbd_fixed1037_bbox500_20260926_r02`: same exit 125
  after deriving the explicit platform from metadata. All original input hashes
  remained unchanged in both attempts.

Image inspection declares linux/amd64, while Docker Desktop runs on arm64.
This Docker environment rejected explicit platform resolution of the cached OCI
image ID but executed the same pinned image without the override, as the existing
runner does. The final script records declared platform metadata and lets Docker
resolve it locally; it does not switch image identity. A diagnostic R invocation
also demonstrated why startup profiles must be disabled: without that control,
renv tried to bootstrap and failed under the disabled network. No installation
or download succeeded; the generation driver uses both protections above.

The successful generation attempt is
`output/domain_experiments/cbd_fixed1037_bbox500_20260926_r03`.

| Lifecycle | UTC |
| --- | --- |
| Experiment started | 2026-09-26T06:02:52.433663+00:00 |
| Network generation started | 2026-09-26T06:02:53.093841+00:00 |
| Network generation finished, exit 0 | 2026-09-26T06:09:52.070886+00:00 |
| Audit completed / experiment completed | 2026-09-26T06:09:52.705565+00:00 |

Total elapsed time was **420.271902 seconds**. The main split handled 18,857
paths using two workers, followed by 66 endpoint re-splits and network cleaning.
The original CBD run handled 6,069 paths at its corresponding main-split stage.
These counts describe observed work; they are not a general scaling model.

## Completed network and coverage evidence

All original input hashes were rechecked unchanged: plans, original network,
Victoria PBF and source baseline manifest. All recorded output-artifact hashes
were independently rechecked after completion. Both nodes and links in the new
SQLite file declare SRID 7899.

New network hashes:

- XML: `48d745864812fc5b50f36f09f2975a2baf1ef1dc86b25bb5ac08b176bd269532`
- SQLite: `4f45710c8d701e0a43c68b4b3c043f762b731b47410b99d49fb478e6f99fd680`

| Measure | Original network | Expanded, cleaned network |
| --- | ---: | ---: |
| Finite nodes | 684 | 3,129 |
| Directed links | 2,464 | 11,331 |
| Explicit usable car links | 1,083 | 6,427 |
| Audited persons / activities | 1,037 / 4,660 | 1,037 / 4,660 |
| Activity occurrences inside final node bbox | 3,222 | 4,660 |
| Activity occurrences outside final node bbox | 1,438 | 0 |
| Inside-node-bbox fraction | 69.1416% | 100% |
| Mean nearest-car-segment distance | 96.4962 m | 5.7643 m |
| p50 distance, nearest rank | 8.7372 m | 2.7505 m |
| p95 distance, nearest rank | 442.8855 m | 22.8324 m |
| Maximum distance | 1,497.6878 m | 206.9817 m |
| Activity occurrences more than 100 m away | 1,284 | 10 |
| Activity occurrences more than 500 m away | 153 | 0 |
| Activity occurrences more than 1,000 m away | 28 | 0 |

All 1,452 activity occurrences adjacent to at least one car leg are now inside
the node bbox; their mean nearest-car-segment distance is 6.8766 m and p95 is
24.0978 m. The 10 occurrences more than 100 m away are in this car-endpoint group,
so remaining access distances should be retained in planning interpretation.
All finite coordinates received distances. Missing/invalid/nonfinite coordinates,
unusable car endpoints and missing link modes remain zero.

An independent adjacency traversal of explicit car links reached all **2,444
car-network nodes** both forward and in the reversed graph from one node. This
establishes one strongly connected graph for these car links. It does not test
MATSim activity-link assignment, turn restrictions outside the XML graph,
link-to-link routing behavior or the effects of the proposed closure.

Evidence files in the successful experiment directory:

- `manifest.json`: lifecycle, controlled environment, input/output hashes.
- `console.log` and `expanded_network/makeMatsimNetwork.log`: actual execution.
- `coverage_before.json` and `coverage_after.json`: full aggregate coverage audits.
- `domain_summary.json` and `r_environment.json`: actual R domain/runtime.
- `network_id_mapping.json`: all old-node/link candidates and case anchors.

## Handoff contract for the planning case

Completed new network file:

`output/domain_experiments/cbd_fixed1037_bbox500_20260926_r03/expanded_network/network.xml`

Wait for `manifest.json` status `completed`; presence of a partially written
file is insufficient. `completed` means the generation/artifact audit workflow
completed, not that a model passed a coverage threshold or is transport-valid.

Keep the original demand file:

`output/cbd_demo_20260926T050044Z_a805bd_demand/8.xml/plan.xml`

Its required SHA-256 remains:
`3b886ede8f0d5fac1fb17bf3602d2b09d0ada3dd986f231c5a00d0bbffaf872c`.

The handoff contains `coverage_after.json` and `network_id_mapping.json`.
For each old node, the mapping records nearest new node IDs and distance, and
accepts a candidate only if uniquely nearest and within 1 m. For links it records
unique direct candidates with matched directed endpoints and a mode superset.
Ambiguity, disappearance or splitting remains unresolved. It does not invent a
replacement route or infer attribute equivalence. Old case anchors 8844, 8954,
8695 and 9032 and closure links 890/2071 have a dedicated summary; any existing
direct chord between the alternative endpoints is also reported.

The case owner must verify the corridor's geometry, topology, link attributes
and building conflicts before freezing a new experiment. This task sends those
artifacts directly to the case agent and does not change frozen case inputs or
execute a bootstrap/MATSim run.

Confirmed case-anchor mappings:

| Kind | Old ID | New ID | Evidence |
| --- | --- | --- | --- |
| Closure endpoint node | 8844 | 28333 | Unique nearest node, 0 m |
| Closure endpoint node | 8954 | 29264 | Unique nearest node, 0 m |
| Alternative endpoint node | 8695 | 27931 | Unique nearest node, 0 m |
| Alternative endpoint node | 9032 | 29548 | Unique nearest node, 0 m |
| Forward closure link | 890 | 3734 | Matched directed endpoints and modes |
| Reverse closure link | 2071 | 9256 | Matched directed endpoints and modes |

The two closure links also have identical XML attributes excluding
`id/from/to`. No existing direct link joins the two alternative endpoint nodes.
Across the entire old network, 672/684 nodes and 2,303/2,464 links meet the mapping
rule; unresolved nodes/links must not be silently substituted.

The case agent published the **single top-level compatibility snapshot**
`output/cbd_expanded1037_bootstrap_inputs_network/network.xml`. This domain task
independently verified byte-for-byte equality with the r03 XML and the same
SHA-256 `48d745864812fc5b50f36f09f2975a2baf1ef1dc86b25bb5ac08b176bd269532`.
This avoids the existing runner's basename
constraint: its record can reference a top-level `*_network` directory while
retaining the nested r03 origin and hash. This domain task does not create a
second `cbd_fixed1037_bbox500_20260926_network` copy. The case agent reported its
separate bootstrap started; its simulation status belongs to the case task and
is not a result of this domain experiment. The immutable r03 source is complete.

## Verification and limits

Commands executed for the current implementation:

```bash
.venv/bin/python -m unittest discover -s tests -p test_expand_demo_network.py -q
.venv/bin/python -m unittest discover -s tests -p test_coverage_audit.py -q
```

Results: **12 expansion tests passed**, and **15 coverage-audit tests passed**.
Tests cover original-input preservation, immutable image identity, isolated
mounts, no pull/network, startup-profile prevention, durable failure/interruption
records, refusal to overwrite, changed demand/hash/CRS rejection, missing
outputs, image/source matching, node ambiguity, link direction and keeping
coverage diagnostics separate from generation status.

A focused read-only test-gap audit found that the original environment stub
masked the platform/startup seam. Tests now inspect command controls and exercise
the real metadata adapter with controlled Docker responses; the actual R run
provides integration evidence. The skill's scoped scanner could not see tests
outside `scripts/`; a repository-root scan and direct import check confirmed
`tests/test_expand_demo_network.py` covers this script. This heuristic was not
treated as a numerical coverage claim. Remaining unautomated failure surfaces
include an actual Docker daemon loss or disk-full event during generation.

No MATSim result, traffic benefit, polygon accuracy, convergence, or valid policy
intervention is established by this domain experiment.
