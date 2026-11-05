"""M3 durable project workflows. Synthetic depth isolates persistence, not AI quality."""

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import depth, editing, jobs, projects_api, sessions, storage
from app.config import settings
from app.main import app
from tests.conftest import make_solid_image_bytes
from tests.test_editing import document as document

client = TestClient(app)


def test_library_rename_recoverable_delete_preserves_models_and_other_work(
    document, tmp_path, monkeypatch
):
    sid, params, raw, original = document
    monkeypatch.setattr(settings, "models_dir", tmp_path / "models")
    settings.models_dir.mkdir()
    protected = settings.models_dir / "weights.bin"
    protected.write_bytes(b"keep")
    another = sessions.create_session(make_solid_image_bytes(), "another.png")
    assert len(client.get("/api/projects").json()["projects"]) == 2
    response = client.patch(f"/api/projects/{sid}", json={"name": "  Tiger   study  "})
    assert response.json()["name"] == "Tiger study"
    assert client.patch(f"/api/projects/{sid}", json={"name": "   "}).status_code == 422
    assert client.delete(f"/api/projects/{sid}").json()["recoverable"]
    assert client.get(f"/api/projects/{sid}").status_code == 404
    assert protected.read_bytes() == b"keep" and sessions.session_dir(another.session_id).exists()
    restored = client.post(f"/api/projects/{sid}/restore").json()
    assert restored["name"] == "Tiger study"
    assert depth.session_depth_path(sid, params.depth_model).read_bytes() == original
    np.testing.assert_array_equal(editing.working_inputs(sid, params.depth_model)[0], raw)


def test_busy_project_cannot_be_deleted(document, monkeypatch):
    sid, _, _, _ = document
    with storage.session_lease(sid):
        assert client.delete(f"/api/projects/{sid}").status_code == 409
    monkeypatch.setattr(jobs, "_jobs", {"queued": jobs.ExportJob(job_id="queued", session_id=sid)})
    assert client.delete(f"/api/projects/{sid}").status_code == 409
    assert sessions.session_dir(sid).exists()


@pytest.mark.parametrize("name", ["Portrait", "Pet", "Object", "Ornament"])
def test_presets_and_undo_preserve_painted_sources_and_physical_changes(document, name):
    sid, params, _, original = document
    editing.add_stroke(sid, params.depth_model, editing.Stroke(tool="raise", points=[(0.5, 0.5)]))
    editing.add_stroke(
        sid, params.depth_model, editing.Stroke(channel="mask", tool="remove", points=[(0.1, 0.1)])
    )
    working, mask, before = editing.working_inputs(sid, params.depth_model)
    response = client.post(
        f"/api/projects/{sid}/preset", json={"name": name, "expected_revision": before["revision"]}
    )
    assert response.status_code == 200, response.text
    after, after_mask, state = editing.working_inputs(sid, params.depth_model)
    np.testing.assert_array_equal(after, working)
    np.testing.assert_array_equal(after_mask, mask)
    assert state["histories"] == before["histories"] and state["depth_source"] == "ai"
    changed = sessions.read_params(sid).model_copy(update={"model_width_mm": 187.25})
    sessions.write_params(sid, changed)
    undo = client.post(f"/api/projects/{sid}/undo-preset")
    assert undo.status_code == 200
    restored = sessions.read_params(sid)
    assert restored.model_width_mm == 187.25 and restored.gamma == params.gamma
    assert depth.session_depth_path(sid, params.depth_model).read_bytes() == original


def test_stale_preset_cannot_overwrite_new_settings(document):
    sid, params, _, _ = document
    editing.update_settings(sid, editing.EditorSettings(texture_guard=0.4))
    response = client.post(
        f"/api/projects/{sid}/preset", json={"name": "Portrait", "expected_revision": 0}
    )
    assert response.status_code == 409
    assert sessions.read_params(sid) == params


@pytest.mark.parametrize("filename", ["meta.json", "project.json", "params.json"])
def test_damaged_metadata_is_visible_and_repair_keeps_backups_and_ai(document, filename):
    sid, params, _, original = document
    path = sessions.session_dir(sid) / filename
    path.write_text("{interrupted", encoding="utf-8")
    record = client.get(f"/api/projects/{sid}").json()
    assert record["issues"]
    result = client.post(f"/api/projects/{sid}/repair", json={"reset_settings": True})
    assert result.status_code == 200, result.text
    assert result.json()["issues"] == []
    assert any(
        p.read_text() == "{interrupted"
        for p in sessions.session_dir(sid).glob(f"recovery/*/{filename}")
    )
    assert depth.session_depth_path(sid, params.depth_model).read_bytes() == original


