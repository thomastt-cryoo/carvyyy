"""Project-wide history must survive mixed edits, reopening and failed writes."""

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import editing, history, sessions
from app.main import app
from tests.test_editing import document as document

client = TestClient(app)


def move(sid, action):
    token = history.status(sid)["token"]
    response = client.post(
        f"/api/projects/{sid}/history", json={"action": action, "expected_token": token}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_mixed_edits_undo_to_original_and_redo_after_reopen(document):
    sid, params, raw, original = document
    baseline = editing.working_inputs(sid, params.depth_model)
    sessions.write_params(sid, params.model_copy(update={"model_width_mm": 180}))
    editing.add_stroke(
        sid, params.depth_model, editing.Stroke(tool="raise", points=[(0.5, 0.5)], strength=0.1)
    )
    editing.add_stroke(
        sid,
        params.depth_model,
        editing.Stroke(channel="mask", tool="remove", points=[(0.2, 0.2)], strength=1),
    )
    editing.update_settings(sid, editing.EditorSettings(mask_enabled=True, sculpt_strength=0.4))
    final_params = sessions.read_params(sid)
    final_depth, final_mask, _ = editing.working_inputs(sid, params.depth_model)
    revision = editing.read_state(sid)["revision"]
    for _ in range(4):
        move(sid, "undo")
    assert not history.status(sid)["undo"] and history.status(sid)["redo"]
    assert sessions.read_params(sid) == params
    current = editing.working_inputs(sid, params.depth_model)
    np.testing.assert_array_equal(current[0], baseline[0])
    np.testing.assert_array_equal(current[1], baseline[1])
    assert editing.read_state(sid)["revision"] > revision
    # A fresh read uses only the saved index and immutable editing files.
    assert client.get(f"/api/sessions/{sid}/editor").json()["project_history"]["redo"]
    for _ in range(4):
        move(sid, "redo")
    assert sessions.read_params(sid) == final_params
    current = editing.working_inputs(sid, params.depth_model)
    np.testing.assert_array_equal(current[0], final_depth)
    np.testing.assert_array_equal(current[1], final_mask)
    assert not history.status(sid)["redo"]
    assert (
        sessions.session_dir(sid) / f"raw_depth_{params.depth_model}.npy"
    ).read_bytes() == original


def test_preset_is_one_step_and_new_edit_discards_redo(document):
    sid, params, _, _ = document
    response = client.post(f"/api/projects/{sid}/preset", json={"name": "Portrait"})
    assert response.status_code == 200
    assert history._index(sid)["cursor"] == 1
    move(sid, "undo")
    assert sessions.read_params(sid) == params
    assert editing.read_state(sid)["sculpt_strength"] == 0
    move(sid, "redo")
    assert editing.read_state(sid)["sculpt_strength"] == 0.25
    move(sid, "undo")
    sessions.write_params(sid, params.model_copy(update={"gamma": 1.4}))
    assert not history.status(sid)["redo"]
    assert sessions.read_params(sid).gamma == 1.4


def test_noop_and_stale_undo_do_not_change_saved_work(document):
    sid, params, _, _ = document
    sessions.write_params(sid, params)
    assert not history.status(sid)["undo"]
    token = history.status(sid)["token"]
    sessions.write_params(sid, params.model_copy(update={"smoothing": 3}))
    result = client.post(
        f"/api/projects/{sid}/history", json={"action": "undo", "expected_token": token}
    )
    assert result.status_code == 409
    assert sessions.read_params(sid).smoothing == 3


def test_interrupted_write_recovers_before_preview_read(document):
    sid, params, _, _ = document
    before = history._capture(sid)
    history._write(history._path(sid, "pending.json"), {"id": "interrupted", "before": before})
    sessions.atomic_json(
        sessions.params_path(sid), params.model_copy(update={"model_width_mm": 400}).model_dump()
    )
    assert sessions.read_params(sid) == params
    assert not history._path(sid, "pending.json").exists()


def test_history_write_failure_preserves_settings_and_all_prior_undo(document, monkeypatch):
    sid, params, _, _ = document
    sessions.write_params(sid, params.model_copy(update={"gamma": 1.3}))
    saved = sessions.read_params(sid)
    token = history.status(sid)["token"]
    original = history._write

    def fail_index(path, value):
        if path.name == "index.json":
            raise OSError("Disk unavailable")
        original(path, value)

    with monkeypatch.context() as patch:
        patch.setattr(history, "_write", fail_index)
        with pytest.raises(OSError, match="Disk unavailable"):
            sessions.write_params(sid, params.model_copy(update={"gamma": 1.8}))
    assert sessions.read_params(sid) == saved
    assert history.status(sid)["token"] == token
    move(sid, "undo")
    assert sessions.read_params(sid) == params


def test_brush_history_entries_store_new_operations_without_duplicating_prior_strokes(document):
    sid, params, _, _ = document
    for _ in range(20):
        editing.add_stroke(
            sid,
            params.depth_model,
            editing.Stroke(tool="raise", points=[(0.5, 0.5)], strength=0.01),
        )
    index = history._index(sid)
    last = history._path(sid, index["entries"][-1] + ".json")
    assert last.stat().st_size < 2000
    assert len(json.loads(last.read_text())) > 0


def test_import_and_source_changes_are_reversible_without_rewriting_original_arrays(document):
    sid, params, raw, original = document
    imported = np.linspace(0, 1, raw.size, dtype=np.float32).reshape(raw.shape)
    editing.import_depth(sid, editing.encode_depth(imported, "npy"), "custom.npy")
    working = editing.working_inputs(sid, params.depth_model)[0].copy()
    move(sid, "undo")
    assert editing.read_state(sid)["depth_source"] == "ai"
    np.testing.assert_array_equal(editing.working_inputs(sid, params.depth_model)[0], raw)
    move(sid, "redo")
    np.testing.assert_array_equal(editing.working_inputs(sid, params.depth_model)[0], working)
    editing.update_settings(sid, editing.EditorSettings(depth_source="ai"))
    move(sid, "undo")
    assert editing.read_state(sid)["depth_source"] == "imported"
