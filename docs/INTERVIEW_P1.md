# P1 interview rehearsal

Use these as editable speaking notes, not claims that the project or upstream engines were written without assistance. Only use first-person claims you can explain and defend. The integration and P0/P1 maintenance were AI-assisted; MATSim and vendored R workflows remain upstream work. See CONTRIBUTIONS.md.

## 90-second English introduction (about 160 words)

My project is a local transport simulation and analysis pipeline for Melbourne. I use MATSim as the simulation engine, and the project connects input validation, scenario runs, analysis and a browser-based review interface.

The main question was whether a proposed detour could reduce the impact of a road closure. I compared three scenarios using the same synthetic population and three random seeds.

I first addressed a data-quality issue: missing travel times were effectively reducing the mean as if they were zero. The corrected logic keeps missing values separate and uses valid measurements as the denominator.

I then added a DuckDB analysis layer with traceable source hashes and paired-trip comparisons. The detour did not improve average car-trip time. Only six of 934 car trips used its new links, and the full corridor offered no free-flow time advantage between its endpoints.

The valuable result is an auditable negative finding, with clear limitations and a concrete next experiment. Implementation was AI-assisted, and the simulation engine is upstream MATSim.

## Five-minute technical walkthrough

### 0:00-0:45 | Question and controls

The decision question was whether adding a detour would recover travel-time losses caused by a closure. I separated baseline, closure, and closure plus detour. Each scenario used the same 1,037 synthetic people, with seeds 4711 to 4713 and ten iterations. I verified the actual input-plan hashes and output configurations, allowing network and output paths to differ. Those controls make the comparison interpretable, but they do not establish convergence or real-world validity.

Open: Experiment tab; Q02 and Q03.

### 0:45-1:35 | Data model and correctness

The analytical model has case and scenario dimensions, run metadata, source artifacts, trip rows, link aggregates and route diagnostics. Each raw trip row has its own source-row key. Person plus trip number is a separate matching key. Duplicate matching keys are retained for quality reporting, but all their occurrences are excluded from pairing. This avoids silently choosing one duplicate or multiplying rows in a join.

Travel time and distance have separate valid counts. A blank value becomes SQL NULL, while a real zero stays zero. I store quality status separately, so NULL does not hide whether the source was missing or invalid.

Open: schema.sql; Q01. Explain AVG(value) versus SUM(value)/COUNT(*).

### 1:35-2:20 | Reproducibility and SQL

The importer checks hashes and configuration, then commits an entire case batch in a transaction. Reimporting identical data skips existing runs. A changed fingerprint is rejected and requires a new database revision. The tests cover rollback after a partial failure, duplicate keys, nulls, zero values and mode changes.

I used CTEs to separate trip counts from link counts, a LEFT JOIN for paired trips, conditional aggregation for cohorts, continuous quantiles for distributions, and ROW_NUMBER to rank comparable link changes. I checked the SQL aggregates against the existing Python summaries and impact analysis. Event parsing is shared, so that cross-check does not independently validate the event reader.

Open: Q07 (preventing join fan-out), Q08 (window function), validation record.

### 2:20-3:20 | Finding and decomposition

The closure added about 7.53 seconds per car trip compared with baseline. The alternative was about 0.10 seconds slower than closure across seeds, so I describe it as no observed improvement, not significant deterioration.

The median paired change was zero and p95 was plus one second. For seed 4711, thirteen trips became faster, sixty-five became slower, and the rest were unchanged within one second. The gains totalled 205 trip-seconds, but the losses totalled 314. The small net effect therefore hides both gains and losses.

Only six car trips had a complete traversal on a new-road link. Between the same endpoints, the existing shortest free-flow route took about 20.88 seconds and the full new corridor about 42.74. The network minimum did not decrease after adding it.

Open: SQL analysis tab, Q04, Q07, Q09.

### 3:20-4:15 | Interpretation and limits

