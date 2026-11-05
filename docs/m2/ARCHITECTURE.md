# M2 architecture

M2 extends the M1 application; the original three adapters, 18 `ReliefParams`
fields, analytic solid mesh and offline three.js viewer remain. M1's native
bootstrap prototype is unchanged. This is not an M3 interface or customer installer.

## Durable document and one rendering path

`app/editing.py` owns a version-1 JSON journal under
`sessions/<uuid>/editing/state.json`. Original normalized photographs and original
`raw_depth_<model>.npy` predictions are immutable. Imports preserve both original
uploaded bytes and normalized float32 working arrays. Imported versions have UUIDs;
switching sources preserves their independent depth histories. Masks have their own
history shared by aligned sources. Every pointer gesture is one operation; undo/redo
moves a cursor, and new work after undo truncates only that layer's redo branch.
Reset is itself undoable. Restore AI selects AI, resets that model's depth journal,
and disables optional mask/quality settings; it preserves the original 18 settings.

Stroke coordinates are normalized photograph coordinates. Radius is a fraction of
the long side; strength is a normalized depth delta (raise/lower), or a blend
weight (smooth/flatten/keep/remove). A soft union of polyline segments makes a
gesture independent of pointer event density. Histories are limited to 500 gestures
per layer and 4 MB of JSON, with a useful export/reimport message before rejection.
Existing saved work remains readable. Atomic replacement and per-session locks
protect writes; revision checks return HTTP 409 rather than overwriting another
request. This is a single-process desktop backend, not a multi-worker server.

`app/pipeline.py` is the shared path for heightmap PNG, reduced GLB, STL and OBJ:

1. Read a fresh document or immutable export snapshot.
2. Select AI/imported float32 depth; replay only active operations; reuse disposable
   working-depth cache keyed by source and active journal.
3. Apply original clipping, inversion, gamma, flattening and smoothing controls.
4. Apply optional bounded multiscale smoothing and restrained photographic detail.
5. Blend masked heights into the backing over a physical distance, then edge taper.
6. Sample a bounded grid using exact physical coordinates; generate the original
   top, sidewalls and flat backing. Masks change heights, never cut mesh holes.

`original=true` creates a view-only original-AI comparison with the same physical
and original shaping settings, without saving or resetting the document. Browser
export is disabled during that view to make the shown/exported version explicit.
Export jobs retain a journal snapshot and separate output path per job; later edits
cannot replace an earlier download.

## Segmentation and optional quality

Built-in GrabCut uses color graphs and genuine-depth initialization, or a selected
rectangle. It is explicitly not semantic recognition. Real failures on all five
M1 examples remain in evidence. Optional U2NETP uses a pinned 4,574,861-byte ONNX
asset with SHA-256 verification before execution and optional ONNX Runtime CPU.
`auto` chooses it only when locally installed; otherwise the response identifies
GrabCut fallback. Runtime editing never downloads weights or sends images anywhere.
Rectangle inference crops the photo and maps the prediction back with zero outside.
One segmentation runs at a time; ORT sessions are short-lived and CPU arenas disabled
to avoid retaining their activation memory beside the depth model.

Both methods save immutable float32 masks. Keep/remove, undo/reset/disable and
physical feather/transition controls remain available. Subject detection cannot
recover occluded anatomy, whiskers, missing tower lattice or carved petals.

Optional sculptural smoothing bounds narrow depth residuals at two scales;
texture restraint limits luminance-derived grooves while retaining the existing
`detail_blend` control. Both default to zero and preserve original behavior.
Neither is represented as reconstruction. The controlled evaluation records the
fixed optional settings and limitations, including loss of fine ornament detail.

## Geometry and resources

`app/grid.py` separates physical source aspect from grid rounding. The complete
part, including frame, fits the resolution cap. Piecewise physical axes include
both exact content/frame boundaries; neither frame thickness nor source aspect is
inferred from rounded sample counts. Legacy pure mesh calls without source metadata
retain an inferred fallback; all application rendering supplies original dimensions.
Two samples minimum prevent degenerate thin grids; uploads beyond configurable
64:1 aspect are rejected with a crop message.

`app/resources.py` calculates grid, exact triangle count, approximate serialized
bytes and conservative memory. Configured memory and currently available-memory
budgets both apply. A rejection precedes mesh construction and is repeated when a
queued job starts. Whole-solid decimation still needs the full initial grid.
The plan is advisory estimation, not an operating-system reservation or OOM guarantee.
Two concurrent pipelines and one export worker bound normal preview/export activity.

`app/storage.py` only cleans known shared duplicate cache filenames under validated
SHA-256 directories. It uses no recursive deletion, ignores symlinks, checks resolved
containment, locks cache reads/writes/cleanup, and protects active/recent sessions.
Photos, per-session raw depth, masks, imports, histories, exports and model weights
are never eligible. Cleanup defaults to dry-run/manual; automatic cleanup is opt-in.
Full document management and deletion/recovery UX remain later work.

## Commercial and platform policy

The registry retains all three original adapters. Commercial mode defaults on,
uses Apache-listed Small on CPU/MPS and approved DA3 on supported CUDA configurations,
and blocks unauthorized V2 Large weight loading. API model metadata and controls
show authorization and platform availability. Research mode and an explicit
separately-authorized model list retain compatibility; environment flags do not
themselves grant rights. macOS DA3 worker remains unavailable as recorded in M1.
There is no automatic restricted-weight bundling or new customer package in M2.

Windows/macOS CPU CI covers fast regressions and one genuine Small/U2NETP editing
and STL/OBJ smoke. Unchanged native launcher proof remains M1 evidence; its workflow
is preserved and filtered to relevant changes to avoid duplicate macOS builds.
