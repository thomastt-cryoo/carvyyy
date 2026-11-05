# M3 developer route

Use the same Python 3.12 environment and explicit CPU extra as M2. There is no
frontend build or package installation required to run this local application.

```text
uv sync --frozen --python 3.12 --extra cpu
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8098
uv run --no-sync pytest -q
node --test tests/frontend/workspace.test.mjs
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
```

On the recorded Windows host, uv is invoked as `python -m uv`. System Python 3.14
does not run the application; `.venv/Scripts/python.exe` is the Python 3.12 runtime.
Node 22+ is a developer-test tool only. All browser assets are local ES modules.

The optional segmentation extra/verified asset setup remains documented in
[M2 DEVELOPMENT](../m2/DEVELOPMENT.md). Automatic uses a source PNG's existing alpha
cutout first; neither new user-supplied example requires a new segmentation model.
The application never offers missing models as selectable and never downloads one
because a preset was chosen.

For reproducible local inference, set `P2R_DEVICE=cpu`, `OMP_NUM_THREADS=4`,
`MKL_NUM_THREADS=4`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and
`HF_HUB_DISABLE_TELEMETRY=1` after models are installed. For isolated acceptance,
set `P2R_DATA_DIR=data/m3/run` and point models/cache to the existing installation.
Do not stop unrelated servers. M3 used port 8098; earlier M2 used 8097.

`tests/test_m3_smoke.py` is an explicit slow test: genuine local Small inference on
the supplied tiger, alpha isolation, project rename/preset/paint/checkpoint, STL/OBJ
roundtrip and recoverable deletion/restore. Its synthetic-free model portion is
separate from unit tests, which use small arrays to isolate editing calculations.

`tools/m3/acceptance.py` records HTTP integration for the two local M3 evidence
sessions, requiring their IDs as recorded at the top of the script. It verifies raw
hashes, all four brush tools, undo/redo, PNG16 precision, imported version switching,
read-only comparison, STL and simplified OBJ, dimensions and resource refusal.
Use the original `inputs/tiger.png` and `inputs/face.png` for new sessions when
reproducing on a new installation; update the evidence-session mapping accordingly.
Large exported solids remain in ignored `data/m3/exports`, with hashes and geometry
results in versioned JSON. Historical M1/M2 images/evidence are not replaced.

Browser verification must use the configured computer/browser-use tool. Do not
substitute fabricated screenshots or direct requests for UI acceptance. Recorded
screenshots are actual earlier browser execution. If local browser use is disabled,
finish independent tests and keep remaining browser acceptance explicitly pending.

Settings and dimensions are autosaved. Deleted project directories are moved to
`project-trash` beside `sessions`; restore via the library's Recently deleted area.
No permanent purge or automatic edited-project deletion is implemented. Explicit
checkpoints retain archived states on disk; users must be told about the transition
to a new undo history. Damaged metadata repair keeps a backup under `recovery/`.
Backups/checkpoints/recovery copies intentionally require a future storage UX for
disk limits and permanent deletion. Do not remove these files automatically.
