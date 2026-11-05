# Photo Relief Studio — M3 completion report

2026-11-05 · `codex/m3-modern-workspace` · [PR #3](https://github.com/thomastt-cryoo/carvyyy/pull/3), based on approved M2 `d34392d29a5970faf051b1a0126249dcf8455508`.

## A. Executive summary

**M3 passes local functional acceptance.** A black/dark workspace replaces the old interface; light remains optional. New examples use the supplied tiger and face. M1/M2 source, tests and historical evidence remain intact. No M4 work has started.

A desktop restart restored browser authorization without a network configuration change. Completed 31 recorded browser checks and eight final theme/size captures. Final local results: 181 Python regressions, eight frontend tests and one fresh genuine tiger inference/export smoke pass. Final-head CI is reported on the PR; earlier-head CI remains historical evidence.

Monocular depth is an estimate. The tiger is emblem artwork, not a natural pet photograph. Production installers, CAM cutting and GPU/MPS qualification remain outside M3. Native drag/drop and right-button pan were not separately automated; picker upload, orbit/scroll and all camera buttons were exercised.

## B. UI implementation

Buildless HTML/CSS/ES modules retain local three.js, system fonts and zero runtime npm dependencies. No CDN, cloud inference, gradients, glass effects or emoji controls. Dark defaults before first paint and appearance persists locally. Project rail, prominent 3D/Photo/Depth/Edit canvas and Customize/Background/Sculpt inspector organize the workspace. Painting uses aligned 2D surfaces separate from camera navigation. Native dialogs, keyboard focus and explanatory labels remain. [Architecture](ARCHITECTURE.md).

## C. Beginner experience

Upload chooses an installed, supported and permitted model. Missing-model projects directly offer depth import and mark AI unavailable. Presets never download a model. Portrait/Pet/Object/Ornament change five disclosed shaping/refinement values; Custom retains values; Undo restores affected settings. Dimensions and painted work survive presets. Backend stages avoid fabricated ETAs. Invalid images show readable recovery advice. Setup distinguishes installed, restricted and download required; installation is a later milestone.

## D. Feature preservation

All 18 fields retain original backend mapping/ranges. Browser saving verified exact 160.125 mm width, 9.25 mm relief, .03/.94 limits and .78 threshold; resolution/reduction/format were exercised through exports. [Full matrix](FEATURE_INVENTORY.md).

Browser execution covered alpha/GrabCut/U2NETP, keep/remove/rectangle, mask enable/softness/transition/reset, four depth brushes, histories/shortcuts/reset, PNG16/NPY downloads/imports/versions, explicit stretch/orientation and original AI restoration. Comparison disables mutations and exports. Original AI hashes stayed unchanged. Same-model reselection and model changes with imported depth preserve readiness.

Final fixes: readable image-error recovery; versioned changed scripts; missing-model import guidance; corrected imports clear only their own validation failure, preserving unrelated failed-write protection (new regression); immediate preview scheduling feedback; rendering pauses when a project is cleared.

## E. Projects and persistence

Library search/thumbnails/recent, naming/reload/root resume and overlapping project switches were exercised. Queued writes and scoped responses protect boundaries. Delete confirms and moves a validated project to recoverable local storage; cancel and restore after reload pass. Models/cache remain shared.

Depth/mask checkpoints archive history; restore archives current work first. The UI explains starting a new undo history. Deliberately damaged metadata in a disposable project was repaired through the UI; backup and unchanged AI bytes were verified. No permanent purge or automatic pruning; recovery copies consume disk.

## F. Export

Standard/High/Maximum map exactly to 512/1024/2048. The actual 2048 tiger plan showed approximately 3911 MB against a 1536 MB budget and required an explicit lower-quality choice. There is no silent lowering. Actual browser downloads were reimported:

| Download | Triangles | Bytes | Geometry |
|---|---:|---:|---|
| Tiger STL, 512 | 528,374 | 26,418,784 | Watertight after standard STL vertex welding; consistent winding and positive volume |
| Tiger OBJ, 512, .15 reduction | 449,116 | 18,077,285 | Watertight, consistent winding, positive volume |

Both retain 150 × 150 × 11 mm bounds and flat bottom. Reduction is approximate: plan 449,118 versus actual 449,116. [Download geometry](evidence/browser-download-geometry.json). Earlier [genuine face/tiger integration](evidence/integration-results.json) also checks dimensions, precision and original AI. Actual cutting remains unverified.

## G. Actual screenshots

These are application captures, not mockups. The user-directed tiger replaces a pet photo example. Inspectors may scroll internally at narrow sizes.

- Welcome: [dark](evidence/welcome-dark.jpg), [light](evidence/welcome-light.jpg).
- Workspaces: [face](evidence/workspace-face-dark.jpg), [tiger](evidence/workspace-tiger-dark.jpg), [interactive 3D](evidence/interactive-3d.jpg).
- Editing: [background](evidence/background-tools.jpg), [depth](evidence/depth-painting.jpg), [original](evidence/comparison-original.jpg), [edited](evidence/comparison-edited.jpg).
- Controls: [advanced](evidence/advanced-settings.jpg), [export](evidence/export-interface.jpg), [resource refusal](evidence/export-resource-limit.jpg).
- Projects: [library](evidence/project-library.jpg), [recovery](evidence/project-recovery.jpg), [checkpoints](evidence/history-checkpoints.jpg).
- Setup/recovery: [installed](evidence/model-status.jpg), [missing](evidence/missing-models.jpg), [invalid image](evidence/error-retry.jpg).
- Narrow: [dark 1024](evidence/workspace-dark-1024.jpg), [light 1024](evidence/workspace-light-1024.jpg), [reachable controls](evidence/narrow-controls.jpg).
- [Eight final size/theme checks](evidence/responsive-checks.json): 1920×1080, 1440×900, 1366×768 and 1024×768; no horizontal overflow.

Initial compact-height spacing was corrected. Captures were inspected for clipping, dialog labels and spacing. The final Advanced capture uses representative values; the separate exact-field test intentionally used extreme inversion/threshold settings.

## H. Automated and browser verification

| Final local check | Passed | Failed | Other |
|---|---:|---:|---|
| Original/M1/M2/M3 Python regressions | 181 | 0 | Four slow deselected; zero skip/xfail |
| Frontend rules/queues/precision | 8 | 0 | Node built-in runner |
| Fresh genuine tiger smoke | 1 | 0 | Small inference, checkpoints, STL/OBJ roundtrips |
| Recorded browser checks | 31 | 0 | Genuine local backend |
| Final responsive captures | 8 | 0 | Both themes/four sizes |

[Counts](evidence/local-tests.json), [browser execution](evidence/browser-verification.json), [exact fields](evidence/browser-advanced-result.json). Ruff lint/format and JS syntax pass. Existing Starlette/httpx deprecation warning remains. Synthetic arrays isolate unit math; representative acceptance uses genuine predictions.

PNG16 is 16-bit grayscale; NPY is finite float32. Earlier integration measured PNG16 maximum quantization error 7.66e-6. The final browser ran behind enforced CSP denying external origins: real portrait rendering, saves and views, 40 recorded loopback requests, no console errors/warnings. HF offline was enabled. [Policy/trace](evidence/offline-browser.json). This is not an OS disconnect or packet capture. Temporary servers were stopped.

M3 Windows/macOS, preserved M2 Windows/macOS and Linux checks passed on the previous implementation head. Read final revision checks on [PR #3](https://github.com/thomastt-cryoo/carvyyy/pull/3); earlier runs must not be attributed to later commits.

## I. Performance

Ryzen 5 7520U Windows laptop, four CPU threads. Prior genuine first tiger inference: 21.672 s; warm face: 6.562 s. Cached shaded/GLB: .653/.626 s tiger, .582/.522 s face. Edited STL/OBJ: 2.238/3.944 s tiger, 1.106/2.473 s face. Sampled server RSS: approximately 500–795 MiB; excludes browser/GPU/worst-case model concurrency. These are individual observations, not benchmarks.

Final fast suite: 60.30 s; fresh smoke: 77.102 s including setup/export. Browser heap telemetry was unavailable. [Footprint](evidence/frontend-footprint.json) records local asset sizes; zero new runtime npm dependencies. Rendering pauses outside 3D and when clearing a project.

## J. M4 readiness

M3 is ready for review after final revision checks. No automatic M4 progression, merge, production installer or Cloudflare deployment. Remaining priorities: model-quality refinement, production setup/storage management, GPU/MPS qualification and real CAM validation. Faces/hair/ornament remain estimates; tiger artwork brightness can become false relief. Presets cannot reconstruct hidden anatomy. Inspect every solid in CAM.
