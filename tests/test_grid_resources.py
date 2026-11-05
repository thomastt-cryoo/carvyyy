from __future__ import annotations

import numpy as np
import pytest

from app import heightmap, meshing
from app.grid import plan_grid
from app.resources import export_plan
from app.schemas import ReliefParams


@pytest.mark.parametrize("shape", [(300, 451), (451, 300), (2, 2000), (2000, 2)])
@pytest.mark.parametrize("frame", [0, 10, 50])
def test_source_aspect_and_frame_dimensions_are_exact(shape, frame):
    p = ReliefParams(depth_model="da2-small", model_width_mm=100, border_frame_mm=frame)
    raw = np.zeros(shape, dtype=np.float32)
    h = heightmap.compute_heightmap(raw, raw, p, 128, image_shape=shape)
    assert max(h.shape) <= 128
    assert min(h.shape) >= 2
    mesh = meshing.build_export_mesh(h, p, image_shape=shape)
    assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume > 0
    assert mesh.extents[:2] == pytest.approx(
        [100 + 2 * frame, 100 * shape[0] / shape[1] + 2 * frame]
    )
    if frame:
        xs, ys = plan_grid(shape, p, 128).axes()
        assert np.min(abs(xs - frame)) < 1e-10
        assert np.min(abs(xs - frame - 100)) < 1e-10
        assert np.min(abs(ys - frame)) < 1e-10


def test_resource_guard_rejects_without_allocating_large_arrays():
    p = ReliefParams(resolution=2048)
    plan = export_plan((4000, 6000), p, available_bytes=100 * 1024**2)
    assert not plan.allowed
    assert plan.grid.columns == 2048
    assert plan.memory_bytes_estimate > plan.memory_budget_bytes
    assert "lower resolution" in plan.message
    assert plan.output_bytes_estimate == 84 + plan.triangles * 50


def test_decimation_changes_size_estimate_but_not_initial_memory_requirement():
    full = export_plan((400, 600), ReliefParams(resolution=512), available_bytes=8 * 1024**3)
    decimated = export_plan(
        (400, 600), ReliefParams(resolution=512, decimate_ratio=0.8), available_bytes=8 * 1024**3
    )
    assert full.allowed
    assert decimated.output_bytes_estimate < full.output_bytes_estimate
    assert decimated.memory_bytes_estimate >= full.memory_bytes_estimate


def test_nonfinite_heights_are_rejected_before_meshing():
    with pytest.raises(ValueError, match="finite"):
        meshing.build_relief_mesh(np.full((8, 8), np.nan), ReliefParams())
