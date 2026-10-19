# MATSim Melbourne — auditable transport scenario analysis

**Python · SQL / DuckDB · FastAPI · Docker · data quality · reproducible experiments**  
Personal project / local prototype · release `2026.10-p1`

## Problem and approach
Road changes are easy to visualise but difficult to compare reliably. This project
connects Melbourne network and synthetic-demand preparation to MATSim, records
the inputs and execution evidence, and makes scenario results inspectable through
a web interface. A failed or incomplete run cannot masquerade as a completed result.

## Project-level contribution
The integration layer contains Python orchestration, API and durable job history,
region and input checks, source/image fingerprints, experiment records, controlled
road interventions, aggregate/paired analysis, and a Three.js editor and replay.
The underlying MATSim engine and upstream R generators are retained third-party
work. Implementation and maintenance use AI assistance; the integration is not a
claim of independently authoring those upstream tools. See [contribution boundaries](CONTRIBUTIONS.md).

## Featured result
One expanded-CBD experiment holds the same **1,037 synthetic agents** fixed across
three seeds and three scenarios: baseline, road closure, closure plus a 356 m
alternative road. Each of the **nine runs** records 3,623 trips and ten iterations.
The mean car-trip-time change across seeds is **+7.530 seconds** for closure versus
baseline and **+0.098 seconds** for the alternative versus closure. The proposed
alternative did not improve this metric in this experiment.

## SQL investigation
Ten analytical SQL queries reproduce the results and inspect paired deltas, time windows, observed road users and comparable links. Only 6/934 car trips per run used the added-road links. The same-endpoint shortest free-flow cost stayed at 20.88 seconds, while the full new corridor cost 42.74 seconds. These facts support limited reach and attractiveness; they do not isolate a causal mechanism. See [the two-page report](../portfolio/reports/MATSim-detour-analysis.pdf).

## Reliability example
A summary bug treated missing time/distance as zero. A 90-second observation plus
a missing observation produced 45 seconds. The repaired pipeline reports 90
seconds, one valid observation and one missing observation; all-missing metrics
remain unavailable. Shared parsing, null-safe comparisons and UI/report handling
prevent the same error from reappearing further downstream.

## Evidence and boundaries
- [Open the offline showcase](../portfolio/index.html) or watch its two-minute tour.
- [Nine-run aggregate evidence](../portfolio/evidence/case.json) includes input-output
  artifact hashes, denominators, missing/invalid counts and per-seed results.
- [Validation record](../validation/2026-10-18-p1.md) separates automated tests,
  saved-result recomputation, Windows/WSL cold image builds and a short fresh run.
- No observed-traffic calibration, proven policy benefit, production deployment
  or AI model is claimed. Transit is teleported; three seeds do not establish
  statistical significance or convergence.

**Review path:** overview → experiment → data-quality repair → implementation.
The showcase is aggregate-only and needs neither Docker nor large datasets.
