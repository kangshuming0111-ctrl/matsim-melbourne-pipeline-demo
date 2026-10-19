# Redundancy refactor — 12 September 2026

Scope: road-editor entrypoints and plan check/run decision only. Existing uncommitted work was preserved; this is not a full repository cleanup. No simulation, Docker build, dependency installation, commit or publication.

## Contract and phased plan

The architecture-first, refactor-plan, codebase-design and poka-yoke skills guided this change. Investigation preceded editing; the contract and sequence were stated before implementation.

1. Keep `CityPlanState` as owner of committed operations/history; keep existing draft ownership and `RoadEditor` pointer lifecycle. Do not change coordinate conventions, relative heights, model geometry or persisted draft schema.
2. Use one `cityPlanFlow()` decision for both button presentation and submission. The action is `blocked`, `check` or `run`; only run carries the checked request. Keep checking distinct from execution, and retain server token/conflict gates.
3. Delete obsolete implementations instead of keeping parallel paths. Preserve the supported 2D fallback and public API.
4. Migrate existing fixture assertions to the shared decision, add checks for request availability, run deterministic checks and supplement with the real local UI.

## Actual removals

- `index.html`: removed unreferenced `startNewRoadIfLine`, its `newRoadDraftReady` / `newRoadParametersValid` helpers, and unreferenced `addNewRoadPoint`. Removed the pass-through `startIfLineFromStudio`; the button calls `cityPlanRun` directly.
- `planning-ui.js`: removed the redundant `cityPlanReady` predicate and unused `cityPlanMove`. Moving a point on the next click still uses the active `RoadEditor` handler; its state was not removed.
- The boot-safe refresh delegate remains because inline initialization precedes the deferred adapter. Its duplicate fallback rules were removed.
- Seven functions removed. Relative to the start-of-turn file copies, production source decreased **107 lines**: `index.html` 3708 → 3612, `planning-ui.js` 326 → 315. Counts exclude tests and documentation; this is not a performance benchmark.

## Focused misuse review

| Interface | Available mistake / existing device | New device and limit |
|---|---|---|
| 3D new-road submission | An unused global still exposed a legacy direct-run implementation; lack of callers was detected by source search (Detection, rung 3). | The old UI entrypoint is absent (Control, rung 1 at this UI seam). Public legacy API remains intentionally available; this is not API access-control hardening. |
| Button vs submit readiness | Two predicates checked similar state with different name/loading/context rules; browser tests detected disagreement (Detection, rung 3, on top of existing runtime/backend guards). | One action decision governs both callers; only a run decision supplies a checked request (runtime Control, rung 1 in this adapter). Server revalidation remains necessary. |
| Point editing | Old add/move functions could be reused beside the current pointer adapter (Detection, rung 3 by call-site search). | Old unused functions removed; the active pointer implementation remains (Control, rung 1 for that obsolete entrypoint). Shared JavaScript draft state still exists, so arbitrary future mutations are not type-proof. |

## Verification

- Before and after: `.venv/bin/python -m unittest discover -s tests -q`: **87 passed**, no failures/errors. The runner messages come from mocked unit tests, not a real generation run.
- `tests/plan_state.cjs` and `tests/road_design.cjs`: passed with the installed bundled Node runtime.
- Inline application/fixture JavaScript and `planning-ui.js` syntax: passed.
- Existing `plan_workflow.html`: **36 checks passed** in the in-app browser (original 26 retained, 10 added). Uses real frontend adapter and mock API; submission success/failure assertions do not establish a new MATSim result.
- Existing `road_editor.html`: **27 checks passed**, including pointer ownership, preview cleanup, bridge transitions, undo/cancellation and unchanged terrain vertex buffer. Synthetic pointer tests are supplemented by the real map clicks below.
- Actual existing CBD baseline: two map clicks produced a **794m** draft; compare first checked one operation and returned **42 building-footprint conflicts**. Explicit acknowledgement enabled the real run button; it was then unchecked. No run was submitted, no saved draft changed, and the inspected app console reported no errors.
- Source search found no remaining callers of the seven removed functions. The 2D `startIfLine` caller and legacy endpoint were retained.
- The requested Playwright skill's prerequisite check found no installed `playwright-cli`. **CLI verification was not executed**, no installation attempted. The in-app browser checks above are separate supplemental verification, not a claim that the CLI workflow ran.

## Recovery and limits

Pre-edit copies of the four initially affected files are at `/private/tmp/matsim-refactor-20260912.AQ6Hp7`. Recovery must use a reviewed reverse patch against those copies, preserving any subsequent edits; do not use a whole-worktree Git reset. Temporary copies may eventually be purged by the OS.

Terrain/building/road meshes, backend compilation, Docker/R adapters and output data were untouched. No speedup, calibrated traffic improvement, universal rendering guarantee, or full-repository redundancy audit is claimed.
