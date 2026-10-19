# Run and review

## Review in five minutes — no installation

Open `portfolio/index.html` in a browser after extracting the review package.
It embeds the featured aggregate data and uses local assets. Read the overview,
compare the three seeds, inspect the missing-value repair, then open the evidence
JSON/CSV or the English brief. The two-minute tour is a recording of this
read-only showcase; its replay screenshot is labelled as recorded simulation.

## Run the local product

Use Python 3.10+ and Docker Desktop; on Windows run Python and the repository
inside Ubuntu/WSL2 with Docker's WSL integration enabled. This machine's project
is `/home/ksm/matsim`. The existing Windows MATSim desktop shortcut starts it.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m wrapper.cli doctor
python -m wrapper.server
```

Open `http://127.0.0.1:8000/`. Historical replay does not launch a simulation.
The API and raw-results routes are intended for local use. Distribute the
aggregate-only showcase rather than exposing this writable local service publicly.

For new simulations, prepare the external data in [DATA_PREPARATION.md](DATA_PREPARATION.md)
and source-matching Docker images. The initial network image is built explicitly:

```bash
python -c 'from wrapper.runner import build_image; build_image()'
```

The featured **ten-iteration, three-seed** experiment is documented in
[PLANNING_CASE.md](PLANNING_CASE.md). The normal CBD quick pipeline uses
iterations 0–2 and is a different run profile. The older capacity experiment in
[REPRODUCIBLE_DEMO.md](REPRODUCIBLE_DEMO.md) remains a separate historical protocol.

## What was verified on Windows/WSL

All three Docker images were built in the new Windows/Ubuntu environment and a
fresh short simulation completed with 1,037 agents, 3,623 trips and iteration 0.
It reused migrated network/demand inputs. This is not evidence of regenerating
all external data or rerunning the complete nine-run experiment on Windows.
See [validation](../validation/2026-10-18-p0.md).
