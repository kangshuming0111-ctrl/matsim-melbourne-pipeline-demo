# MATSim Melbourne: transport analytics and an evaluated AI assistant

Personal integration project · Python, DuckDB/SQL, FastAPI, Docker, Qwen3/Ollama · Release 2026.10-p2

Compare a road closure and proposed detour using traceable simulation results, then inspect the data through a bounded local AI assistant. Implementation and documentation were AI-assisted. MATSim supplies the simulation engine; Qwen is a pretrained model. See [contribution boundaries](docs/CONTRIBUTIONS.md).

[**Open the public project showcase**](https://matsim-melbourne-p2.blueheron8.chatgpt.site) · [Source on GitHub](https://github.com/kangshuming0111-ctrl/matsim-melbourne-pipeline-demo)

The public page needs no login or installation. It includes interactive aggregate comparisons, the detour report and recorded AI evaluation examples. Live AI inference runs locally.

## Review in five minutes

- Open [the interactive aggregate showcase](portfolio/index.html): experiment, data quality, SQL and recorded AI answers. No installation needed.
- Read [the detour investigation](portfolio/reports/MATSim-detour-analysis.pdf) and [AI evaluation report](portfolio/reports/MATSim-ai-evaluation.html).
- Inspect [SQL Q07](sql/queries/07_detour_usage.sql), [assistant implementation](wrapper/assistant.py), [33 assistant tests](tests/test_assistant.py) and [frozen evaluation](evals/assistant/holdout-freeze.json).

## What is implemented

- P0: shared valid/missing/invalid measurement handling; valid zero values remain included. A regression example of 90 seconds plus missing gives 90, not 45. The nine native runs have no missing measurements; this defect was verified with regression fixtures.
- P1: DuckDB schema, transactional and idempotent imports, source hashes, and ten SQL analyses with CTEs, joins and window functions. The saved case contains 32,607 synthetic trip rows across nine runs, with repeated agents across scenarios and seeds.
- P2: a local Qwen3 model selects typed, read-only tools. SQL/Python calculates numeric facts; deterministic constraints bind explicit parameters. Reviewed explanation blocks distinguish observations, hypotheses and limitations. Responses retain units, run IDs, source hashes and raw model plans.

## Findings and evaluation

The experiment uses 1,037 synthetic agents, three seeds, three scenarios and ten iterations per run. Closure increased mean car-trip time by 7.530 seconds; adding the detour increased it by a further 0.098 seconds, averaged across seeds. Six of 934 car trips used the new links in each detour run. The selected endpoint shortest free-flow cost was unchanged. These observations support limited uptake and route attractiveness; they do not isolate a causal mechanism. The proposed next experiment is a split-only control.

Final internal development evaluation: 30/30. Frozen reserved evaluation: 20/20, including 14 numerical questions. The deterministic baseline also passed 20/20. Eight AI questions required deterministic parameter corrections, and five refusals happened before any model call. These are guarded-system scores, not raw-model accuracy or independent external validation. Earlier failed development runs are retained. Model-invoked holdout latency: p50 7.184 seconds, p95 10.195 seconds, on the evaluated local CPU setup.

The P2 source package was verified with 368 Python tests: 367 passed and one optional osmium test skipped. Public packaging changes documentation and presentation only; frozen implementation hashes are checked again. See [release validation](validation/2026-10-19-p2.md) and [the GitHub release record](docs/PUBLIC_RELEASE.md).

## Run the source locally

Use Python 3.10+; Windows users can run in Ubuntu/WSL2. From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-analytics.txt
python -m unittest discover -s tests -v
python -m scripts.assistant '4711 baseline car mean time' --engine deterministic
python -m wrapper.server --no-browser
```

The local UI runs at http://127.0.0.1:8000/assistant. Without a native analytics database, the assistant explicitly uses the reviewed aggregate snapshot. For model inference, install Ollama and the evaluated `qwen3:4b-instruct-2507-q4_K_M` model separately; see [AI setup and scope](docs/AI_ASSISTANT.md). Model weights and runtime binaries are excluded. The website shows saved answers and never starts the model or a simulation.

Docker and external inputs are needed for new simulations; see [run guide](docs/RUNNING.md), [data preparation](docs/DATA_PREPARATION.md) and [SQL guide](docs/ANALYTICS.md). The repository does not bundle native individual trip records or the analytical database. A fresh source download can inspect the reviewed aggregate results; it cannot regenerate external data without those additional prerequisites.

## Boundaries and attribution

This is a local prototype plus a static public showcase. It does not claim observed-traffic calibration, policy benefit, statistical significance, production AI hosting, load testing, model training, general RAG, unrestricted text-to-SQL or independent user evaluation. The original holdout has already been opened; future model/prompt changes require a new unseen evaluation set.

Upstream notices and vendor licensing files are retained. The repository update preserves the existing Git history. Downloadable source ZIPs are snapshots with file-level SHA-256 manifests. Historical documentation and validation records describe their respective earlier releases. The recorded video is the earlier P0 tour; SQL and AI are shown in the current page tabs.

[Chinese historical project guide](README.zh.md) · [development and measurement contract](docs/DEVELOPMENT.md) · [SQL interview notes](docs/INTERVIEW_P1.md) · [AI interview notes](docs/AI_INTERVIEW.md)
