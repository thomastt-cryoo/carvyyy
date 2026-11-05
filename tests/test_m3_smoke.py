"""Actual local Small inference and new project workflow on the supplied tiger."""

import io
import time
from pathlib import Path

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient

from app import depth, editing, sessions
from app.config import settings
from app.main import app


@pytest.mark.slow
def test_genuine_tiger_project_checkpoint_and_exports(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "sessions_dir", tmp_path / "sessions")
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "cache")
    settings.sessions_dir.mkdir()
    settings.cache_dir.mkdir()
    client = TestClient(app)
    photo = Path(__file__).parents[1] / "docs/m3/evidence/inputs/tiger.png"
    created = client.post(
        "/api/projects/upload", files={"image": ("Tiger.png", photo.read_bytes())}
    )
    assert created.status_code == 200
    sid = created.json()["id"]
    raw = depth.run_inference(sid, "da2-small")
    assert np.isfinite(raw).all() and raw.shape == (1024, 1024)
    sessions.write_status(sid, model_id="da2-small", status="ready")
    original = depth.session_depth_path(sid, "da2-small").read_bytes()
    mask = client.post(f"/api/sessions/{sid}/editor/automatic-mask", json={"method": "auto"})
    assert mask.json()["segmentation"]["method"] == "Original image transparency"
    assert client.patch(f"/api/projects/{sid}", json={"name": "Tiger study"}).status_code == 200
    assert client.post(f"/api/projects/{sid}/preset", json={"name": "Ornament"}).status_code == 200
    assert (
        client.post(
            f"/api/sessions/{sid}/editor/stroke",
            json={"tool": "raise", "points": [[0.5, 0.5]], "strength": 0.04},
        ).status_code
        == 200
    )
    working = editing.working_inputs(sid, "da2-small")[0]
    assert (
        client.post(f"/api/sessions/{sid}/editor/checkpoint", json={"channel": "depth"}).status_code
        == 200
    )
    np.testing.assert_array_equal(editing.working_inputs(sid, "da2-small")[0], working)
    for format in ["stl", "obj"]:
        params = sessions.read_params(sid).model_copy(
            update={"resolution": 512, "output_format": format}
        )
        response = client.post(f"/api/sessions/{sid}/export", json=params.model_dump())
        assert response.status_code == 200
        job = response.json()["job_id"]
        started = time.monotonic()
        while time.monotonic() - started < 180:
            status = client.get(f"/api/jobs/{job}").json()
            if status["status"] != "processing":
                break
            time.sleep(0.05)
        assert status["status"] == "ready", status
        content = client.get(status["download_url"]).content
        mesh = trimesh.load(io.BytesIO(content), file_type=format, force="mesh")
        assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume > 0
        np.testing.assert_allclose(mesh.extents[:2], [150, 150], atol=0.001)
    assert depth.session_depth_path(sid, "da2-small").read_bytes() == original
    assert client.delete(f"/api/projects/{sid}").status_code == 200
    assert client.post(f"/api/projects/{sid}/restore").json()["name"] == "Tiger study"
