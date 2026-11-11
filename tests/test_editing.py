"""Isolated M2 document tests; synthetic arrays test math, not AI quality."""

from __future__ import annotations

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import depth, editing, jobs, meshing, pipeline, quality, segmentation, sessions
from app.config import settings
from app.main import app
from app.schemas import ReliefParams
from tests.conftest import make_solid_image_bytes


@pytest.fixture
def document(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "sessions_dir", tmp_path / "sessions")
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "cache")
    settings.sessions_dir.mkdir()
    settings.cache_dir.mkdir()
    info = sessions.create_session(make_solid_image_bytes(size=(65, 65)), "test.png")
    params = ReliefParams(depth_model="da2-small", smoothing=0, detail_blend=0, gamma=1)
    sessions.write_params(info.session_id, params)
    raw = np.full((65, 65), 0.4, dtype=np.float32)
    path = depth.session_depth_path(info.session_id, "da2-small")
    np.save(path, raw)

    def forbidden(*args, **kwargs):
        raise AssertionError("Editing and previews must never rerun inference")

    monkeypatch.setattr(depth, "run_inference", forbidden)
    return info.session_id, params, raw, path.read_bytes()


@pytest.mark.parametrize("tool,expected", [("raise", 0.5), ("lower", 0.3), ("flatten", 0.2)])
def test_brush_predictable_center_and_unchanged_outside(tool, expected):
    raw = np.full((65, 65), 0.4, dtype=np.float32)
    stroke = editing.Stroke(
        tool=tool,
        points=[(0.5, 0.5)],
        radius=0.15,
        strength=1 if tool == "flatten" else 0.1,
        level=0.2,
    )
    changed = editing.apply_stroke(raw, stroke)
    assert changed[32, 32] == pytest.approx(expected)
    assert changed[0, 0] == 0.4
    assert np.all(raw == 0.4)
    assert np.isfinite(changed).all()


def test_smooth_brush_removes_selected_spike_only():
    raw = np.full((65, 65), 0.4, dtype=np.float32)
    raw[32, 32] = 1
    changed = editing.apply_stroke(
        raw, editing.Stroke(tool="smooth", points=[(0.5, 0.5)], radius=0.2, strength=1)
    )
    assert 0.4 < changed[32, 32] < 0.6
    assert changed[0, 0] == 0.4


def test_gesture_is_one_delta_not_repeated_per_pointer_event():
    raw = np.full((65, 65), 0.4, dtype=np.float32)
    sparse = editing.apply_stroke(
        raw, editing.Stroke(tool="raise", points=[(0.2, 0.5), (0.8, 0.5)], strength=0.1, radius=0.1)
    )
    dense = editing.apply_stroke(
        raw,
        editing.Stroke(
            tool="raise",
            points=[(float(x), 0.5) for x in np.linspace(0.2, 0.8, 80)],
            strength=0.1,
            radius=0.1,
        ),
    )
    assert sparse.max() <= 0.500001 and dense.max() <= 0.500001
    np.testing.assert_allclose(sparse, dense, atol=0.002)


def test_history_persists_undo_redo_and_reset_without_touching_ai(document):
    sid, params, raw, original_bytes = document
    editing.add_stroke(
        sid, params.depth_model, editing.Stroke(tool="raise", points=[(0.5, 0.5)], strength=0.1)
    )
    assert editing.working_inputs(sid, params.depth_model)[0][32, 32] == 0.5
    assert editing.public_state(sid, params.depth_model)["depth_undo"]
    editing.history_action(sid, params.depth_model, "depth", "undo")
    np.testing.assert_array_equal(editing.working_inputs(sid, params.depth_model)[0], raw)
    editing.history_action(sid, params.depth_model, "depth", "redo")
    assert editing.working_inputs(sid, params.depth_model)[0][32, 32] == 0.5
    editing.history_action(sid, params.depth_model, "depth", "reset")
    np.testing.assert_array_equal(editing.working_inputs(sid, params.depth_model)[0], raw)
    editing.history_action(sid, params.depth_model, "depth", "undo")
    assert editing.working_inputs(sid, params.depth_model)[0][32, 32] == 0.5
    assert depth.session_depth_path(sid, params.depth_model).read_bytes() == original_bytes


