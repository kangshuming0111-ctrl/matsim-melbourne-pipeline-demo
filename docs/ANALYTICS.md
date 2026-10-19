# Local SQL analysis (P1)

This optional DuckDB layer analyses completed simulation evidence. It does not start MATSim, change input plans, or rewrite native outputs. Version: 2026.10-p1; DuckDB 1.5.6.

## Run it

From the project root in WSL/Linux:

```bash
.venv/bin/python -m pip install -r requirements-analytics.txt
.venv/bin/python -m scripts.analytics import
.venv/bin/python -m scripts.analytics query --name 03_paired_distribution
.venv/bin/python -m scripts.analytics export --destination output/analytics/my-review
.venv/bin/python -m scripts.verify_analytics
.venv/bin/python -m unittest tests.test_analytics -v
```

The database defaults to `output/analytics/matsim.duckdb`. `--database /path/new.duckdb` selects another revision. Export requires a NEW destination so an existing review is never overwritten. Read-only queries use checked-in names, not arbitrary paths.

The importer targets `cbd_expanded1037_detour_10it_review_r02` by default. `--case` accepts another completed case only if it has the same baseline/closure/alternative manifest and geometry contract. It is not a general importer for unrelated MATSim projects. The source release excludes raw population, native simulation outputs and the person-level database; importing real runs requires those files in the local project. The offline review includes aggregate results, hashes and this report; unit fixtures run without raw data. Do not claim the source ZIP alone reproduces the nine simulations.

## Model and table grain

| Table / view | Grain and key | Purpose |
|---|---|---|
| cases | One case / case_id | Frozen case-spec and population SHA-256 |
| scenarios | Case + scenario_key | Baseline, closure, alternative; ordinal |
| runs | One saved run / run_id; unique case + seed + scenario | Source fingerprint, population size, iteration count, expected trip rows, normalized config hash |
| source_artifacts | Run + artifact kind | 99 source references across nine runs; relative path, SHA-256, bytes |
| trips | Run + source row number | Every CSV row retained, including invalid/duplicate keys |
| link_metrics | Run + directed link ID | Network geometry and complete car-link traversal aggregates |
| route_diagnostics | Run + direction + route kind | Same-endpoint minimum free-flow costs and added-road-only route |
| usable_trip_keys | Run + person + trip_number | Excludes malformed keys and ALL occurrences of duplicate keys |
| paired_trips | Case + seed + comparison + before trip key | Before-anchored LEFT JOIN to proposal; matched, unmatched or invalid |

FKs prevent orphans. `analytics_meta` stores schema version 1. Run IDs are provenance, never treatment assignments. Trip keys match a person and trip number, not necessarily identical OD, mode or route.

## Measurement dictionary

| Field / metric | Unit, denominator, missing policy |
|---|---|
| departure_s | Seconds since simulation-day start; hours beyond 24 supported. Pairing requires before departure in [0,108000), valid before mode. |
| travel_time_s / distance_m | Seconds / metres. Only finite nonnegative measurements. Blank = missing; malformed, negative or nonfinite = invalid; both stored as NULL. Real zero remains valid. |
| time_status / distance_status / departure_status | `valid`, `missing`, `invalid`; quality counts describe whole source files. Extra CSV fields invalidate time/distance. Missing or duplicated required headers fail ingestion. |
| mode / mode_fallback | Use nonempty `main_mode`, otherwise an unambiguous single `modes` value. No inference from a multi-mode chain. |
| key_valid / duplicate_key | Valid nonblank person + positive integer trip number; all copies of duplicate keys excluded from pairing. |
| scenario mean | AVG of valid measurements, with COUNT(measurement) as its own denominator. Raw means include rows with bad/duplicate keys, which are separately audited. This differs intentionally from the paired cohort. |
| delta_s | After minus before trip duration. Positive = slower; NULL or absent proposal cannot contribute to paired means. Mode switches remain in the cohort and are counted. |
| pairing_status | `unmatched` includes absent proposal keys and proposal keys removed as duplicates; audit Q01 for the distinction. `invalid` means matched key but unusable time/departure/mode. Baseline duplicate/malformed keys are outside eligibility. |
| faster / unchanged / slower | <= -1 s / absolute delta < 1 s / >= +1 s; exhaustive, mutually exclusive. |
| p05 / median / p95 | Quantiles of individual paired DELTAS, not differences between scenario quantiles. DuckDB quantile_cont uses linear interpolation, matching Python impact analysis. |
| observed_detour / observed_closed_link | At least one COMPLETE attributable traversal of a selected directed link anywhere during that car trip. Not a count of users/traversals. False means not observed, not proof of no use. |
| entered_count / complete_count | Car-link events whose entry time is in [0,108000); exit may occur later. Departure/arrival partial links, parked intervals and unfinished traversals are excluded from complete statistics. Counts can differ. |
| mean_travel_time_s / mean_delay_s | Complete-traversal sums divided by complete_count; zero complete observations => NULL. Delay reference is length/freespeed, signed and not clipped; not a pure observed congestion measure. |
| role | `added_road` = ifplan_road_ IDs; `split_existing` = ifplan_split_ IDs; others `existing`. Splitting is not equivalent to adding a new corridor. |
| route freeflow_s | Dijkstra over car-permitted links, cost length/freespeed. `added_road_only` restricts to new-road links. No path => NULL. Same actual endpoint nodes 27931 and 29548 in every scenario and both directions. Ignores queues, route choice, turn costs and observed travel time. |
| seed average | Arithmetic mean of three within-seed effects. Same synthetic population is reused, so never pool seed repetitions as independent people or label the range a confidence interval. |

