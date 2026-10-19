# CBD capacity stress test — verified local comparison

This is an aggregate-only technical demonstration, not a policy recommendation.

Baseline: `cbd_demo_20260926T050044Z_a805bd_sim`
Proposal: `if_20260926T050734Z_a9b72b_sim`

| Metric | Baseline | Proposal | Difference |
| --- | ---: | ---: | ---: |
| Synthetic agents | 1037 | 1037 | +0 |
| Recorded trips | 3623 | 3623 | +0 |
| Mean trip time (s) | 1126.976 | 1126.981 | +0.006 |
| Mean trip distance (m) | 2191.010 | 2191.010 | +0.000 |

## Mode-level travel time

| Mode | Baseline mean (s) | Proposal mean (s) | Difference (s) |
| --- | ---: | ---: | ---: |
| bike | 161.526 | 161.526 | +0.000 |
| car | 219.069 | 219.090 | +0.021 |
| pt | 383.920 | 383.920 | +0.000 |
| walk | 2180.800 | 2180.800 | +0.000 |

## Evidence and limits

Input-plan hash, configuration equality, actual network changes and artifact hashes are in `evidence.json`.
The CSV retains numerical precision; displayed tables round for readability.

- Existing local data, Python environment and Docker image caches were reused; no clean-machine reproduction.
- Single seed and three iterations do not establish convergence, significance or real-world impact.
- Synthetic agents, not real users; public transport is teleported, not a timetable/vehicle simulation.
- Counts and times come from recorded simulation output, not measured city traffic.
- Git baseline plus a dirty flag alone does not reconstruct all local source edits.
