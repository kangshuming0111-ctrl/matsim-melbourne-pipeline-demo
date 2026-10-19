# 2026-09-26 — durable process logs and detached web service

## Scope and diagnosis

Repair of the local service startup and external-process I/O boundary, not a
simulation rerun or a change to traffic-model parameters or the 3D renderer.
The working tree already contained unrelated changes; these were preserved.

The latest failed run, `cbd_demo_20260926T044349Z_a6cb24`, stopped in network
generation with `SIGPIPE (13)`. Before restart, the old service's stdout/stderr
were pipes, and the network Docker subprocess inherited them. This is consistent
with an abandoned launch-session pipe; a missing live reader was not independently
proven. An earlier attempt exited 255 during image build, without enough captured
output to establish its separate cause. We do not claim an OOM or a model error.

## Contract and changes

- `wrapper/process_logging.py:run_logged` requires a log path, opens it before
  starting work, supplies `/dev/null` stdin and file-backed stdout/stderr, and
  raises on a nonzero return code. It does not retry or own job state. Failure
  messages identify the return code/signal and log location without echoing argv.
- Network, demand, baseline builds/runs and SA1 extraction use that boundary.
  Logs append in `output/process_logs/`, outside directories R may recreate or
  MATSim expects not to exist. Build output is retained even before native R/Java
  logs exist. Run manifests (including IF Line branches) reference console logs.
- Optional CLI progress does not turn a closed output pipe into a job failure.
  Child output and nonzero exit status remain authoritative; errors are not
  converted into successful runs.
- `wrapper/server.py` starts uvicorn in a new session, with closed stdin and
  append-only `output/service_logs/web.log`. `/health` is a cheap read-only probe.
  Startup waits for the launched PID, rather than treating any response on the
  port as success. A healthy existing instance is reused; no automatic stop,
  simulation retry, or stale-PID-file kill is performed.
- `start.command` and both READMEs use the new launcher. No dependencies added.

The architecture/refactor skills kept job-state ownership unchanged and put I/O
handling in a single boundary. The mistake-proofing change moves logging from an
optional caller convention to a required argument of the execution interface.

## Checks run

| Check | Result |
| --- | --- |
| Initial focused existing unittest suite | 17 passed |
| Focused process/launcher/adapter/job/API tests after changes | 33 passed |
| `.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v` | 103 passed, no failures or skips |
| `bash -n start.command` | Passed |
| `git diff --check` | Passed |
| Real Python child with deliberately closed parent stdout/stderr pipes | Exit 0; both child streams saved |
| Real detached child checks | New session; EOF stdin; both output descriptors regular files |
| Live `docker version --format '{{.Server.Version}}'` with closed parent pipes | Exit 0; saved to `output/service_logs/docker_io_smoke_20260926.log` |

Raw unittest output: [2026-09-26-process-logging-tests.log](2026-09-26-process-logging-tests.log).
The Docker adapter tests mock Docker execution; they do not build images or run
containers. Process-I/O tests use harmless real Python subprocesses.

## Live service verification

Before restart, `/jobs?limit=100` showed 15 historical jobs, no pending/running
jobs; `docker ps` was empty. The old command and port ownership were verified
before sending SIGTERM to that specific process. New service PID at verification:
67465, parent PID 1, no terminal. `lsof` showed stdin `/dev/null`, stdout/stderr
regular files pointing to `output/service_logs/web.log`.

The homepage, `/health`, `/pipeline/regions`, `/system/status` and `/jobs` all
returned HTTP 200. Environment status was `ready`. Repeating the launcher reused
the same PID. All 15 historical job IDs/statuses were unchanged, including the
latest failure with a null result. No simulation job was submitted; no running
container remained. Historical outputs and failure records were not deleted.

## Focused read-only test-gap audit

Scope: process I/O, Docker adapters, launcher/health, and failure/provenance
contracts. The skill's `coverage_map.py --repo . --format json --top 0` was used
as a heuristic inventory, not a coverage percentage. It misclassified some
indirectly tested modules: baseline/scenario have explicit adapter assertions in
`test_runner_configuration.py`; provenance is exercised by pipeline reliability
tests. Assertions were inspected directly.

Retained protections include nonzero/signal propagation, missing executables,
unwritable log targets, append behavior, no pre-created producer directories,
timeout/failed startup, wrong-PID readiness, invalid health payloads, preserved
random seed/iteration config, failed-job null results and mismatched run IDs.

Residual validation gap: no cold Docker build or full network → demand → MATSim
run was executed under the new launcher. This would be the next integration
check with a new run ID, not a claim supported by these unit tests. Finder
double-click and browser/WebGL interaction were not re-tested; the shell syntax,
launcher process behavior and HTTP service were checked separately. No geometry
or front-end display code changed. Shutdown of Docker Desktop, OS shutdown and
disk exhaustion are not made recoverable by detaching the launcher.
