"""M4 coverage for failure recovery, storage boundaries and machining review."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import cnc, depth, editing, jobs, meshing, pipeline, projects_api, sessions, storage
from app.config import settings
from app.main import ProjectFileResponse, app
from tests.conftest import make_solid_image_bytes
from tests.test_editing import document as document

client = TestClient(app)


def test_reviewed_purge_removes_only_selected_deleted_project(document, tmp_path, monkeypatch):
    sid, _, _, original = document
    monkeypatch.setattr(settings, "models_dir", tmp_path / "models")
    settings.models_dir.mkdir()
    weight = settings.models_dir / "weight.bin"
    weight.write_bytes(b"protected")
    other = sessions.create_session(make_solid_image_bytes(), "other.png").session_id
    assert client.post(f"/api/storage/purge/{sid}", json={}).status_code == 409
    assert client.delete(f"/api/projects/{sid}").status_code == 200
    assert client.delete(f"/api/projects/{other}").status_code == 200
    summary = client.get("/api/storage").json()
    assert summary["deleted_project_bytes"] > len(original)
    review = client.post(f"/api/storage/purge/{sid}", json={}).json()
    assert review["files"] > 0
    trash = storage.recovery_root() / sid
    (trash / "changed.txt").write_text("new file")
    assert (
        client.post(f"/api/storage/purge/{sid}", json={"expected_plan": review["plan"]}).status_code
        == 409
    )
    review = client.post(f"/api/storage/purge/{sid}", json={}).json()
    result = client.post(f"/api/storage/purge/{sid}", json={"expected_plan": review["plan"]})
    assert result.json()["pending"] is False
    assert result.json()["removed_bytes"] == review["bytes"]
    assert not trash.exists()
    assert client.post(f"/api/projects/{other}/restore").status_code == 200
    assert weight.read_bytes() == b"protected"


def test_interrupted_purge_can_resume_without_exposing_partial_project(document, monkeypatch):
    sid, _, _, _ = document
    assert client.delete(f"/api/projects/{sid}").status_code == 200
    review = storage.purge_project(sid, pending=False)
    original_unlink = Path.unlink

    def locked_file(path, *args, **kwargs):
        if "project-purge" in path.parts and path.name == "source.png":
            raise PermissionError("simulated in-use file")
        return original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", locked_file)
        outcome = storage.purge_project(sid, pending=False, expected_plan=review["plan"])
    assert outcome["pending"] is True
    assert client.post(f"/api/projects/{sid}/restore").status_code == 400
    assert client.get("/api/storage").json()["pending_purges"][0]["id"] == sid
    review = storage.purge_project(sid, pending=True)
    assert not storage.purge_project(sid, pending=True, expected_plan=review["plan"])["pending"]
    assert client.get("/api/storage").json()["pending_purges"] == []


@pytest.mark.asyncio
async def test_project_file_lease_survives_until_response_completes(document):
    sid, _, _, _ = document
    response = ProjectFileResponse(sid, ("source.png",), media_type="image/png")
    bodies = []

    async def send(event):
        assert storage.is_leased(sid)
        if event["type"] == "http.response.start":
            with pytest.raises(editing.RevisionConflict, match="still processing"):
                projects_api.delete_project(sid)
        elif event["type"] == "http.response.body":
            bodies.append(event["body"])

    await response({"type": "http", "method": "GET", "headers": []}, None, send)
    assert b"".join(bodies) == sessions.session_file(sid, "source.png").read_bytes()
    assert not storage.is_leased(sid)


def test_linked_session_and_recovery_children_are_refused(document, tmp_path):
    sid, _, _, _ = document
    outside = tmp_path / "outside"
    outside.mkdir()
    precious = outside / "params.json"
    precious.write_text("unchanged")
    fake = "a" * 32
    try:
        (settings.sessions_dir / fake).symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("This Windows account cannot create symlinks")
    assert client.get(f"/api/sessions/{fake}/params").status_code == 404
    assert client.put(f"/api/sessions/{fake}/params", json={}).status_code == 404
    assert client.delete(f"/api/projects/{sid}").status_code == 200
    recovery = storage.recovery_root() / sid
    (recovery / "linked").symlink_to(outside, target_is_directory=True)
    assert client.post(f"/api/storage/purge/{sid}", json={}).status_code == 409
    assert (recovery / "source.png").exists() and precious.read_text() == "unchanged"


def test_disposable_working_cache_damage_replays_saved_gestures(document):
    sid, params, _, original = document
    editing.add_stroke(sid, params.depth_model, editing.Stroke(tool="raise", points=[(0.5, 0.5)]))
    expected, _, state = editing.working_inputs(sid, params.depth_model)
    root = sessions.session_dir(sid) / "editing"
    (root / "working-cache.json").write_text("{bad")
    np.testing.assert_array_equal(editing.working_inputs(sid, params.depth_model)[0], expected)
    (root / "working-depth.npy").write_bytes(b"bad depth")
    np.testing.assert_array_equal(editing.working_inputs(sid, params.depth_model)[0], expected)
    assert editing.read_state(sid)["revision"] == state["revision"]
    assert depth.session_depth_path(sid, params.depth_model).read_bytes() == original


def test_refinement_is_reversible_and_preserves_source_and_scale(document):
    sid, params, raw, _ = document
    params = params.model_copy(update={"model_width_mm": 20})
    path = depth.session_depth_path(sid, params.depth_model)
    raw[:, 32] = 0.75
    np.save(path, raw)
    original = path.read_bytes()
    before, shape = pipeline.render_heightmap(sid, params, 256)
    res = client.put(f"/api/sessions/{sid}/editor", json={"cnc_refinement": True})
    assert res.json()["cnc_refinement"] is True
    after, _ = pipeline.render_heightmap(sid, params, 256)
    assert after.max() < before.max()
    assert np.max(np.abs(after - before)) * params.relief_height_mm <= 0.18001
    mesh = meshing.build_relief_mesh(after, params, image_shape=shape)
    assert mesh.is_watertight
    np.testing.assert_allclose(mesh.extents[:2], [20, 20])
    assert (
        client.put(f"/api/sessions/{sid}/editor", json={"cnc_refinement": False}).status_code == 200
    )
    np.testing.assert_array_equal(pipeline.render_heightmap(sid, params, 256)[0], before)
    assert path.read_bytes() == original


def test_surface_report_excludes_vertical_walls_and_backing(document):
    _, params, _, _ = document
    params = params.model_copy(update={"model_width_mm": 3, "relief_height_mm": 8})
    flat = meshing.build_relief_mesh(np.full((2, 2), 0.5), params)
    ramp = meshing.build_relief_mesh(np.array([[0, 1], [0, 1]]), params)
    assert cnc.surface_report(flat) == {
        "max_slope_deg": 0.0,
        "steep_area_percent": 0.0,
        "thickness_mm": 7.0,
    }
    assert cnc.surface_report(ramp)["steep_area_percent"] == 100.0
    assert cnc.surface_report(ramp)["max_slope_deg"] == 69.4


def test_aggressive_simplification_stays_inside_stock(document):
    # A high reduction on a narrow ridge can overshoot the original top.
    _, params, _, _ = document
    y, x = np.mgrid[-1:1:128j, -1:1:128j]
    height = np.clip((np.sin(x * 23) + np.cos(y * 31)) * 0.45 + 0.5, 0, 1)
    params = params.model_copy(update={"decimate_ratio": 0.95})
    original = meshing.build_relief_mesh(height, params)
    simplified = meshing.build_export_mesh(height, params)
    assert simplified.is_watertight and simplified.is_winding_consistent
    assert np.all(simplified.bounds[0] >= original.bounds[0])
    assert np.all(simplified.bounds[1] <= original.bounds[1])
    np.testing.assert_allclose(simplified.bounds[:, :2], original.bounds[:, :2], atol=0.001)


def test_inspection_cap_keeps_original_download_available(document, monkeypatch):
    sid, params, _, _ = document
    monkeypatch.setattr(jobs, "MAX_INSPECTION_TRIANGLES", 1)
    monkeypatch.setattr(jobs, "_jobs", {})
    job = jobs.ExportJob(job_id="a" * 32, session_id=sid)
    jobs._jobs[job.job_id] = job
    jobs._run_export(job, params.model_copy(update={"resolution": 512}))
    result = client.get(f"/api/jobs/{job.job_id}").json()
    assert result["status"] == "ready" and result["preview_url"] is None
    assert "inspection limit" in result["inspection_note"]
    assert result["surface"]["steep_area_percent"] == 0.0
    assert client.get(result["download_url"]).status_code == 200
    assert client.get(f"/api/jobs/{job.job_id}/preview").status_code == 404


@pytest.mark.parametrize(
    "format,size,expected",
    [
        ("JPEG", (8, 12), (12, 8)),
        ("PNG", (2, 2), (2, 2)),
        ("WEBP", (128, 4), (128, 4)),
        ("HEIF", (64, 96), (64, 96)),
        ("PNG", (32, 1024), (32, 1024)),
    ],
)
def test_real_encoded_inputs_keep_corrected_dimensions(document, format, size, expected):
    photo = Image.new("RGB", size, (50, 90, 120))
    payload = io.BytesIO()
    options = {}
    if format == "JPEG":
        exif = photo.getexif()
        exif[274] = 6
        options["exif"] = exif
    photo.save(payload, format=format, **options)
    info = sessions.create_session(payload.getvalue(), "photo." + format.lower())
    assert (info.width, info.height) == expected
    assert (
        sessions.session_file(info.session_id, "original-upload.bin").read_bytes()
        == payload.getvalue()
    )


def test_failed_image_write_does_not_publish_partial_project(document, monkeypatch):
    payload = make_solid_image_bytes()
    before = set(settings.sessions_dir.iterdir())

    def full_disk(*args, **kwargs):
        raise OSError("simulated full disk")

    monkeypatch.setattr(Image.Image, "save", full_disk)
    with pytest.raises(sessions.InvalidImageError, match="disk space"):
        sessions.create_session(payload, "photo.png")
    assert set(settings.sessions_dir.iterdir()) == before
