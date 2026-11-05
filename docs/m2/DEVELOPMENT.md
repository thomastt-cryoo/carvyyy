# Running and verifying M2

Developer route only. M1's bootstrap prototype remains under `bootstrapper/`;
production installer work is not part of M2.

```text
uv sync --frozen --python 3.12 --extra cpu
uv run --no-sync pytest -q
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8097
```

For optional stronger isolation:

```text
uv sync --frozen --python 3.12 --extra cpu --extra segmentation
uv run --no-sync python tools/m2/install_segmentation.py
uv run --no-sync pytest -q -m slow tests/test_m2_smoke.py
```

Only the explicit install step downloads U2NETP. It validates exact length and
SHA-256 before atomic installation to `data/models/segmentation/u2netp.onnx`.
Missing runtime/weights falls back to GrabCut in Automatic mode. Explicit U2NETP
selection reports setup guidance; a corrupt asset is rejected. See the
[original U-2-Net repository and Apache license](https://github.com/xuebinqin/U-2-Net),
[rembg model reference/checksum](https://github.com/danielgatis/rembg/blob/main/rembg/sessions/u2netp.py)
and [ONNX Runtime Python instructions](https://onnxruntime.ai/docs/get-started/with-python.html).
No rembg dependency or cloud API is installed.

On this Windows machine, replace `uv` with `python -m uv`. Use Python 3.12 from
`.venv`, not system Python 3.14. Always retain the CPU extra when syncing, or torch
will be removed. `uv run --no-sync` preserves selected extras.

Use `P2R_DEVICE=cpu`, `OMP_NUM_THREADS=4`, `MKL_NUM_THREADS=4` for comparable CPU
measurements. After explicit model setup, `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1` enforce offline Hugging Face loading. The five M2 controlled
examples reuse the genuine M1 Small arrays, verified byte-for-byte; the separate
real-model smoke forces a fresh prediction in a new cache.

## Configuration additions

| Setting | Default | Meaning |
|---|---|---|
| `P2R_EXPORT_MEMORY_MB` | 1536 | Conservative export working-memory budget |
| `P2R_MEMORY_FRACTION` | 0.55 | Maximum share of currently available RAM |
| `P2R_EXPORT_MAX_TRIANGLES` | 9000000 | Additional full-grid face cap |
| `P2R_MAX_IMAGE_ASPECT` | 64 | Upload long/short aspect limit |
| `P2R_CACHE_MAX_MB` | 2048 | Shared duplicate-cache quota |
| `P2R_CACHE_RETENTION_DAYS` | 30 | Cache retention threshold |
| `P2R_AUTO_CLEAN_CACHE` | false | Enable duplicate-cache cleanup at startup |
| `P2R_COMMERCIAL_BUILD` | true | Block restricted weight loading/defaults |
| `P2R_AUTHORIZED_MODELS` | empty | Comma-separated IDs with separately obtained rights |

Memory estimates include constructing the full mesh before simplification. 2048
remains selectable; it may require more RAM and an explicitly raised budget.
Never raise limits merely to make a test pass or deliberately exhaust the laptop.

## Session and exchange API

All routes below are under `/api/sessions/{sid}`. Open `/?session={sid}` to reopen
an existing document; uploads update that bookmarkable address. Last-session resume
still works without the query. There is no document-library UI yet.

| Route | Purpose |
|---|---|
| `GET/PUT /editor` | Saved source/settings/revision; partial settings changes |
| `POST /editor/stroke` | Normalized polyline, radius, strength, tool/channel |
| `POST /editor/history` | Depth/mask undo, redo or undoable reset |
| `POST /editor/restore-ai` | Restore original AI workflow without overwriting source |
| `GET /segmentation` | Optional model/runtime availability, bytes, checksum |
| `POST /editor/automatic-mask` | Method auto/grabcut/u2netp, optional normalized rectangle |
| `GET /editor/image` | Photo, original AI, working, mask or processed display PNG |
| `POST /depth/import` | Multipart `file`; white_is_far and match/stretch alignment |
| `GET /depth/export` | Source ai/imported/working; png16 or float32 npy |
| `POST /export-plan` | Same 18 parameters; estimate and safe/refused result |

Mutations accept `expected_revision`; stale changes return 409. Import sources use
`depth_source` plus optional saved `import_id`. Imports accept only grayscale PNG16
or floating 2D NPY, finite normalized 0–1 values. NPY headers are checked before
allocation. Aspect mismatches over 1% require explicit Stretch; this is deliberate
distortion, not automatic registration. Same-aspect maps resample to aligned working
resolution. Original imported bytes remain available on disk. Display PNGs are
8-bit for viewing; exchange endpoints retain 16-bit or float32 precision.

`GET /api/storage` reports usage. `POST /api/storage/cleanup` defaults to
`{"dry_run": true}`; passing false only removes eligible duplicate cache files.
Protected sessions are not a cleanup target. Export jobs survive only as saved
files after restart; transient job polling IDs do not.

## Reproducing visual evidence

`tools/m2/evaluate.py --phase automatic` creates five sessions and checks every
original depth against M1's genuine cached prediction. Run it with only GrabCut
installed, or select GrabCut explicitly when reproducing its retained failure stage.
Start a separate offline server with data directory `data/m2/run`, shared M1 models
and cache. Then run `tools/m2/final_evidence.py --pid <actual-backend-pid> --export`.
It samples server RSS every 20 ms, uses the same original image/model/18 parameters,
and measures both original and edited previews. Avoid concurrent tests/browser
requests while measuring. It validates each 512 STL and OBJ after reimport; large
solids stay in git-ignored `data/m2/exports`, with hashes and topology in JSON.

`editing-document.zip` holds actual journal and referenced immutable float masks.
Original source is linked from M1; exact AI float arrays and PNG16 exchange files
are in each evidence folder. GLBs are actual pipeline output, not illustrations.
Subject-specific conclusions and unsupported platform/CAM claims belong in REPORT.md.
