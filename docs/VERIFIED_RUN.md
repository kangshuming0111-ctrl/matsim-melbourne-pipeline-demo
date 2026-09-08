# Privacy-reviewed run and test summary

This file summarizes a local validation run without publishing raw source data,
full agent plans, event streams, host names, user names, local absolute paths,
environment variables, credentials or tokens.

## End-to-end demo

- Profile: `cbd_small_v1`
- Local run ID: `cbd_demo_20260908T205520Z_16879d`
- Date: 9 September 2026 (Melbourne time)
- Elapsed time: 885.999 seconds
- Network: 684 nodes and 2,464 links
- Synthetic agents: 1,037
- Trips: 3,623
- MATSim score rows: 3 (iterations 0, 1 and 2)
- Required artifacts: 16/16 present and non-empty
- Runtime outcome: normal MATSim shutdown; no unexpected-termination marker
- Network/demand bounding-box diagnostic: 69.1%

The run used a new output directory and preserved prior results. The published
screenshots show a historical replay of this completed run, not a claim that a
simulation completed at the instant the screenshot was taken.

## Python validation

- Python: 3.11.9 in a newly created project-local `.venv`
- Command: `python3 -m unittest discover -s tests -v`
- Discovered: 22
- Passed: 22
- Failed: 0
- Errors: 0
- Skipped: 0

Additional checks passed for Python byte compilation, launcher shell syntax and
Git whitespace errors. API replay assertions confirmed that the displayed run
ID, agent count, trip count, iteration count and run-record link all referred to
the same result directory. Browser acceptance confirmed that the summary table,
charts and 3D scene rendered without console warnings or errors.

## Upstream test status

The upstream R demand test suite was also executed in its pinned container. Its
unmodified harness first reported an undefined `output_crs` in `testPlace.R` and
a legacy `plan.csv` MD5 mismatch in `testPlan.R`. Supplying EPSG:28355, the CRS
stored in the expected fixture, allowed `testPlace.R` to pass. One byte-level
MD5 snapshot failure and four plotting warnings remained. The failing snapshot
was not removed, regenerated or relaxed.

The single upstream network R test still targets the old hard-coded city setup
and was not executed independently. The current end-to-end demo did exercise the
network generator through the environment-driven wrapper.

## Interpretation limits

This is evidence that the local software pipeline completed and produced the
required files. It is **not** evidence that the transport model is calibrated,
scientifically validated, converged, predictive, or responsible for a measured
improvement in real transport conditions. The 69.1% value is a rectangular
bounds diagnostic, not strict polygon coverage or an accuracy metric.
