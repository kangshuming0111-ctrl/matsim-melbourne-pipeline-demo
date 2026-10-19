# Studio panel clipping repair — 2026-09-12

## Scope and evidence

- User screenshot: right tools clipped beyond Safari window; live Safari observation also showed the studio topbar outside the visible area. Normal Chromium layout at 1280 px, 600 px and 320 px did not reproduce that original whole-stage displacement.
- The prior fixed studio followed the layout viewport only (`inset: 0`); it had no visual-viewport resize/pan handling. Pinch zoom can shrink and offset the visible viewport without changing layout media queries. This is a supported explanation, not a captured measurement of the user's original pinch scale. Reference: [MDN VisualViewport](https://developer.mozilla.org/en-US/docs/Web/API/VisualViewport).
- Added `wrapper/static/studio-viewport.js`: binds the studio's CSS-pixel position and dimensions to the visual viewport; compact mode follows visible width. Window-size fallback, frame coalescing, no renderer resizing for offset-only pans, listener cleanup on exit.
- `wrapper/static/index.html`: compact drawer positioned inside the studio, intrinsic width containment, wrapped point rows/long names, border-box sizing. Existing layout-viewport-only studio media rules were replaced, not kept as another state source.
- No edits to route data, building/terrain meshes, conflict rules, run API, simulation parameters or prior results. No simulation or Docker build launched by this task.

## Executed verification

1. `tests/browser/studio_layout.html`: **86 checks passed in Chromium (Codex in-app browser) and native Safari**, using real application markup/CSS and the actual viewport controller. No app API calls or localStorage writes. Eight layout widths (320, 375, 600, 760, 761, 1024, 1280, 1920), plus simulated visible windows of 600×420 at offset 170,140 and 320×300 at offset 300,200 inside a 1280 px layout.
   Checks cover panel bounds, horizontal overflow, control widths, vertical access to the comparison button, drawer visibility, offset-only pan and disposal. Simulated visual viewports are injected inputs, **not automated native pinch gestures**.
2. `node tests/test_studio_viewport.js`: passed. Resize coalescing, compact/desktop transitions, offset-only pan, transient zero size, pending-frame cancellation, listener removal, and no-VisualViewport fallback.
3. Existing `tests/browser/plan_workflow.html`: **36 checks passed**, mocked API, no simulation.
4. Actual app: separate Safari tab opened the CBD studio; right panel visibly complete, including after two page-zoom-in commands. Original draft tab was not refreshed. In-app actual viewport measured 320×640: panel [10,310], scrollWidth = clientWidth = 298; hide/show worked; exit removed viewport styles. The requested 600 px browser override did not apply consistently, so the live-app measurement is reported as 320 px; 600 px is covered by the deterministic layout fixture.
5. `node --check wrapper/static/studio-viewport.js` and `git diff --check`: passed.

## Limits

- Playwright CLI is not installed: its CLI workflow was skipped, not represented as passed. Existing CUA browser/native Safari tools were used for supplemental validation without installing packages.
- No real trackpad pinch automation, full simulation, full Python suite, performance benchmark or exhaustive graphics validation was performed. This change is UI containment, not a repair or revalidation of 3D geometry.
