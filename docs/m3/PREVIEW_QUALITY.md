# Visible settings and progressive preview

User-requested M3 follow-up, 2026-11-05. This supersedes the upstream 256-only
workspace preview limit; the API still defaults to 256 for existing callers.

The customization panel stays open. Size, depth shaping, surface refinement,
model, background and sculpt settings are expanded in one scrollable panel.
Customize / Background / Sculpt navigate within that panel. The panel-hide toggle
and advanced-settings disclosure are removed. On narrow screens the panel sits
below the preview.

The 3D toolbar always shows the rendered preview resolution, selected export
resolution, **Inspect export**, and light direction, elevation and brightness.
Lighting is saved locally and changes presentation only.

Parameter adjustments request a 256-sample preview after a short debounce and
a 512-sample preview after 800 ms without another adjustment. Opening a project
uses 512. Autosave does not cancel that refinement. Superseded requests and GLTF
loads cannot replace the current project's view.

**Inspect export** creates or reuses the matching export, then displays a GLB
serialized from the same validated mesh as the STL/OBJ, including triangle
reduction. Its label reports the export resolution and actual triangle count.
Return to live preview resumes editing; changing settings invalidates inspection.
The original-AI comparison disables inspection. Existing export memory guards
apply, with an explicit lower-quality choice when refused.

## Verification

- 183 fast Python regressions passed; four slow tests deselected. Five targeted
  endpoint/export tests also passed after adding the simplified-mesh assertions.
- Eight frontend tests, Ruff lint/format and JS syntax passed.
- One fresh genuine tiger inference/checkpoint/STL+OBJ smoke passed (94.13 s).
- Real browser inspection: tiger 1024, .15 reduction, **1,789,532 triangles**.
  The downloaded OBJ and displayed GLB are both watertight with matching
  150 × 150 × 11 mm bounds. [Geometry measurements](evidence/preview-quality/geometry.json).
- Browser inspection also displayed the 512 export with 449,116 triangles.
  Return-to-live and automatic invalidation after a smoothing change worked.
- Server access logs confirmed successful 256 followed by 512 preview requests
  after a slider adjustment. The toolbar settled at 512 and retained export quality.
- Light direction, elevation and brightness respond without rebuilding geometry;
  lighting survives reload. The final view restores 315° / 35° / 1.8.
- All three settings sections remain displayed without closed disclosures.
  [Three viewport checks](evidence/preview-quality/responsive.json) show visible
  controls/settings and no horizontal overflow. Dark and light themes inspected.
- A 2048 tiger export was refused at approximately 5194 MB against this machine's
  1536 MB safety budget; no quiet resolution substitution occurred.
- Final page console: zero warnings/errors. The user's tiger workspace remains
  open in dark mode; its shaping settings were preserved.

## Actual captures

[Final dark workspace](evidence/preview-quality/workspace-dark.png) ·
[1024 export inspection](evidence/preview-quality/export-inspection-1024.png) ·
[Portrait preview](evidence/preview-quality/portrait-512.png) ·
[1024-wide controls](evidence/preview-quality/controls-1024.png) ·
[760-wide stacked settings](evidence/preview-quality/controls-760.png) ·
[Expanded sculpt in light mode](evidence/preview-quality/expanded-sculpt-light.png) ·
[2048 resource refusal](evidence/preview-quality/memory-limit-2048.png).

Higher sampling preserves available detail; it cannot reconstruct missing anatomy
or remove brightness-derived grooves. Full export inspection takes more browser
memory and may be slower. The GLB adds local disk use beside each export. Browser
heap telemetry and actual cutting were not measured. No new runtime dependency,
model inference on parameter changes, cloud processing or M4 work was introduced.