def test_mask_brush_history_and_reload_are_independent(document):
    sid, params, raw, _ = document
    editing.add_stroke(
        sid,
        params.depth_model,
        editing.Stroke(channel="mask", tool="remove", points=[(0.5, 0.5)], radius=0.2, strength=1),
    )
    working, mask, state = editing.working_inputs(sid, params.depth_model)
    assert mask[32, 32] == 0 and mask[0, 0] == 1
    assert state["mask_enabled"]
    np.testing.assert_array_equal(working, raw)
    editing.history_action(sid, params.depth_model, "mask", "undo")
    assert np.all(editing.working_inputs(sid, params.depth_model)[1] == 1)
    editing.history_action(sid, params.depth_model, "mask", "redo")
    assert editing.working_inputs(sid, params.depth_model)[1][32, 32] == 0


def test_journal_limit_rejects_new_stroke_without_losing_saved_work(document, monkeypatch):
    sid, params, _, _ = document
    editing.add_stroke(sid, params.depth_model, editing.Stroke(tool="raise", points=[(0.5, 0.5)]))
    before = editing.read_state(sid)
    monkeypatch.setattr(editing, "MAX_DOCUMENT_BYTES", 4000)
    with pytest.raises(editing.EditingError, match="safe size limit"):
        editing.add_stroke(
            sid, params.depth_model, editing.Stroke(tool="lower", points=[(0.5, 0.5)] * 1024)
        )
    assert editing.read_state(sid) == before


def test_png16_and_float_precision():
    array = np.linspace(0, 1, 6000, dtype=np.float32).reshape(60, 100)
    encoded = editing.encode_depth(array, "png16")
    assert encoded[24:26] == bytes([16, 0])
    result = editing.decode_depth(encoded)
    assert np.max(np.abs(result - array)) <= 0.51 / 65535
    assert len(np.unique(result)) > 256
    np.testing.assert_array_equal(editing.decode_depth(editing.encode_depth(array, "npy")), array)


@pytest.mark.parametrize("value", [np.nan, np.inf, -0.1, 1.1])
def test_import_rejects_bad_values(value):
    output = io.BytesIO()
    np.save(output, np.full((5, 5), value, np.float32))
    with pytest.raises(editing.EditingError):
        editing.decode_depth(output.getvalue())


def test_import_rejects_8bit_and_huge_npy_header():
    output = io.BytesIO()
    Image.new("L", (8, 8), 100).save(output, "PNG")
    with pytest.raises(editing.EditingError, match="16-bit"):
        editing.decode_depth(output.getvalue())
    header = io.BytesIO()
    np.lib.format.write_array_header_1_0(
        header, {"descr": "<f4", "fortran_order": False, "shape": (1000000, 1000000)}
    )
    with pytest.raises(editing.EditingError):
        editing.decode_depth(header.getvalue())


def test_import_alignment_switch_and_separate_histories(document):
    sid, params, raw, original_bytes = document
    imported = np.linspace(0, 1, 33 * 33, dtype=np.float32).reshape(33, 33)
    editing.import_depth(sid, editing.encode_depth(imported, "png16"), "external.png")
    actual, _, state = editing.working_inputs(sid, params.depth_model)
    assert actual.shape == raw.shape
    assert state["depth_source"] == "imported"
    editing.add_stroke(
        sid, params.depth_model, editing.Stroke(tool="lower", points=[(0.5, 0.5)], strength=0.1)
    )
    edited_import = editing.working_inputs(sid, params.depth_model)[0].copy()
    editing.update_settings(sid, editing.EditorSettings(depth_source="ai"))
    np.testing.assert_array_equal(editing.working_inputs(sid, params.depth_model)[0], raw)
    editing.update_settings(sid, editing.EditorSettings(depth_source="imported"))
    np.testing.assert_array_equal(editing.working_inputs(sid, params.depth_model)[0], edited_import)
    assert depth.session_depth_path(sid, params.depth_model).read_bytes() == original_bytes
    with pytest.raises(editing.EditingError, match="aspect ratio"):
        editing.import_depth(sid, editing.encode_depth(np.zeros((8, 32)), "png16"), "bad.png")


