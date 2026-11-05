# Photo Relief Studio · M4 completion report

## A. Executive summary

**Local M4 acceptance passed.** The Windows browser and CNC checks ran on actual reliefs. The app keeps the dark workspace and visible settings, adds reversible surface refinement, handles large inspection meshes explicitly, and reports disk usage with reviewed cleanup and deletion. M4 starts from the approved M3 revision `6d42000`.

FreeCAD imported both tiger exports and computed a toolpath. Stock-removal simulation, postprocessing, and physical cutting remain untested. The portrait and ornament studies still show missing form. Native macOS browser testing remains open. Cross-platform CI results are tracked on the M4 pull request.

## B. Relief quality

Eight studies used genuine inferred depth for a face, cat, dog, tiger, ornament, Hopper portrait, cup, and complex rocket scene. The adopted option, **Soften fine ridges and grooves**, evaluates narrow ridges and depressions in a 1.2 mm neighborhood. It is off by default and changes the working surface by up to 0.18 mm. It leaves the original AI depth, subject mask, and edit history available. The preview and export use the same refinement.

| Study | Change in fine-scale RMS variation | Observation |
| --- | ---: | --- |
| Face | −7.6% | Light texture reduction. Eye sockets, lips, ears, and jaw remain dependent on the predicted depth. Hairline transitions can still be uneven. |
| Cat / dog | −15.4% / −10.8% | Some fur ridges soften. Whiskers, eyes, and snout relief still depend on the input. Cat p99 slope increased from 39.8° to 42.6°. |
| Ornament / cup | −7.8% / −15.2% | Small surface changes. The ornament still has shallow central detail. |
| Tiger / Hopper / rocket | −0.6% / −11.3% / −9.8% | The tiger changes little. Background isolation and manual sculpting remain useful for stray depth. |

The metric measures variation at the refinement scale. The comparisons do not establish anatomical accuracy or cutter clearance. Tested alternatives included morphological filtering, broad detail enhancement, and brightness-driven embossing. Morphology had little effect on several samples. Broader enhancement amplified some texture and lighting artifacts, and brightness could raise or recess the wrong features. Those methods were left out. Processing took roughly 10–152 ms per source on this workstation.

On the same cutout portrait, Depth Anything V2 Small and DA3Mono Large produced different relief. An approximate nose-to-cheek measurement was 1.924 mm for Small and 0.323 mm for DA3 on that sample. A single image provides no reference for physical depth. The original AI view and nondestructive brushes remain available for shaping those regions.

[Quality measurements](evidence/quality.json) · [Portrait model comparison](evidence/portrait-models.json)

## C. Original functionality

All 18 original parameters and existing presets remain. Refinement is a separate edit option. Original AI depth, alpha isolation, GrabCut, optional U2NETP, keep/remove mask brushes, depth brushes and history, 16-bit PNG and float32 NPY exchange, local projects, recovery, dark/light themes, lighting, progressive preview, exact export inspection, STL/OBJ, and resource preflight remain available. The regression suite exercises older project data, edit replay, downloads, export parity, and original parameter values.

## D. CNC validation

| Check | Result |
| --- | --- |
| Tiger STL and OBJ | 512 samples with 95% triangle reduction and refinement enabled. Each had 26,418 facets and imported as a closed native mesh in FreeCAD 1.1.4. |
| Native dimensions | 150 × 150 × 11 mm, flat backing at Z=0. |
| Part conversion | One closed valid shell with 26,418 faces and volume of 125,518.57 mm³. |
| Surface operation | 3 mm ball-end tool, stock boundary, planar zigzag, 40% stepover, and 0.8 mm sampling. FreeCAD reported **Valid** and **Up-to-date**. |
| Computed path | 12,537 commands, including 11,903 cutting moves with an explicit Z between 3.000 and 10.999 mm. The recompute took 10.65 s. |

The exact files, checksums, native project, and screenshot are preserved in the local evidence. The model-boundary attempt reached the 180 s limit at about 1.38 GiB sampled working set. The stock-boundary run used the same relief as the cutter-contact model and peaked at about 479 MiB. M4 also corrected a 0.0054 mm height overshoot observed under aggressive mesh reduction. The reduced exports now stay inside the full mesh bounds.

The export dialog reports actual thickness, steepest measured top face, and projected area at 60° or steeper. The check excludes backing and vertical stock walls. Stock removal, workholding, tool reach, postprocessing, and machine behavior require separate validation.

[Native FreeCAD measurements](evidence/freecad.json) · [Application geometry and hashes](evidence/geometry.json)

## E. UI polish

The workspace opens in dark mode with customization controls visible. Light mode is still available. The narrow layout keeps lighting labels with their sliders and prevents a hidden accessible label from scrolling the header offscreen. Browser measurements at 1024 × 768 and 1366 × 768 showed the settings visible without horizontal page overflow. The refinement control lives with the other settings. The export dialog distinguishes live preview, exact inspection, and the resource warning. The local report links actual browser screenshots for both themes, the four study subjects, isolation, sculpting, inspection, export safety, projects, storage, and narrow layouts.

## F. Preview and performance