## Ten review queries

| Query | Question and SQL technique |
|---|---|
| Q01 `01_data_quality` | Are nulls, zeros, malformed and duplicate keys visible? FILTER counts; grouped JOIN. |
| Q02 `02_scenario_means` | What changed by mode and overall? CTE, UNION ALL, baseline self-join, NULLIF denominators. |
| Q03 `03_paired_distribution` | What happened to the same trips? LEFT JOIN in view, filtered aggregates, quantile_cont. |
| Q04 `04_change_bins` | Do gains offset losses? CASE bins, count and sum of paired deltas. |
| Q05 `05_time_windows` | Does the result differ by departure window? CASE windows (07-09 / 16-18 / other), before-time anchor. |
| Q06 `06_exposure_cohorts` | What happened to prior closed-link users and observed new-road users? Keyed JOIN and UNION ALL; no multiplicative join. |
| Q07 `07_detour_usage` | Was the new road actually used? Separate trip and link CTEs prevent fan-out; weighted link means. |
| Q08 `08_link_changes` | Which unchanged road segments changed most? Like-for-like join and ROW_NUMBER partitioned by case, seed and comparison. Top five by absolute change. |
| Q09 `09_route_diagnostics` | Does the new corridor offer an endpoint time advantage? Conditional aggregation over comparable endpoints. |
| Q10 `10_integrity` | Are counts, relationships and controls consistent? Eight audit checks; all issue counts must be zero. |

## Import and provenance contract

A case batch is transactional. Native paths, actual seeds, fixed plan hash and normalized output configs are checked before import; only network/output path differences are allowed within a seed. Case results are verified against manifest hashes. Source content and importer/parser/schema hashes form each run fingerprint. Identical imports skip; changed sources/code refuse in-place replacement and require a new database revision. Mid-batch failure rolls back the case batch. Sources are never modified; file stamps are checked again after extraction.

`sql-evidence.json` contains query hashes, 99 source hashes, event diagnostics and aggregate outputs, with no person keys. Core export provenance is per-run; the raw database contains synthetic individual rows and stays local. Older P0 `case.json` is retained with its original release/date. P1 normalized-config and event checks are additional, not retroactively claimed by P0.

SQL aggregates and joins are checked against 36 existing Python mode summaries and nine strict paired comparisons. The underlying shared event reader is reused: this is not an independent validation of MATSim/event semantics. All-mode summaries include teleported walk/PT; car-network diagnostics do not measure PT routes. Imported event-quality counters remain visible rather than being interpreted as all zero errors.

## Limits and next experiments

The six observed users are selected after treatment; their outcome is descriptive, not a causal road-user effect. The road addition also changes junctions/splits: isolating it needs a split-only control. Three seeds and ten iterations do not prove convergence. These data have no observed-traffic calibration, confidence interval, network safety assessment, emissions estimate or policy recommendation.

The report builder needs optional `reportlab`: `python -m scripts.build_interview_report`. Aggregate evidence suffices for report generation. The PDF is two pages; its numerical claims cite Q01-Q10 and the recorded case specification.

SQL references: [DuckDB Python](https://duckdb.org/docs/current/clients/python/overview), [transactions](https://duckdb.org/docs/current/sql/statements/transactions), [aggregate functions](https://duckdb.org/docs/current/sql/functions/aggregates).