def test_edits_mask_pipeline_and_physical_export(document):
    sid, params, _, _ = document
    editing.add_stroke(
        sid,
        params.depth_model,
        editing.Stroke(tool="raise", points=[(0.5, 0.5)], strength=0.1, radius=0.15),
    )
    h, shape = pipeline.render_heightmap(sid, params, 65)
    mesh = meshing.build_export_mesh(h, params, image_shape=shape)
    center = mesh.vertices[: 65 * 65].reshape(65, 65, 3)[32, 32]
    assert center[2] == pytest.approx(params.base_thickness_mm + 0.5 * params.relief_height_mm)
    editing.add_stroke(
        sid,
        params.depth_model,
        editing.Stroke(channel="mask", tool="remove", points=[(0.5, 0.5)], radius=0.2, strength=1),
    )
    h, shape = pipeline.render_heightmap(sid, params, 128)
    assert np.isfinite(h).all()
    mesh = meshing.build_export_mesh(h, params, image_shape=shape)
    assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume > 0


def test_mask_transition_is_continuous_and_uniform_cases_are_safe():
    mask = np.zeros((100, 100), np.float32)
    mask[20:80, 20:80] = 1
    alpha = quality.mask_alpha(mask, 100, 1, 8)
    assert alpha[50, 50] == pytest.approx(1)
    assert alpha[0, 0] == 0
    assert np.max(np.abs(np.diff(alpha[50]))) < 0.3
    assert np.all(quality.mask_alpha(np.zeros_like(mask), 100, 1, 2) == 0)
    assert np.all(quality.mask_alpha(np.ones_like(mask), 100, 1, 2) == 1)


def test_document_api_conflict_source_export_and_resource_guard(document, monkeypatch):
    sid, params, _, _ = document
    client = TestClient(app)
    base = f"/api/sessions/{sid}"
    assert client.get(base + "/editor").json()["revision"] == 0
    body = {"tool": "raise", "points": [[0.5, 0.5]], "strength": 0.1, "expected_revision": 0}
    assert client.post(base + "/editor/stroke", json=body).status_code == 200
    assert client.post(base + "/editor/stroke", json=body).status_code == 409
    export = client.get(base + "/depth/export?source=working&format=png16")
    assert export.status_code == 200 and export.content[24:26] == bytes([16, 0])
    assert client.get(base + "/preview/heightmap").status_code == 200
    monkeypatch.setattr(settings, "export_memory_mb", 1)
    plan = client.post(base + "/export-plan", json=params.model_dump())
    assert not plan.json()["allowed"]
    result = client.post(base + "/export", json=params.model_dump())
    assert result.status_code == 422 and result.json()["error"] == "resource_limit"


def test_original_comparison_is_readonly_and_restores_are_reversible(document):
    sid, params, raw, original = document
    editing.add_stroke(
        sid, params.depth_model, editing.Stroke(tool="raise", points=[(0.5, 0.5)], strength=0.1)
    )
    before = editing.read_state(sid)
    h, _ = pipeline.render_heightmap(sid, params, 65, original=True)
    np.testing.assert_allclose(h, raw, atol=1e-6)
    assert editing.read_state(sid) == before
    editing.restore_ai(sid, params.depth_model)
    np.testing.assert_array_equal(editing.working_inputs(sid, params.depth_model)[0], raw)
    editing.history_action(sid, params.depth_model, "depth", "undo")
    assert editing.working_inputs(sid, params.depth_model)[0][32, 32] == 0.5
    assert depth.session_depth_path(sid, params.depth_model).read_bytes() == original


def test_import_versions_and_white_far_orientation(document):
    sid, params, raw, _ = document
    first = editing.import_depth(
        sid, editing.encode_depth(raw, "npy"), "first.npy", white_is_far=True
    )
    editing.import_depth(sid, editing.encode_depth(raw * 0.5, "png16"), "second.png")
    editing.update_settings(
        sid, editing.EditorSettings(depth_source="imported", import_id=first["id"])
    )
    np.testing.assert_allclose(editing.working_inputs(sid, params.depth_model)[0], 0.6)
    assert len(editing.read_state(sid)["imports"]) == 2


