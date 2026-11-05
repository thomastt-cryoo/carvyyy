"""Measurements of final mesh geometry for the export review."""

from __future__ import annotations

import numpy as np
import trimesh


def surface_report(mesh: trimesh.Trimesh) -> dict:
    """Area-weighted slopes on upward-facing facets, excluding backing and walls."""
    total_xy = steep_xy = 0.0
    steepest = 0.0
    for offset in range(0, len(mesh.faces), 65_536):
        triangles = mesh.vertices[mesh.faces[offset : offset + 65_536]]
        cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
        top = cross[:, 2] > 1e-12
        if not top.any():
            continue
        projected = cross[top, 2]
        angles = np.degrees(np.arctan2(np.hypot(cross[top, 0], cross[top, 1]), projected))
        total_xy += float(projected.sum())
        steep_xy += float(projected[angles >= 60].sum())
        steepest = max(steepest, float(angles.max()))
    return {
        "max_slope_deg": round(steepest, 1),
        "steep_area_percent": round(100 * steep_xy / total_xy, 2) if total_xy else 0.0,
        "thickness_mm": round(float(mesh.extents[2]), 3),
    }
