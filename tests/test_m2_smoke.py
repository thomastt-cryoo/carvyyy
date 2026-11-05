"""Explicit real CPU inference/segmentation/edit/export smoke for platform CI."""

import io
from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image

from app import depth, editing, meshing, pipeline, segmentation, sessions
from app.config import settings
from app.schemas import ReliefParams


@pytest.mark.slow
def test_real_cpu_models_edit_and_export(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "sessions_dir", tmp_path / "sessions")
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "cache")
    settings.sessions_dir.mkdir()
    settings.cache_dir.mkdir()
    photo = Image.open(Path(__file__).parents[1] / "docs/m1/evidence/inputs/object.png")
    photo.thumbnail((256, 256))
    content = io.BytesIO()
    photo.save(content, "PNG")
    info = sessions.create_session(content.getvalue(), "coffee-smoke.png")
    sid = info.session_id
    params = ReliefParams(depth_model="da2-small", resolution=512)
    sessions.write_params(sid, params)
    raw = depth.run_inference(sid, params.depth_model)
    assert np.isfinite(raw).all() and 0 <= raw.min() <= raw.max() <= 1
    original = depth.session_depth_path(sid, params.depth_model).read_bytes()
    assert segmentation.status()["available"], "Install the optional verified test model first"
    result = editing.automatic_mask(sid, params.depth_model, method="u2netp")
    assert "U2NETP" in result["method"] and 0.05 < result["foreground_fraction"] < 0.95
    # Test crop-to-photo projection, including exact zero outside the selected region.
    cropped = segmentation.predict(photo, [0.1, 0.1, 0.9, 0.9])
    assert cropped.shape == (photo.height, photo.width)
    assert np.all(cropped[: int(photo.height * 0.1)] == 0) and cropped.max() > 0.9
    editing.add_stroke(
        sid, params.depth_model, editing.Stroke(tool="lower", points=[(0.5, 0.5)], strength=0.02)
    )
    working = editing.working_inputs(sid, params.depth_model)[0]
    assert not np.array_equal(working, raw)
    imported = editing.encode_depth(working, "png16")
    editing.import_depth(sid, imported, "corrected.png")
    assert depth.session_depth_path(sid, params.depth_model).read_bytes() == original
    h, shape = pipeline.render_heightmap(sid, params, 512)
    mesh = meshing.build_export_mesh(h, params, image_shape=shape)
    for format in ["stl", "obj"]:
        loaded = trimesh.load(
            io.BytesIO(meshing.export_bytes(mesh, format)), file_type=format, force="mesh"
        )
        assert loaded.is_watertight and loaded.is_winding_consistent and loaded.volume > 0
        assert np.isfinite(loaded.vertices).all()