@pytest.mark.parametrize("format", ["stl", "obj"])
def test_export_snapshot_roundtrip_after_import_mask_and_edit(document, format):
    import trimesh

    sid, params, raw, _ = document
    imported = raw.copy()
    imported[25:40, 25:40] = 0.65
    editing.import_depth(sid, editing.encode_depth(imported, "png16"), "corrected.png")
    editing.add_stroke(
        sid, params.depth_model, editing.Stroke(tool="raise", points=[(0.5, 0.5)], strength=0.05)
    )
    editing.add_stroke(
        sid,
        params.depth_model,
        editing.Stroke(channel="mask", tool="remove", points=[(0.1, 0.1)], radius=0.1, strength=1),
    )
    snapshot = editing.read_state(sid)
    job = jobs.ExportJob(job_id="roundtrip-" + format, session_id=sid, editor_snapshot=snapshot)
    editing.restore_ai(sid, params.depth_model)
    configured = params.model_copy(
        update={
            "resolution": 512,
            "output_format": format,
            "model_width_mm": 113,
            "border_frame_mm": 7,
        }
    )
    jobs._run_export(job, configured)
    assert job.status == "ready", job.error
    mesh = trimesh.load(io.BytesIO(job.file_path.read_bytes()), file_type=format, force="mesh")
    assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume > 0
    assert np.isfinite(mesh.vertices).all()
    np.testing.assert_allclose(mesh.extents[:2], [127, 127], atol=2e-5)
    assert mesh.bounds[0, 2] == 0
    # Frame reaches full stock height; masked center stays a continuous solid.
    assert mesh.bounds[1, 2] == pytest.approx(
        configured.base_thickness_mm + configured.relief_height_mm
    )
    nearest = np.argmin(
        np.sum((mesh.vertices[:, :2] - [63.5, 63.5]) ** 2, axis=1)
        + np.where(mesh.vertices[:, 2] > 0, 0, 10000)
    )
    assert mesh.vertices[nearest, 2] > 8.5  # Imported+raised snapshot, despite later AI reset.
    assert "exports" in job.file_path.parts and job.job_id in job.file_path.parts
    # Inspection is the actual validated/simplified export snapshot, not a new
    # live preview. Later edits must not change either artifact.
    inspection = trimesh.load(
        io.BytesIO(job.preview_path.read_bytes()), file_type="glb"
    ).to_geometry()
    assert len(inspection.faces) == len(mesh.faces)
    np.testing.assert_allclose(inspection.bounds, mesh.bounds, atol=0.0001)
    assert inspection.is_watertight
    original_inspection = job.preview_path.read_bytes()
    editing.history_action(sid, configured.depth_model, "depth", "reset")
    assert job.preview_path.read_bytes() == original_inspection


def test_optional_segmentation_fallback_and_mask_persistence(document, monkeypatch):
    sid, params, _, _ = document
    monkeypatch.setattr(segmentation, "status", lambda: {"available": True})
    mask = np.zeros((65, 65), np.float32)
    mask[10:55, 15:50] = 1
    monkeypatch.setattr(segmentation, "predict", lambda *args: mask)
    result = editing.automatic_mask(sid, params.depth_model)
    assert "U2NETP" in result["method"]
    np.testing.assert_array_equal(editing.working_inputs(sid, params.depth_model)[1], mask)
    editing.history_action(sid, params.depth_model, "mask", "undo")
    assert np.all(editing.working_inputs(sid, params.depth_model)[1] == 1)
    editing.history_action(sid, params.depth_model, "mask", "redo")
    np.testing.assert_array_equal(editing.working_inputs(sid, params.depth_model)[1], mask)


def test_missing_or_corrupt_optional_model_fails_without_download(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "models_dir", tmp_path)
    with pytest.raises(ValueError, match="not installed"):
        segmentation.predict(Image.new("RGB", (32, 32)))
    path = segmentation.model_path()
    path.parent.mkdir()
    path.write_bytes(bytes(segmentation.MODEL_BYTES))
    monkeypatch.setattr(segmentation, "status", lambda: {"available": True})
    with pytest.raises(ValueError, match="checksum"):
        segmentation.predict(Image.new("RGB", (32, 32)))


def test_restricted_parameter_change_does_not_corrupt_session(document, monkeypatch):
    sid, params, _, _ = document
    monkeypatch.setattr(settings, "commercial_build", True)
    monkeypatch.setattr(settings, "authorized_models", ())
    response = TestClient(app).put(
        f"/api/sessions/{sid}/params",
        json=params.model_copy(update={"depth_model": "da2-large"}).model_dump(),
    )
    assert response.status_code == 403
    assert sessions.read_params(sid).depth_model == "da2-small"
