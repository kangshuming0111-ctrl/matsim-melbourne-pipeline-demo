# P2: evidence-bound local AI assistant

Open http://127.0.0.1:8000/assistant after starting MATSim. The home page links to it. The interface supports Chinese/English questions, numeric facts, source/run IDs, hashes, execution scope, model timings and downloadable response JSON. A separate deterministic baseline is selectable.

## Run locally

```bash
.venv/bin/python -m scripts.assistant --status
.venv/bin/python -m wrapper.server --no-browser
.venv/bin/python -m scripts.assistant '4711 alternative minus closure car mean time in seconds'
.venv/bin/python -m scripts.assistant '为什么新增绕行路没有改善出行时间？'
.venv/bin/python -m scripts.assistant '4711 baseline car mean time' --engine deterministic
```

This workstation already has the evaluated local runtime/model. Runtime and weights live in `~/.local/share/matsim-ai/`, outside source/shareable packages. No administrator startup service was installed. Once installed, the first AI question can start this managed local service. Deterministic mode requires no model.

For a fresh machine, install Ollama using its official Linux instructions below, obtain `qwen3:4b-instruct-2507-q4_K_M` using its CLI, then start `ollama serve`. Set `MATSIM_AI_URL` to a local HTTP loopback endpoint if needed. The source archive excludes runtime binaries and weights. The app and model run together in WSL on this workstation; runtime and weights required about 4 GB of downloads.

Evaluated runtime: Ollama 0.40.6. Model digest: `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`. Runtime archive SHA-256: `c164ab8b1b28e2a247c29719b8e404c423c5b83ae64c3ab4e59d50c7ff7fc5e0`. Different revisions require fresh evaluation; recorded scores do not transfer automatically. `MATSIM_AI_MODEL` selects an installed local model. No API key or cloud provider is configured.

A fresh checkout needs normal product dependencies; `requirements-analytics.txt` enables read-only DuckDB. Without the native database, the reviewed aggregate snapshot is used with an explicit `aggregate_snapshot` label. It does not pretend to query unimported runs.

## Supported scope

- List the nine reviewed imported runs. Other product runs are outside this assistant until imported and reviewed.
- Single-scenario time/distance means, trip counts, population and iterations; car/bike/walk/pt/all modes.
- After-minus-before differences in scenario means, one seed or an equal-weight mean across three seeds.
- Per-seed car paired mean/median/p95 and faster/slower/unchanged counts for the three forward comparisons. No pooled seed quantiles, sign-flipped reverse p95 or unavailable PT paired exports.
- Missing/invalid counts; explicit hypothetical JSON-array duration examples, separated from simulation records.
- Detour explanation: observations, supported hypothesis, limitations and next experiment.

Units: seconds/minutes, metres/kilometres, counts. The reviewed explanation also includes observed usage percentage. This is not an arbitrary-ratio calculator. Emissions, demographics, observed traffic, forecasts, significance and policy benefits are unavailable.

## Design

1. Scope/identity checks reject unknown runs/seeds, user-supplied paths/URLs, write/simulation actions and unsupported claims before a model call.
2. Qwen returns a schema-validated Plan selecting an allowlisted read-only tool. It cannot submit SQL, commands, paths or arbitrary tool names.
3. Deterministic constraints bind explicit seeds, modes, units, scenarios and subtraction direction. `raw_model_plan` and `explicit_parameter_constraints` preserve output and corrections. This is a guarded hybrid, not raw model accuracy.
4. Existing P1 SQL executes in a read-only connection, or the reviewed export is used. Values, denominators, units and provenance come from code/data, never model arithmetic.
5. After calculation, the model orders/selects reviewed claim blocks. The server resolves fact placeholders and restores mandatory evidence/limits. It does not accept unrestricted model-authored numerical or causal prose. This deliberately bounds explanation scope.
6. Invalid/unavailable model output triggers an explicitly labelled deterministic fallback. Unknown data remains unavailable. One assistant request runs per API process; extra requests get HTTP 429.

This is not unrestricted natural-language-to-SQL, general RAG, fine-tuning or autonomous planning. Existing MATSim/event processing remains upstream. See CONTRIBUTIONS.md.

## Provenance and freshness

The store validates query hashes against the P1 export, checks SQL integrity and requires the complete nine-run case. Facts point to exact run IDs, query text/path/hash and artifact hashes. Population/iteration facts cite run metadata and person/score files. P1 SQL was reconciled with native Python analysis.

Cache invalidation uses database/query/export timestamps and sizes. This is imported evidence, not a live tail of new native outputs. Changes require a new analytics revision and reviewed export. The fixed explanation is not automatically valid for a new population or road design.

## Evaluation

The suite has 30 development and 20 holdout questions locked before implementation. Numerical gold answers come from independent native CSV arithmetic and predeclared metadata/quality cases. Failed development answers are preserved. Code/prompt/model fingerprints are frozen before first holdout use; the evaluator refuses to reuse it as unseen data.

```bash
.venv/bin/python -m scripts.evaluate_assistant --split development --engine deterministic --output output/assistant_evals/new-baseline
.venv/bin/python -m scripts.evaluate_assistant --split development --engine ai --output output/assistant_evals/new-ai
.venv/bin/python -m unittest tests.test_assistant -v
```

After the delivered holdout is opened, future prompt/constraint changes need a NEW independent suite for unseen evaluation. The report distinguishes guarded accuracy, baseline, failures, fallbacks, parameter corrections, citations, refusals and latency. Same-author internal tests are not an external benchmark or production guarantee.

Local inference has no per-question API fee. Electricity, depreciation, download time and storage are excluded from dollar costs. Timings describe this workstation and warmed service, not an SLA. No unrelated cloud pricing is used to invent costs.

## References

[Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs), [official Linux installation](https://docs.ollama.com/linux), [evaluated Qwen tag](https://ollama.com/library/qwen3:4b-instruct-2507-q4_K_M). Valid JSON alone does not establish semantic correctness.
