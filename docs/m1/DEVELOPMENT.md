# Reproducing the M1 development environment

These are developer instructions. The planned customer installer must automate
runtime installation; customers must not be asked to follow these commands.

## Main environment

Use the committed `pyproject.toml` and `uv.lock`, Python **3.12**, and the explicit
CPU extra. A plain `uv sync` omits torch because torch is an optional extra.

```text
uv sync --frozen --python 3.12 --extra cpu
uv run --no-sync pytest -q
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
```

On the tested Windows host, uv is installed as a module of the system Python,
so the equivalent invocation is `python -m uv ...`. uv locates the managed
Python 3.12 interpreter and creates `.venv`; system Python 3.14 is not used to
run the application. The lock installed torch 2.9.1+cpu, transformers 5.14.1,
numpy 2.5.1 and the recorded versions in `evidence/environment.json`.

Set `P2R_DEVICE=cpu`, `OMP_NUM_THREADS=4`, `MKL_NUM_THREADS=4` and
`HF_HUB_DISABLE_TELEMETRY=1` in the shell, then:

```text
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8096
```

Use an unused port. The user already had another Photo2Relief checkout running on
8090; the M1 verification therefore uses its own 8095/8096 ports and fails before
connecting if the test port is occupied. It does not stop the existing applications.

## DA3 worker

```text
uv sync --project da3worker --frozen --python 3.12 --extra cpu
uv run --no-sync pytest -q -m slow tests/test_depth_smoke.py::test_da3mono_real_inference_subject_nearer
```

Keep the main and worker environments separate. The worker's numpy 1.26 stack
conflicts with the main app's numpy 2 stack. The fixed lock targets CPython x64
Windows/Linux and pins the CPU torchvision local build explicitly. It must not be
advertised as an available macOS DA3 installation.

The M1 worker forces float32 on CPU because the vendor 0.1.1 API chooses float16
autocast based on CUDA capability even when the actual device is CPU. The original
real sphere test crashed natively on this machine; it passes with the CPU precision
fix. CUDA keeps the original vendor forward path. xformers warns that its CUDA
extension is unavailable in the CPU environment; CPU inference uses the fallback.

## Recreate photo evidence

```text
uv run --no-sync python -m tools.m1.fixtures
uv run --no-sync python -m tools.m1.baseline --large-exports
uv run --no-sync python -m tools.m1.baseline --offline --fresh --cases portrait --run-name verified
uv run --no-sync python -m tools.m1.baseline --models da2-large --cases portrait --run-name cpu-large
uv run --no-sync python -m tools.m1.baseline --models da3mono-large --cases portrait --run-name cpu-da3
uv run --no-sync python -m tools.m1.compare_surface
```

The runner starts the real server, uploads through HTTP, waits for real inference,
changes settings, saves both previews and GLB, exports STL/OBJ and reimports them.
`--fresh` changes one source pixel to prevent reuse of cached depth. Offline mode
sets offline flags and injects an acceptance-only socket guard. No fake depth
predictions are used by this runner. Existing unit tests use synthetic depth on
purpose to isolate processing/geometry, as recorded separately in the report.

Large exports and full model runs can use several GB of RAM. The 2048 stress rerun
demonstrated an out-of-memory failure while reimporting on the busy laptop. The
initial successful 2048 validation is recorded separately; do not overwrite or
relabel that failure as success. The runner records sampled backend process-tree
RSS; client reimport memory and GPU memory are not included in that number.

Generated meshes and model files remain under ignored `data/`. Small inputs,
comparison images, screenshots, preview GLBs and JSON results are versioned under
`docs/m1/evidence/`. Test image origin/license/hash data is in `inputs/sources.json`.

## Native proof and CI

See [bootstrapper instructions](../../bootstrapper/README.md). This Windows host
had MSVC tools but no SDK include/import-library directories. For the local build,
official Microsoft NuGet SDK 10.0.28000.2957 packages were extracted under ignored
`data/m1/windows-sdk`; MSVC/SDK INCLUDE, LIB and PATH were set only for that build
process. No customer requirement or global OS configuration change results from
that developer workaround. Hosted native runners build with their existing SDK.

The `M1 platform verification` workflow runs on Windows and Apple Silicon macOS:
fast tests, real CPU Small model smoke, locked Rust release build, Rust unit tests,
native executable acceptance and measured ZIP artifacts. `M1 optional DA3 CPU
verification` is a manual Windows route for the much larger worker/model smoke.
The original Linux CI and Docker publishing workflows remain present. No product
release tag, container publication or R2 upload was performed in M1.
