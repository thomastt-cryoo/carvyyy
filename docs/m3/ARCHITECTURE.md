# M3 local workspace architecture

M3 starts at approved M2 `d34392d29a5970faf051b1a0126249dcf8455508`.
The inference adapters, heightmap engine, exact physical grid, solid mesher,
resource estimates and export-snapshot pipeline remain from M2. The native launcher
and distribution architecture remain unchanged. No Electron, cloud hosting, CDN,
remote fonts, telemetry or installer is introduced.

## Frontend

The runtime is buildless HTML/CSS and ES modules, with existing vendored three.js.
`package.json` only declares module syntax and Node's built-in test runner; there
are no mandatory npm dependencies or build output. Prettier was used as a developer
formatter through npm's registry; it is not shipped or required to run the app.

- `workspace.js`: document lifecycle, navigation/library, field binding, queue,
  presets, progress, import/export and dialogs.
- `core.js`: pure schema-facing field definitions, exact numeric validation,
  supported quality mapping, model selection, project scope and serialized queue.
- `viewer.js`: existing GLB/OrbitControls integration; fit/reset/top/zoom, theme,
  geometry disposal, and rendering only while 3D is active.
- `painting.js`: source-aligned 2D canvas with separate mask/depth tools, normalized
  points and visible brush/stroke feedback. No brush listeners on the 3D canvas.
- `workspace.css`, `appearance.js`, `icons.js`: local appearance and SVG icons.
  Dark/black is the default requested by the user; persistent light remains optional.

A compact project rail, one switchable main canvas, and a purpose-grouped inspector
replace the earlier side-by-side preview/control cards. Primary controls stay near
the top; exact advanced settings scroll within the inspector. Small desktop widths
collapse the rail; very narrow widths use a collapsible inspector. Dialogs use native
focus containment/Escape behavior. There are no emoji controls or decorative gradients.

Every document transition flushes the pending parameter debounce and edit queue.
Failures stop that flush and expose retry/reload instead of silently switching.
Scope tokens include project ID and generation, so a stale response cannot be
applied after switching away and returning to the same project. Preview sequence
tokens additionally prevent old view requests replacing a newer view. Editor writes
retain M2's expected-revision checks. Original-AI comparison is read-only across
fields, painting, imports, checkpoints and exports, not only the visible sliders.

## Projects, deletion and recovery

Existing session UUID directories become customer-facing projects. The new small
`project.json` stores display name, creation time, preset and preset undo state;
source, raw depth and editing files keep their original locations. Parameters and
session status now use temporary-write/atomic-replace rather than direct overwrite.
`project_store.py` tolerates malformed or invalid-shaped project metadata in the
library and exposes repair issues. Repair backs up existing metadata/settings before
rebuilding, and refuses a missing/damaged original with recovery advice. It never
rewrites raw depth, photos or brush files.

`DELETE /api/projects/{id}` moves only that validated project directory to a sibling
`project-trash/{id}` on the same filesystem. It does not recursively delete anything.
Symlink/containment checks and active inference/export/lease checks prevent unsafe
moves. The UI confirms deletion, offers immediate Restore, and has Recently deleted
in the library for recovery after reopening. There is no permanent-purge UI in M3;
recovery copies continue to consume disk. Model weights and shared cache are separate.

Inference tracks queued/running projects in memory, permitting an interrupted
processing state to be distinguished after restart. Existing session status APIs
remain compatible; the project API adds interrupted-state metadata and Retry.

## Presets and histories

Portrait/Pet/Object/Ornament presets are explicit combinations of original gamma,
smoothing/detail blend plus M2 sculptural smoothing/texture restraint. Their exact
values are in `projects_api.PRESETS`. Width, depth, backing, frame, source/model,
mask and brush journals are retained. Model selection already chooses an installed,
permitted model on first upload. Presets do not invoke unavailable models or trigger
segmentation over existing painted masks. The Background action remains explicit.

Preset Undo restores the affected settings, preserving unrelated dimensions and
all painted work. Custom is a label for current settings, not a reset. The displayed
preset is derived from actual returned values, changing to Custom after a manual
adjustment. These are starting points, not new reconstruction algorithms.

Explicit checkpoints archive the complete editing state and keep all referenced
files. Depth checkpoint creates a new immutable float32 imported source from the
current working depth and starts a fresh per-source history. Mask checkpoint writes
the current float mask as a single replacement operation. Restoring a checkpoint
archives the present state first. The dialog explains that earlier undo history
moves into an archive; it never clears work silently. Original AI/photos remain.
This is a single-process application with existing per-session locks, not a
multi-worker datastore. Checkpoint archives are not automatically pruned.

## Transparent inputs and model setup

The user's new tiger and face inputs are PNG cutouts. Their exact uploaded bytes
and normalized RGBA cutout are retained. The RGB inference image is composited on
white so hidden transparent RGB pixels cannot accidentally become a black rectangle.
Original alpha is stored aligned with the photo. Automatic isolation prefers this
existing cutout, explicitly labeled as original transparency, before optional
U2NETP/GrabCut. It is not represented as AI segmentation. This small input fix changes
the cache identity appropriately; raw inference for both new sources is genuine.

`model_status.py` inspects only local snapshot metadata and safetensors headers/file
extent. It never loads or downloads weights to list setup state. The UI distinguishes
installed/loaded, download required, damaged, runtime setup required, unsupported,
restricted, and current local processing. Header validation is not a cryptographic
model-integrity guarantee. Only selectable states are enabled. Upload without a
usable installed model still creates a local project for high-precision depth import.
The complete one-click setup installer remains later work.

## Additional API surface

| Route | Purpose |
|---|---|
| `GET /api/projects` | Local library, thumbnail, dates, issues/interrupted state |
| `POST /api/projects/upload` | Installed-model generation or import-only project |
| `GET/PATCH /api/projects/{id}` | Open / rename |
| `POST /api/projects/{id}/preset`, `/undo-preset` | Explicit shaping collection / reversal |
| `POST /api/projects/{id}/retry`, `/repair` | Generation retry / backed-up metadata repair |
| `DELETE /api/projects/{id}` | Confirmed recoverable local move |
| `GET /api/projects/deleted` | Recoverable project listing |
| `POST /api/projects/{id}/restore` | Restore validated recovery copy |
| `GET /api/sessions/{id}/editor/checkpoints` | Archived edit states |
| `POST /api/sessions/{id}/editor/checkpoint` | Explicit layer checkpoint |
| `POST /api/sessions/{id}/editor/checkpoints/restore` | Archived state restore |

All original M2 APIs remain. M3 still exports saved edited state through the same
resource preflight, immutable snapshot and watertight gates. Export quality names map
exactly to 512/1024/2048. The UI never silently lowers quality. Completion provides
an explicit Download action; closing the export dialog does not falsely cancel a
backend job. Stage progress is backend progress, not an invented ETA.
