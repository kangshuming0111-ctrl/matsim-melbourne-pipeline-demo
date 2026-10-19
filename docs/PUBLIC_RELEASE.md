# P2 publication record · 19 October 2026

This change brings the existing public repository to the reviewed P2 source state. It is based on `40d47dfb4b99ef7fc08696495222d217ecc2e2c3`, preserving that history and all pre-existing third-party notices.

- Public showcase: https://matsim-melbourne-p2.blueheron8.chatgpt.site
- Repository: https://github.com/kangshuming0111-ctrl/matsim-melbourne-pipeline-demo
- Source provenance: original P2 ZIP SHA-256 `3e52d861536407caf5f8039d154db30b48cf6b6b1cd790b08f0695421f1921ba`.
- All 16 frozen implementation/query/evidence hashes match `evals/assistant/holdout-freeze.json`.
- The delivered P2 package passed 367 Python tests with one optional osmium skip; the public snapshot also passed all 33 assistant tests. The assembled repository is checked before upload; current results are recorded in `validation/2026-10-19-github-release.json`.
- The public showcase passed 21 section/viewport combinations, 25 review links, four saved AI examples and four measurement states in a fresh, unauthenticated browser context. Source ZIP checksum also matched.

The static deployment does not expose the local simulation API or model server. Raw native trip records, the DuckDB database, model/runtime binaries and credentials are excluded. Retained vendored test fixtures and licensing files remain included.

The original P2 evaluation is unchanged: the guarded system passed 20/20 reserved questions, eight needed explicit-parameter corrections, and the deterministic baseline also passed 20/20. There is no accuracy advantage or independent external benchmark claim. Future model or prompt changes need a new unseen suite.

Earlier validation records retain their original dates and deployment status. They are historical records, not assertions about the current publication. GitHub CI status is only claimed after its actual run completes.
