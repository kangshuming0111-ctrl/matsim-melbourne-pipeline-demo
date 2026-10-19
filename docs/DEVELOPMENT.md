# Development and verification

Install product dependencies in a project-local Python virtual environment.
`requirements-data.txt` adds optional OSM extraction tooling; viewing saved
results and the ordinary product suite do not require osmium.

```bash
python -m unittest discover -s tests -v
python -m uvicorn wrapper.api:app --host 127.0.0.1 --port 8000
```

Finish active jobs before restarting an existing service to load code changes.
The launcher reuses a healthy service; it does not hot-reload old Python code.

## Measurement contract (summary schema v2)

- `avg_time_seconds` and `avg_distance_m` are numbers or JSON `null`.
- Time accepts nonnegative seconds or H+:MM:SS with fractional seconds. Hours
  may exceed 24; minutes and seconds must be below 60.
- Missing/blank values and malformed/negative/nonfinite values are excluded,
  counted separately. True zero is a valid measurement.
- Each mode reports `time_quality` and `distance_quality` with `valid`, `missing`
  and `invalid` counts. Their sum equals the number of rows in that mode.
- Overall means use the valid count for each metric, not all trip counts.
- Prefer `main_mode`; if empty, accept one recognized `modes` value. Supported
  categories match the impact workbench: car, bike, walk and pt. Ambiguous or
  unsupported categories are counted as unknown rather than guessed.
- A comparison involving an unavailable mean is unavailable; a zero baseline
  does not define a percentage change. Display it explicitly rather than as zero.
- Historical records are preserved. Replay recomputes current summaries from
  native trips. If its baseline cannot be read, old statistics are not substituted.
- General summaries are unpaired descriptive means; the strict workbench also
  checks identity, departure time, duplicates, input/config compatibility and
  matched cohorts. Sharing parsers does not make those estimators identical.

## Re-export the featured evidence

With the nine recorded runs present locally:

```bash
python -m scripts.export_portfolio_case --destination validation/my-new-export
```

Use a new directory. The exporter does not run MATSim, overwrite historical
evidence or publish person-level rows. Inspect `case.json` for measurement
denominators and artifact hashes. The distributed aggregates can be inspected
without local raw data; full recomputation requires the original artifacts.

## Browser regression checks

`tests/browser/measurement_quality.cjs` runs with Playwright against an explicit
local base URL. It executes the production formatter functions and renders
missing-data fixtures. `scripts/check_portfolio.cjs` checks the static review
page, per-seed table, calculator, mobile overflow and browser errors. Playwright
is a development-only tool; the showcase itself has no runtime dependencies.

Existing GitHub Actions configuration is retained; local test success is not a
claim that this release has run on the remote CI service.