These findings support low route attractiveness and limited reach under this demand sample. They do not prove that the speed limit alone caused the result. The alternative also splits existing links to connect junctions, so topology changes are another possible explanation for some trip differences.

The six observed road users are a group selected after the intervention. Comparing their outcomes is descriptive, not a causal treatment-effect estimate. Similarly, the three seeds reuse the same people. I do not pool them as independent observations or claim confidence intervals. The population is synthetic and the scenario is not calibrated against observed traffic.

Open: report page 2; Chinese explanation if rehearsing concepts.

### 4:15-5:00 | Next decision and contribution

The first next experiment would keep the same junction and link splits but disable the new corridor. That would help separate splitting effects from new connectivity. I would then inspect the actual paths of the six users and the largest outlier, test a predeclared parameter grid, and check stability with more iterations.

The contribution I can demonstrate is the integration and evidence workflow: data-quality handling, reproducible comparisons, SQL analysis and clear communication of a negative result. I would disclose AI assistance and distinguish that work from the upstream MATSim engine and population-generation workflows.

## Ten likely questions

1. **Why SQL if you already have Python?** Python handles XML/events and validation; SQL makes joins, denominators, cohorts and ranking reviewable and queryable. DuckDB is optional and local; it is not a production multi-user warehouse claim.
2. **What exactly was the missing-value bug?** A missing duration reduced a mean through an incorrect denominator. Ninety seconds plus missing must average ninety, while ninety plus real zero must average forty-five. All missing means unavailable. The saved nine-run dataset itself has no missing time/distance values, so the fix does not manufacture a better result.
3. **How did you prevent duplicate rows in comparisons?** Keep raw source rows, identify duplicate person/trip keys, exclude every duplicate occurrence from usable keys, and join by case + seed + scenario + trip key. Separate link and trip aggregation before joining to prevent fan-out.
4. **Why not subtract two averages and stop?** The means can represent different populations. Pairing holds the trip keys fixed and lets me count unmatched cases, mode switches, gains/losses and quantiles of individual differences. Here the cohorts align, so the paired and overall car-mean differences agree.
5. **Did you prove why it failed?** I found evidence consistent with limited route attractiveness and coverage: only six observed users and unchanged same-endpoint minimum free-flow cost. Exact causal attribution requires the split-only control and path-level follow-up.
6. **Could this be Braess's paradox?** These outputs do not establish it. The measured difference is tiny, convergence is unproven, and several topology changes occur together. I would avoid that label until the mechanism is isolated.
7. **Are the results statistically significant?** No significance claim is made. Three seeds repeat the same synthetic population; they are sensitivity runs, not independent traveller samples. The variation is described per seed.
8. **Why not just raise the new-road speed or capacity?** That is a hypothesis to test, not a proven fix. Speed changes route cost and capacity matters under demand; a predeclared grid plus realistic constraints avoids tuning a single result for a favourable story.
9. **What happens when ingestion fails or data changes?** The case batch rolls back; unchanged fingerprints skip; changed data or importer/schema hashes require a new database revision. Original simulation files remain unchanged, and exported source/query hashes link claims to inputs.
10. **What did you personally build, and where was AI used?** Explain the decisions and code you have actually reviewed. The repository integrates upstream MATSim/R tools; orchestration, quality checks, analysis and UI are project integration work developed with AI assistance. Do not claim authorship of the simulator or mastery of unreviewed code. Show one SQL query and explain it line by line.

## Practice acceptance checklist

- Give the 90-second introduction without reading, then explain Q03/Q07/Q08 from code.
- Explain why 17 link traversals are not 17 trips, and why 2,802 repeated records are not independent people.
- Use the report to answer “why no improvement?” in two minutes, including one limit and one next experiment.
- Have a classmate or mentor read the two-page report and ask what they think the conclusion is; record their actual feedback before claiming an external review. No such review has been performed for this release.
