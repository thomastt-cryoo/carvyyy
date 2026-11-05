# M3 preservation and verification matrix

The original [M1](../m1/FEATURE_INVENTORY.md) and [M2](../m2/FEATURE_INVENTORY.md)
inventories, tests, source and evidence remain intact. New M3 examples use only the
supplied tiger and face. Historical astronaut evidence is unchanged.

B = actual browser execution before Browser Use failed; A = genuine HTTP/geometry
integration; U = isolated regression; P = final browser acceptance pending.

| Original parameter | M3 location / range | Verification |
|---|---|---|
| Model width | Customize → Width, 10–1000 mm | B/A/U; exact 160.125 saved |
| Relief height | Customize → Relief depth, .5–100 mm | B/A/U; 9.25 saved |
| Base thickness | Advanced → Backing thickness, .5–50 mm | B/A/U; 4.5 saved |
| Frame | Advanced → Border frame, 0–50 mm | B/A/U; 2.5 saved |
| Depth model | Advanced → Model, all three adapters retained | B/U; restricted disabled; same-model fix final P |
| Invert | Advanced → Invert relief | B/U, true saved |
| Gamma | Advanced → Depth contrast, .2–5 | B/U, 1.35 saved |
| Depth floor | Advanced → Far depth limit, 0–1 | B/U, .03 saved |
| Depth ceiling | Advanced → Near depth limit, 0–1 | B/U, .94 saved |
| Flatten background | Advanced → Flatten low depth | B/U, true saved |
| Flatten threshold | Advanced → Flatten threshold, full 0–1 | B/U, .78 saved |
| Smoothing | Customize → Smoothing, 0–10 | B/A/U, 1.6 saved |
| Edge-preserving filter | Advanced → Preserve edges | B/U, false saved |
| Detail blend | Customize → Surface detail, 0–1 | B/A/U, .09 saved |
| Edge taper | Advanced → Outer edge taper, 0–50 mm | B/U, 2.25 saved |
| Resolution | Export quality/dialog: 512/1024/2048 | A/U; new dialog P |
| Decimation | Export → Triangle reduction, 0–.95 | A/U, .15 genuine OBJ; new dialog P |
| Format | Export → STL/OBJ | A/U roundtrips; new browser downloads P |

| Added/preserved workflow | Implementation and actual qualification |
|---|---|
| Upload/default model | Tiger and face uploaded/inferred B/A. Drag/drop implemented; final gesture P |
| One prominent 3D canvas | Genuine GLB B. Orbit controls retained; new fit/reset/top/zoom final P |
| Photo/depth views | Implemented, final explicit switching P |
| Read-only comparison | B/A/U; import/source observed disabled during comparison |
| Automatic isolation | Existing cutout/optional U2NETP/GrabCut. Genuine alpha A/U; new method-selector browser P |
| Mask keep/remove/rectangle | Remove/undo B. All math/history U; keep/rectangle final P |
| Feather/transition/reset/disable | Preserved API U/A; new field adjustment browser P |
| Raise/lower/smooth/flatten | Raise B; all four A/U with exact undo/redo; other UI tools P |
| Brush radius/strength/level | Visible aligned cursor B; calculations U; exhaustive UI P |
| Undo/redo/reset/shortcuts | Browser undo B; persistence U; new keyboard/reset final P |
| PNG16/float32 exchange | A/U precision, orientation, version switching; redesigned dialog P |
| Restore original AI | A/U; new confirmation browser P |
| Presets/undo | Portrait B; all four and reversal U; other new UI paths P |
| Project names/recent/reload | B/U. Full library/switch/delete/restore browser P |
| Recoverable deletion | U; real tiger slow test. No permanent purge; model/cache protected |
| Checkpoints | A/U exact depth/mask, archived histories; browser dialogs P |
| Damaged metadata | Syntax/invalid-type repair and missing-image message U; browser P |
| Resource plan / export snapshot | A/U; dialog/download/browser refusal P |
| Dark/light | Switched B; startup persistence implemented; restart P |
| Responsive | Eight actual initial size/theme screenshots B, no horizontal overflow; compact-height fix observed at 1366; final recapture P |
| Offline frontend | Local ES modules/system fonts/no new runtime npm dependencies; offline browser trace P |
| Platform/launcher | Original adapters/native architecture preserved; local real CPU; CI results on PR; GPU/MPS not qualified |

Pending browser checks are not marked complete merely because their buttons exist.
Original AI depth stayed byte-identical throughout both real integration cases.
