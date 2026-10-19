# Contribution and attribution boundaries

This is a personal integration project, not employment or a claim to have
written the MATSim engine. Repository-level components below are directly
inspectable; individual interview claims should describe the owner's actual
decisions, debugging and contributions, including AI-assisted implementation.

| Area | Origin / contribution |
| --- | --- |
| MATSim simulation | Upstream MATSim Java engine, invoked through the vendored baseline project |
| Network and synthetic population | Vendored `matsim-melbourne` R workflows, with local container/compatibility entry points |
| Integration | Python CLI/API, job history, preflight, region alignment, process logs, run manifests, source fingerprints |
| Experiment workflow | Controlled edits, immutable run identities, input checks, comparisons and grouped-case catalogue |
| Interface | Browser editing, result selection, aggregate/paired workbench and Three.js replay |
| October P0 maintenance | AI-assisted shared measurement parser, quality counts, null-safe comparison/replay, regression tests and portfolio packaging |

## Retained upstream notices

- `vendor/network/LICENSE` and `vendor/demand/LICENSE` remain in the source package.
- Consult vendored project metadata, Maven dependencies and their upstream
  documentation for the Java engine and other dependency terms.
- OSM data is credited to OpenStreetMap contributors; ABS/VISTA-derived inputs
  and terrain have their own source conditions. See `DATA_PREPARATION.md`.
- The small screenshot assets depict synthetic simulation replay, not observed
  individual trajectories. Large source data, raw trip/event tables, environment
  files, caches and local logs are not included in the portfolio package.
- No new top-level reuse licence is granted by this maintenance release.

## Version provenance

The Mac-to-Windows migration snapshot did not contain `.git`. This release
does not fabricate older commits. `CHANGELOG.md`, the P0 patch, and the packaged
file SHA-256 manifest identify this delivery. The existing GitHub repository may
lag behind this local release; a badge is not used as evidence of this version's CI.


## P2 local AI extension

AI-assisted implementation adds the local Ollama adapter, typed read-only routing, explicit-parameter constraints, evidence-bound explanation composition, API/browser interface and evaluation tooling. Qwen3 is an upstream pretrained model; this project did not train it. SQL/Python determine all numeric facts. Reviewed explanation blocks bound the model's output; this is not unrestricted causal generation or a general RAG agent.

The 30 development and 20 reserved questions are a same-author internal evaluation, not independent user research. Earlier failed answers, raw model plans, deterministic corrections and no-AI baselines are retained. Review `AI_EVALUATION.md` and `AI_INTERVIEW.md` before making personal interview claims. No external human review or public deployment is claimed.

## P1 analytical extension (historical)

AI-assisted additions: DuckDB schema/import CLI, ten SQL queries, transactional and analytical tests, metric documentation, report generation and portfolio/interview materials. Existing MATSim output and existing event parsing supply the evidence. This release does not create a new simulation engine, new observed dataset, ML model or claim of independent external review. The owner should review and explain the source before using first-person implementation claims in an interview.
