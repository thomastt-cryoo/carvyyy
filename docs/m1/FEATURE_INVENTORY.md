# Preserved Photo2Relief feature inventory

Baseline: PotatoVibes/photo2relief `8f7cd6d3fdba13c872b0747b42eeb1ba62ae1c64`.
This checklist is based on source, not on the older SPEC defaults. No original
application feature or geometry algorithm was removed or rewritten in M1.

Status: **E** = exercised end to end with real inference; **U** = automated isolated
test; **S** = source audit only; **L** = limitation needing additional verification.
Unit tests deliberately use synthetic depth to isolate geometry; those results are
never presented as proof of AI inference. Model-specific evidence is in REPORT.md.

## Input, sessions and inference

| Preserve | Implementation and behavior | M1 evidence |
|---|---|---|
| Photo upload and replacement | Click, drag/drop, multipart API, original-name thumbnail | E, browser and HTTP |
| JPEG, PNG, WebP, HEIC/HEIF | Pillow/pillow-heif; decoded format allowlist | PNG/JPEG E/U; WebP/HEIC S, no real HEIC fixture |
| Upload limits | 40 MiB file, 30 MP decoded image; friendly rejection | U; no manual 30 MP stress inference |
| Phone EXIF rotation | `ImageOps.exif_transpose`, normalized RGB PNG | S; preserved, no new camera fixture acceptance |
| Image identity | SHA-256 of normalized source bytes | U/E |
| Session persistence | UUID directories; source/meta/params/depth/export files | E/U |
| Reload/resume | localStorage last-session ID + server identity/params | E, saved gamma 2.2 survived reload |
| Session path validation | Exactly 32 lowercase hex characters; traversal rejected | U |
| Model registry and license hints | `/api/models`, dropdown, per-model descriptions | E/U |
| Depth Anything V2 Small | HF Transformers adapter; disparity -> near=1 | E on five fixtures; offline fresh inference; CPU smoke on Win/Mac |
| Depth Anything V2 Large | Same adapter; CC-BY-NC-4.0 weights | Preserved; see model-specific results in report |
| Depth Anything 3 Mono Large | Isolated Python 3.12 worker, direct depth flipped -> near=1 | Windows worker installation repaired; see report for runs and failure |
| CPU/CUDA/MPS selection | Auto CUDA > MPS > CPU; explicit unavailable accelerator errors | CPU E; precedence/error U; accelerators L |
| Device defaults | CPU Small, CUDA DA3, MPS V2 Large | U/S; Mac default licensing issue documented |
| One resident model | Locked lazy backend; unload and accelerator cache release | U/S; accelerator memory behavior L |
| Working input cap | Long side at most 1024 by default; Lanczos input resize | U |
| Per-model and shared depth caches | `(image SHA, model ID, inference cap)` global cache, session copies | E/U; session cache itself omits changed inference-cap identity |
| Model switching | Save params, queue inference or reuse cached depth; preserve other tuning | U/API/source; GPU model switching L |
| Background depth queue | Single worker, polling status, elapsed/error text | E/U |
| Measured ETA | Last actual cache-miss timing per model/device, persisted JSON | U/E; first run no invented ETA |

## All 18 parameter fields

| Preserve | Actual schema range/default | M1 evidence |
|---|---|---|
| Physical image width | 10–1000 mm, 150 | E/U |
| Relief height | 0.5–100 mm, 8 | E/U, direct unit map peaks prove scaling |
| Base thickness | 0.5–50 mm, 3 | E/U |
| Border/frame width | 0–50 mm, 0 | U; full stock height, adds to finished part; quantization limitation |
| Depth model | Three registry IDs; seeded to device default at upload | E/U |
| Invert depth | Boolean, false; intaglio/mold use | U |
| Gamma | 0.2–5, **1.2** | E/U, live numeric commit and reload |
| Depth floor | 0–1, 0 | U; clips normalized values, not statistical percentiles |
| Depth ceiling | 0–1, 1; must exceed floor | U |
| Flatten background | Boolean, false | U; simple hard threshold, no subject segmentation |
| Background threshold | Schema 0–1, 0.15; UI slider 0–0.5, step 0.005 | U/S |
| Smoothing | 0–10 sigma pixels, **2.5** | U; applied at working resolution |
| Edge preservation | Boolean, **true** | U; OpenCV bilateral versus SciPy Gaussian |
| Fine detail blend | 0–1, **0.12** | E/U; luminance high-pass sigma 8, contribution scale 0.15 |
| Edge taper | 0–50 mm, 0 | U; linear ramp to base along image border |
| Export resolution | 512 / 1024 / 2048, 1024 | E/U, actual STL sizes and round trips |
| Decimation ratio | 0–0.95, 0 | U; whole-solid fast-simplification and second watertight gate |
| Output format | STL / OBJ, STL | Both E, all five fixtures |