The live view draws a 256-sample mesh before refining to 512. Export inspection opens the geometry generated with the chosen export settings. The browser loaded the unreduced 1024 tiger export with 2,105,334 triangles, then returned to the 512 live mesh. The STL was 100.4 MiB. An explicit load step and cancellation control protect the live workspace. Above 2,250,000 triangles, the exported file remains available for external inspection and download. Switching projects or leaving inspection disposes superseded view resources.

On the Windows test machine, Tiger GLB generation took roughly 0.8–0.95 s at 256 and 0.78–0.82 s at 512 from cached depth. The reduced STL and OBJ took 3.60 s and 2.98 s. Settled process RSS ranged from about 378–634 MiB over the export test run. These are backend readings and do not quantify browser or GPU memory. The 2048 resource check correctly refused an estimated 3,911 MB allocation against a 1,536 MB budget. A fresh Tiger upload and CPU inference with Small took 21.9 s for inference.

[Geometry and timings](evidence/geometry.json) · [Browser results](evidence/browser.json)

## G. Storage

Storage reports saved project data, recovery, cache, exports, inspection meshes, and shared model data. The cleanup dialog previews disposable duplicate cache bytes before removal. A stale review requires a new plan. Active work and current file transfers retain a project lease. Saved originals, masks, editing history, and exports remain protected from cache cleanup.

Deleting a project from the library moves it to recovery. Permanent deletion requires a separate review of a single deleted project. Interrupted deletion can resume from its staged location. Tests covered restore, selected purge, stale plans, interrupted purge, path escape refusal, and broken working-cache replay. The browser exercised duplicate cache cleanup on disposable test data and canceled the permanent deletion confirmation.

## H. Input robustness

Tests exercised genuine encoded JPEG, PNG, WebP, TIFF, and HEIF, including portrait and wide dimensions. The app applies EXIF orientation before measuring the working image and retains source transparency and the original upload bytes. The actual transparent tiger PNG completed a browser upload and inference. Invalid or truncated inputs, size limits, path escapes, and failed writes are handled without publishing partial projects. An invalid disposable depth array is regenerated or replayed. Damage to a required saved source is reported.

## I. Tests

| Verification | Local result |
| --- | --- |
| Python fast suite | 198 passed, 0 failed, 4 slow cases deselected |
| Genuine CPU inference regressions | 2 selected, 2 passed |
| Frontend Node suite | 8 passed, 0 failed |
| Ruff lint and format | Passed |
| Windows browser | Passed in the in-app browser and Chrome |
| Offline browser | Preview and project controls passed with external browser connections blocked and assets served locally |
| GitHub Actions | Linux, Windows, and macOS checks tracked on the pull request |

The browser exercises included upload, project switching during an edit, dark/light mode, mask isolation, sculpt undo/redo, exact inspection, safe export refusal, and storage. The automated runs emitted an existing Starlette/httpx deprecation warning. Genuine slow tests were selected to cover the relevant M2 and M3 pipelines, with a separate real M4 Tiger upload and the CAM study.

[Browser results](evidence/browser.json) · [Loopback request trace](evidence/offline-requests.jsonl)

## J. Release-readiness risks

Native Safari/WebGL, macOS app launch, and signing/notarization remain unverified. Hosted macOS CI exercises the Python and Node workflows. Large exports and CAM conversion depend on memory, mesh density, and the toolpath algorithm. One photo can provide ambiguous depth, especially in facial features, fur, flat ornamental marks, and complex backgrounds. Distribution still requires clean-machine dependency, codec, model license, signature, and recovery checks on each target platform.

## K. M5 handoff

Proposed architecture for review is a small signed launcher and an isolated Python 3.12 CPU runtime per OS/architecture, with the current FastAPI server bound to loopback and the system browser as its frontend. Put mutable projects, recovery, settings, and model caches under per-user application data. Supply a versioned manifest with sizes and SHA-256 for the runtime, vendored frontend assets, codec/native wheels, default model, and optional packs. Stage and verify downloads before activation. A previously installed version should start offline, with runtime upgrades separate from saved projects. Start with Windows x64 and macOS arm64. Treat Intel Mac support as a separate compatibility decision.

| Component | Proposed delivery |
| --- | --- |
| Launcher and UI | Signed Windows launcher or signed/notarized macOS bundle, plus offline assets and loopback lifecycle management. |
| Main inference and geometry | Pinned CPU PyTorch, Transformers, Python web dependencies, NumPy/SciPy, Pillow/HEIF, OpenCV, Trimesh and mesh simplification. |
| Default model | Depth Anything V2 Small on both platforms. Observed local weight/cache payload 94.6 MiB. |
| Optional models | DA2 Large cache 1,279.2 MiB and DA3Mono Large cache 1,274.8 MiB before dependencies. Offer only after platform performance and distribution license checks. Keep DA3's worker environment isolated. |
| Optional segmentation | Separate platform-specific ONNX Runtime/U2NETP pack with verified offline artifacts. |
| First-install transfer | Planning estimate 350–650 MiB for Windows x64 and 250–500 MiB for macOS arm64, including Small. These ranges are budgets until signed release candidates are measured. |

Open decisions include a downloadable offline bundle versus a staged installer, the model license and pack policy, platform minimums, and which CAM and physical carve tests are required before commercial release. M5 implementation has not started.
