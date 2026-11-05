# M2 feature inventory

The full [M1 inventory](../m1/FEATURE_INVENTORY.md), original 18 parameters, all three
adapters, PNG heightmap, GLB preview, STL/OBJ export, offline assets, model cache,
EXIF normalization and native bootstrap proof remain. M2 changes intentional
behavior where M1 documented defects; see below.

| Capability | M2 implementation | Verification |
|---|---|---|
| Subject isolation | Built-in depth-assisted GrabCut; optional verified local U2NETP CPU | Five genuine M1 inputs; successes and failures retained |
| Manual mask | Keep/remove soft strokes; selected ROI; separate undo/redo/reset/disable | Isolated math, persistence, browser painting |
| Edge transitions | Feather and backing blend in physical mm; default new documents 4 mm transition | Continuous solid mesh, numerical gradient test, shaded/3D evidence |
| Depth exchange | PNG16 and float32 NPY; AI/imported/working export | Precision, invalid type/range/header/aspect, browser download/header |
| Depth import alignment | Same-aspect resample; explicit different-aspect stretch; white-far option | Float tests, source/version switching, real edited export smoke |
| Nondestructive depth | Raise/lower/smooth/flatten; brush size/strength/level | Independent math, browser tools and actual export integration |
| Saved editing | Atomic journal, immutable imports/masks, per-source history/revision | Reload/undo/redo/reset tests and browser reload |
| Reopen document | Bookmarkable session query plus original last-session resume | Browser reload and five-subject 3D evidence |
| Before/after | View-only original AI in both 2D and 3D; same physical settings | Read-only document test, browser comparison |
| Sculptural controls | Optional bounded multiscale smoothing, restrained luminance detail | Real five-subject comparison with unresolved anatomy/petal limitations |
| Original shaping | Gamma, clipping, smoothing/bilateral, detail blend, invert, flatten, edge taper | Original regressions; both optional new amounts zero preserve behavior |
| Frame-inclusive grids | Bounded full-part sample counts, minimum thin-grid side | D01/D02 now passing, extreme aspect crop policy |
| Exact mm aspect/frame | Source dimensions independent of grid rounding; exact frame boundaries | Asymmetric/frame regressions and STL/OBJ bounds |
| Resource plan | Grid/faces/bytes/RAM before queue and mesh; friendly refusal | Forced small budget tests, actual 512 exports, 2048 preflight |
| Export snapshots | Immutable journal snapshot, separate saved file per job | Later AI reset cannot change imported+edited export test |
| Cache maintenance | Safe manual/dry-run shared-cache quota/age cleanup | Active lease, protected files, symlink and containment tests |
| Commercial policy | Restricted Large retained and labeled; approved commercial defaults | Weight-load guard, unchanged params on rejection, mode/authorization tests |
| Platform support | Existing Windows/macOS architecture; DA3 macOS remains unavailable | M1 native CI retained; M2 CPU editing CI |

Intentional regression-test updates: a framed heightmap now stays at its requested
64-sample cap instead of asserting the old 84-sample padding bug. MPS commercial
default is now Small; research mode can still select Large under its terms. No
original parameter or adapter was removed. Display previews remain reduced resolution.

M3 should consolidate these functional controls, surface per-document management,
improve history/tool affordances and show model installation state. It must retain
the advanced controls and the separation between automatic estimates and authored
corrections. No final interface redesign, production package, G-code or CAM engine
was undertaken in M2.