## Preview and workflow

| Preserve | Implementation and behavior | M1 evidence |
|---|---|---|
| Automatic aspect ratio | Height derived from sampled image grid; width controls physical size | E/U; pixel quantization documented |
| Derived model and stock sizes | Content W/H plus border and base+relief | E; STL remains unitless, import as mm |
| Grayscale heightmap | PNG endpoint, checkbox | E/U |
| Shaded heightmap | Lambertian normal/gradient preview with mm scale | E/U |
| Interactive solid 3D | GLB, vendored three.js, wood material, grid, correct Z-up conversion | E; screenshots for all fixtures |
| Orbit/pan/zoom | OrbitControls, damping, camera preserved on ordinary tuning | Rotation/zoom E; pan S |
| Preview limits | 1024 image and 256 mesh **before frame padding** | U; frame-padding cap defect is an explicit expected failure |
| Settings updates | 300 ms 2D and 800 ms 3D debounce, no fresh AI for ordinary tuning | E/U, depth bytes/mtime unchanged |
| Stale request handling | Sequence counters, object URL/geometry disposal | S |
| Size/Shaping/Export tabs | Sliders plus numeric fields, checkboxes, dropdowns | E |
| Reset defaults | Canonical device defaults from backend | U/source/browser control present |
| Busy states/errors | Upload, inference, preview rebuild and export overlays | E/U |
| Parameter help | Tooltips, inline hints, local guide and example PNGs | Source/all static assets checked; no network fonts/CDN |
| Responsive layout | Side by side at desktop, stacked below 900 CSS pixels | Browser inspected at 1365×900 and default narrow size; narrow nested scrolling remains awkward |

## Mesh and exports

| Preserve | Implementation and behavior | M1 evidence |
|---|---|---|
| Structured 2.5D top | Two triangles per grid cell; no undercuts by construction | E/U; no machining/toolpath simulation |
| Flat back and walls | Perimeter wall strips, base fan at Z=0 | U, flat and extreme-aspect round trips |
| Outward geometry | Analytic face winding, positive signed volume | E/U; consistent winding after both imports |
| Watertight gate | Before export and after optional simplification; error on failure | E/U |
| Physical dimensions | mm coordinates, +Y=image top, Z=base+h×relief | E/U, source photo aspect rounded to grid |
| Binary STL | 80-byte header + face count + 50 bytes/triangle | E/U |
| Text OBJ | Vertices/faces, no unit metadata | E/U including reimport, rather than checking text alone |
| Export background queue | Single export worker separate from depth worker | E/U |
| Progress and download | Honest coarse stages; triangles, bytes and W/H summary | E/U; percentages are stage shares, not measured time fractions |
| Useful filenames | Sanitized original photo stem + stock W×H×thickness mm | E/U |
| Repeat download cache | Frontend reuses previous ready job when params unchanged | S; exports/jobs are memory tracked and reset on backend restart |
| Export file persistence | Saved in session directory | E; no automatic session retention limit/cleanup |

## Deployment capabilities retained

| Preserve | Current implementation | M1 status |
|---|---|---|
| Native development | Python 3.12, uv, FastAPI/Uvicorn | Windows E; Mac CI CPU E |
| CPU Docker image | CPU torch, Linux amd64/arm64 | Preserved/source inspected; Docker not run on this host |
| CUDA Docker image/Compose | cu128, NVIDIA reservation, isolated DA3 env | Preserved; no NVIDIA GPU/container test |
| Prebuilt GHCR path | CPU/GPU variants, version tags, multi-arch build workflow | Preserved; upstream image addresses not republished as this product |
| Local-only compose ports | 127.0.0.1 binding by default | Source; native verification also binds loopback explicitly |
| Configurable storage/device | All original P2R environment options retained | E/U/S |
| Offline assets | Vendored modules/help images/system font stack | E/source audit; model files need complete provisioning |

Every unchecked/L item is a verification debt, not a removed feature or a passing claim.
