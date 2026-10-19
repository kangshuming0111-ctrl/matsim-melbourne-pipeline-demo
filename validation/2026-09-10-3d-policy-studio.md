# 3D policy-studio validation — 2026-09-10

## Scope

This check covered the first interactive-planning slice of IF Line: opening the
recorded CBD baseline in a full-screen 3D city, selecting a MATSim road link in
the scene, previewing an intervention, submitting it through the web API, and
displaying the independently recorded branch result. It did not test drawing a
new road, land-use feedback, calibration or predictive accuracy.

## Static and automated checks

- Python: `3.11.9` from the existing project-local `.venv`
- Command: `.venv/bin/python -m unittest discover -s tests -v`
- Result: **30 passed, 0 failed, 0 errors, 0 skipped**
- Inline JavaScript in `wrapper/static/index.html` parsed successfully with the
  locally available `esprima` parser.
- `git diff --check` passed.
- The regenerated CBD scene contained **2,464/2,464** roads with stable
  `link_id` fields. The policy API exposed **1,083** car-editable links and each
  link included its permitted transport modes.

## Browser interaction check

The local FastAPI page was opened in a real browser. The full-screen policy
studio rendered the existing terrain, OSM-derived buildings, road layers and
MATSim vehicle replay. Switching to the top traffic view and clicking a road
changed the selected object from link `255` to link `1300` and matched reverse
link `2370`. The editor showed recorded length, speed, lanes, capacity, observed
entry count and allowed modes. Capacity and car-closure previews updated before
any simulation was launched; the closure preview explicitly retained `bike`
and `walk` while removing `car`.

An existing completed closure branch was opened in the same studio. Its run
identity, baseline comparison, changed-link IDs, evidence link and 3D impact
view all referred to the same recorded branch.

## New controlled branch

- Scenario ID: `if_20260909T235103Z_029118`
- Baseline: `cbd_demo_20260908T205520Z_16879d_sim`
- Intervention: links `1300` and `2370`, speed `40 → 35 km/h`
- Status: `completed`
- Recorded duration: **35.741 seconds**
- Output population/trips/iterations: **1,037 synthetic agents**, **3,623
  trips**, **3 iterations**
- Recorded all-mode average trip-time delta: **+0.027 seconds**
- Recorded car average trip-time delta: approximately **+0.1 seconds** in the
  browser summary

The web UI labelled this as a newly completed experimental counterfactual and
linked to its own run manifest and comparison record. These tiny changes are a
software-pipeline result under a fixed synthetic scenario, not evidence of a
real-world transport effect.

Primary evidence:

- `output/ifline/if_20260909T235103Z_029118/scenario.json`
- `output/ifline/if_20260909T235103Z_029118/comparison.json`
- `output/run_records/if_20260909T235103Z_029118/run_manifest.json`

