# M3 preservation and verification matrix

The original [M1](../m1/FEATURE_INVENTORY.md) and [M2](../m2/FEATURE_INVENTORY.md)
inventories, tests, source and evidence remain intact. New M3 examples use only the
supplied tiger and face. Historical astronaut evidence is unchanged.

B = actual browser execution; A = genuine HTTP/geometry integration; U = isolated regression. Final execution evidence is in [browser verification](evidence/browser-verification.json).

| Original parameter | M3 location / range | Verification |
|---|---|---|
| Model width | Customize → Width, 10–1000 mm | B/A/U; exact 160.125 saved |
| Relief height | Customize → Relief depth, .5–100 mm | B/A/U; 9.25 saved |
| Base thickness | Advanced → Backing thickness, .5–50 mm | B/A/U; 4.5 saved |
| Frame | Advanced → Border frame, 0–50 mm | B/A/U; 2.5 saved |
| Depth model | Advanced → Model, all three adapters retained | B/U; restricted disabled; same-model regression and browser retest pass |
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
| Resolution | Export quality/dialog: 512/1024/2048 | B/A/U; actual resource refusal |
| Decimation | Export → Triangle reduction, 0–.95 | B/A/U; .15 reduced OBJ downloaded and reimported |
| Format | Export → STL/OBJ | B/A/U; browser downloads reimported |

| Added/preserved workflow | Implementation and actual qualification |
|---|---|
| Upload/default model | Tiger and face uploaded/inferred B/A. Drag/drop implemented; final gesture P |
| One prominent 3D canvas | Genuine GLB B. Orbit controls retained; fit/reset/top/zoom B |
| Photo/depth views | Photo/depth/3D switching B |
| Read-only comparison | B/A/U; import/source observed disabled during comparison |
| Automatic isolation | Existing cutout/optional U2NETP/GrabCut. Genuine alpha A/U; all three isolation methods B |
| Mask keep/remove/rectangle | Remove/undo B. All math/history U; keep/rectangle B |
| Feather/transition/reset/disable | Preserved API U/A; field adjustment/reset/disable B |
| Raise/lower/smooth/flatten | Raise B; all four A/U with exact undo/redo; all UI brushes B |
| Brush radius/strength/level | Visible aligned cursor B; calculations U; radius/strength/level B |
| Undo/redo/reset/shortcuts | Browser undo B; persistence U; keyboard/reset B |
| PNG16/float32 exchange | A/U precision, orientation, version switching; redesigned dialog B |
| Restore original AI | A/U; confirmation B |
| Presets/undo | Portrait B; all four and reversal U; all four/undo B |
| Project names/recent/reload | B/U. library/switch/delete/restore B |
| Recoverable deletion | U; real tiger slow test. No permanent purge; model/cache protected |
| Checkpoints | A/U exact depth/mask, archived histories; browser dialogs B |
| Damaged metadata | Syntax/invalid-type repair and missing-image message U; browser repair B |
| Resource plan / export snapshot | A/U; dialog/download/refusal B |
| Dark/light | Switched B; startup persistence implemented; reload/root persistence B |
| Responsive | Eight actual initial size/theme screenshots B, no horizontal overflow; compact-height fix observed at 1366; all eight final captures B |
| Offline frontend | Local ES modules/system fonts/no new runtime npm dependencies; CSP local-only browser trace B |
| Platform/launcher | Original adapters/native architecture preserved; local real CPU; CI results on PR; GPU/MPS not qualified |

Native drag/drop and right-button pan were not separately automated; picker upload, orbit/scroll and camera buttons passed. Browser heap telemetry was unavailable.
Original AI depth stayed byte-identical throughout both real integration cases.
