"""M1 added checks; known defects remain visible as strict expected failures."""

from __future__ import annotations

import io

import numpy as np
import pytest
import trimesh

from app import heightmap, meshing
from app.schemas import ReliefParams


@pytest.mark.parametrize("shape", [(2, 200), (200, 2), (8, 8)])
@pytest.mark.parametrize("level", [0.0, 1.0])
@pytest.mark.parametrize("fmt", ["stl", "obj"])
def test_flat_and_extreme_mesh_roundtrips(shape, level, fmt) -> None:
    params = ReliefParams(
        depth_model="da2-small", model_width_mm=100, base_thickness_mm=3, relief_height_mm=8
    )
    mesh = meshing.build_export_mesh(np.full(shape, level, dtype=np.float32), params)
    result = trimesh.load(io.BytesIO(meshing.export_bytes(mesh, fmt)), file_type=fmt)
    assert result.is_watertight
    assert result.is_winding_consistent
    assert result.volume > 0
    assert result.extents == pytest.approx([100, 100 * shape[0] / shape[1], 3 + level * 8])
    # Every base triangle faces down and lies on one plane; walls face out.
    bottom = np.all(np.isclose(result.triangles[:, :, 2], 0), axis=1)
    assert bottom.any()
    assert np.all(result.face_normals[bottom, 2] < -0.99)


def test_decimation_preserves_outward_solid_and_dimensions() -> None:
    y, x = np.mgrid[0:80, 0:120]
    h = ((np.sin(x / 12) * np.cos(y / 15) + 1) / 2).astype(np.float32)
    params = ReliefParams(depth_model="da2-small", decimate_ratio=0.8)
    full = meshing.build_relief_mesh(h, params)
    reduced = meshing.build_export_mesh(h, params)
    assert reduced.is_watertight and reduced.is_winding_consistent
    assert reduced.volume > 0
    assert len(reduced.faces) < len(full.faces) * 0.25
    assert reduced.extents == pytest.approx(full.extents, abs=0.1)


@pytest.mark.xfail(strict=True, reason="M1-D01: extreme aspect ratio resizes a side to one vertex")
def test_extremely_wide_photo_can_generate_both_previews() -> None:
    depth = np.zeros((2, 2000), dtype=np.float32)
    params = ReliefParams(depth_model="da2-small")
    h = heightmap.compute_heightmap(depth, depth, params, target_long_side=256)
    heightmap.hillshade(h, params.total_width_mm, params.relief_height_mm)
    assert meshing.build_relief_mesh(h, params).is_watertight


@pytest.mark.xfail(strict=True, reason="M1-D02: frame padding is added after preview grid limit")
def test_border_frame_respects_preview_resource_limit() -> None:
    depth = np.zeros((32, 32), dtype=np.float32)
    params = ReliefParams(depth_model="da2-small", model_width_mm=10, border_frame_mm=50)
    h = heightmap.compute_heightmap(depth, depth, params, target_long_side=256)
    assert max(h.shape) <= 256