def test_checkpoint_preserves_result_archives_old_history_and_recovers_later_work(
    document, monkeypatch
):
    sid, params, _, original = document
    monkeypatch.setattr(editing, "MAX_OPERATIONS", 2)
    for tool in ["raise", "lower"]:
        editing.add_stroke(sid, params.depth_model, editing.Stroke(tool=tool, points=[(0.5, 0.5)]))
    before = editing.working_inputs(sid, params.depth_model)[0].copy()
    response = client.post(f"/api/sessions/{sid}/editor/checkpoint", json={"channel": "depth"})
    assert response.status_code == 200, response.text
    assert response.json()["depth_source"] == "imported"
    np.testing.assert_array_equal(editing.working_inputs(sid, params.depth_model)[0], before)
    editing.add_stroke(sid, params.depth_model, editing.Stroke(tool="raise", points=[(0.5, 0.5)]))
    later = editing.working_inputs(sid, params.depth_model)[0].copy()
    items = client.get(f"/api/sessions/{sid}/editor/checkpoints").json()["items"]
    restore = client.post(
        f"/api/sessions/{sid}/editor/checkpoints/restore", json={"id": items[0]["id"]}
    )
    assert restore.status_code == 200
    np.testing.assert_array_equal(editing.working_inputs(sid, params.depth_model)[0], before)
    archived_later = client.get(f"/api/sessions/{sid}/editor/checkpoints").json()["items"][-1]
    assert (
        client.post(
            f"/api/sessions/{sid}/editor/checkpoints/restore", json={"id": archived_later["id"]}
        ).status_code
        == 200
    )
    np.testing.assert_array_equal(editing.working_inputs(sid, params.depth_model)[0], later)
    assert depth.session_depth_path(sid, params.depth_model).read_bytes() == original


def test_mask_checkpoint_keeps_float_mask_without_changing_depth(document):
    sid, params, raw, _ = document
    editing.add_stroke(
        sid, params.depth_model, editing.Stroke(channel="mask", tool="remove", points=[(0.5, 0.5)])
    )
    before = editing.working_inputs(sid, params.depth_model)[1]
    assert (
        client.post(f"/api/sessions/{sid}/editor/checkpoint", json={"channel": "mask"}).status_code
        == 200
    )
    working, mask, _ = editing.working_inputs(sid, params.depth_model)
    np.testing.assert_array_equal(mask, before)
    np.testing.assert_array_equal(working, raw)


def test_model_missing_upload_still_allows_import_without_implicit_download(document, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No model download/inference is allowed for this import-only workflow")

    monkeypatch.setattr(depth, "start_inference_job", forbidden)
    monkeypatch.setattr(
        projects_api,
        "availability",
        lambda model: {"selectable": False, "setup_reason": "Not installed"},
    )
    photo = make_solid_image_bytes(size=(32, 32))
    assert (
        client.post(
            "/api/projects/upload?model_id=da2-small", files={"image": ("test.png", photo)}
        ).status_code
        == 400
    )
    project = client.post("/api/projects/upload", files={"image": ("test.png", photo)}).json()
    sid = project["id"]
    content = editing.encode_depth(np.full((32, 32), 0.5, np.float32), "png16")
    assert (
        client.post(
            f"/api/sessions/{sid}/depth/import", files={"file": ("corrected.png", content)}
        ).status_code
        == 200
    )
    params = sessions.read_params(sid).model_copy(update={"gamma": 1.7})
    assert client.put(f"/api/sessions/{sid}/params", json=params.model_dump()).status_code == 200


def test_transparent_upload_preserves_original_and_uses_aligned_alpha(document):
    image = Image.new("RGBA", (33, 33), (0, 0, 0, 0))
    image.paste((30, 60, 90, 255), (8, 8, 25, 25))
    output = io.BytesIO()
    image.save(output, "PNG")
    info = sessions.create_session(output.getvalue(), "cutout.png")
    sid = info.session_id
    params = sessions.read_params(document[0])
    sessions.write_params(sid, params)
    np.save(depth.session_depth_path(sid, params.depth_model), np.full((33, 33), 0.5, np.float32))
    root = sessions.session_dir(sid)
    assert (root / "original-upload.bin").read_bytes() == output.getvalue()
    assert Image.open(root / "source.png").getpixel((0, 0)) == (255, 255, 255)
    assert (
        editing.automatic_mask(sid, params.depth_model)["method"] == "Original image transparency"
    )
    mask = editing.working_inputs(sid, params.depth_model)[1]
    assert mask[16, 16] == 1 and mask[0, 0] == 0
    assert Image.open(io.BytesIO(client.get(f"/api/sessions/{sid}/source").content)).mode == "RGBA"


def test_project_ids_and_external_links_cannot_escape_storage(document, tmp_path):
    assert client.get("/api/projects/not-a-project").status_code == 404
    assert client.post("/api/projects/invalid/restore").status_code == 404
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep")
    link = settings.sessions_dir / ("c" * 32)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("This account cannot create directory symlinks")
    assert client.delete(f"/api/projects/{link.name}").status_code == 404
    assert (outside / "precious.txt").read_text() == "keep"
