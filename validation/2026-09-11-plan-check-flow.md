# Plan check / compare UI regression — 11 September 2026

Working tree based on `55a3dd8`, including pre-existing uncommitted work. No commit, publication or MATSim rerun in this fix.

## Defects and changes

- `planning-ui.js`: `planCheck` previously required a nonempty committed operation list, although a visible map draft was stored separately. The draft rendering path refreshed the run button but never made checking the draft possible. The first check now includes the visible draft exactly once, or replaces its edited operation; subsequent checks do not duplicate it.
- `index.html` and `planning-ui.js`: action availability and next-step text now share `cityPlanFlow` / `cityPlanRefreshActions`. The compare entry checks first when necessary, but only a later explicit run click can submit. Missing points, loading, result view, check in progress, running job, invalid name and unacknowledged conflicts have visible explanations. Existing backend token and risk gates are unchanged.
- Conflict count and clickable building list have dedicated DOM containers, separate from move-point instructions. New drafts mark old reports incomplete; a failed check clears approval and says the conflict count is unknown, not zero. In-flight and obsolete baseline responses cannot approve a different plan.
- Updated the on-page guidance and English/Chinese README and city-plan documentation. Terrain, building meshes and depth settings were not changed.

## Executed verification

- `.venv/bin/python -m unittest discover -s tests -q`: **87 passed**, 0 failures/errors (0.121s). External simulation calls are mocked in this unit suite.
- JavaScript parse checks for inline application/fixture scripts, `planning-ui.js` and `road-editor.js`: passed.
- `tests/browser/plan_workflow.html`: **26 checks passed** in the in-app browser, using the actual frontend adapter and a mock API. Covers empty/single-point draft, automatic inclusion, count/list/navigation callback, acknowledgement and name gates, duplicate checks, edit replacement, failed and accepted submission paths, zero/unknown/stale reports, async locking and obsolete baseline response. Mock submission is not an actual completed simulation.
- Actual application, existing baseline `cbd_demo_20260910T001314Z_0d6a3f_sim`, 436px-wide window: placed two mouse clicks to draw a **675m route** without clicking Add; clicked the compare entry. The actual check API returned **one operation and 33 building-footprint conflicts**. Clicked Building 1 and observed camera navigation; checked the risk box and observed the real run button become enabled. No run request was sent. The test checkbox was then unchecked, leaving review to the user.

The 675m plan was a UI test route, not the user's intended design; the open page names it “界面验收示例 · 675米（未运行）”. No saved draft or existing simulation output was overwritten. Conflict counts are conservative footprint intersections, not engineered 3D clearance validation.
