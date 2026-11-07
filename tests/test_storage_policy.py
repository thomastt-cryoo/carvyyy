"""Safety boundaries: disposable duplicates only; explicit commercial model policy."""

import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from app import depth, storage
from app.config import MODEL_REGISTRY, model_use_allowed, resolve_default_model, settings
from app.main import app


def test_cleanup_dryrun_age_quota_and_active_work_are_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "cache")
    monkeypatch.setattr(settings, "sessions_dir", tmp_path / "sessions")
    monkeypatch.setattr(settings, "models_dir", tmp_path / "models")
    monkeypatch.setattr(storage, "_recent", {})
    monkeypatch.setattr(storage, "_leases", {})
    files = []
    for i in range(3):
        path = settings.cache_dir / (str(i) * 64) / "raw_depth_da2-small_1024.npy"
        path.parent.mkdir(parents=True)
        path.write_bytes(bytes(100))
        os.utime(path, (time.time() - (40 - i) * 86400,) * 2)
        files.append(path)
    sid = "a" * 32
    session = settings.sessions_dir / sid
    session.mkdir(parents=True)
    (session / "meta.json").write_text(json.dumps({"image_hash": "0" * 64}))
    protected = [
        session / name
        for name in [
            "source.png",
            "raw_depth_da2-small.npy",
            "state.json",
            "mask.npy",
            "import.npy",
            "relief.stl",
        ]
    ]
    protected += [settings.models_dir / "weight.onnx", files[1].parent / "unknown.bin"]
    for path in protected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"valuable")
    with storage.session_lease(sid):
        dry = storage.cleanup_cache(max_mb=0, retention_days=0)
        assert dry["eligible_bytes"] == 200 and dry["removed_bytes"] == 0
        assert all(path.exists() for path in files)
        actual = storage.cleanup_cache(dry_run=False, max_mb=0, retention_days=0)
        assert actual["removed_bytes"] == 200
        assert files[0].exists() and not files[1].exists() and not files[2].exists()
        assert all(path.read_bytes() == b"valuable" for path in protected)
    assert storage._leases == {}
    summary = storage.storage_summary()
    assert summary["session_deletion_enabled"] is False
    assert summary["model_bytes"] == 8


def test_cache_cleanup_never_follows_symlinks(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "cache_dir", tmp_path / "cache")
    settings.cache_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    precious = outside / "raw_depth_da2-small_1024.npy"
    precious.write_bytes(b"keep")
    try:
        (settings.cache_dir / ("b" * 64)).symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("This Windows account cannot create symlinks")
    assert storage.cleanup_cache(dry_run=False, max_mb=0)["removed_bytes"] == 0
    assert precious.read_bytes() == b"keep"


def test_commercial_defaults_and_restricted_adapter_are_preserved(monkeypatch):
    monkeypatch.setattr(settings, "commercial_build", True)
    monkeypatch.setattr(settings, "authorized_models", ())
    assert resolve_default_model("mps") == "da2-small"
    assert model_use_allowed("da2-small") and model_use_allowed("da3mono-large")
    assert MODEL_REGISTRY["da2-large"].available
    assert not model_use_allowed("da2-large")
    with pytest.raises(depth.BackendUnavailableError, match="authorization"):
        depth._ensure_backend("da2-large")
    response = TestClient(app).get("/api/models").json()
    assert [row["model_id"] for row in response["models"]] == ["da2-small"]
    monkeypatch.setattr(settings, "authorized_models", ("da2-large",))
    assert model_use_allowed("da2-large")
    monkeypatch.setattr(settings, "authorized_models", ())
    monkeypatch.setattr(settings, "commercial_build", False)
    assert model_use_allowed("da2-large") and resolve_default_model("mps") == "da2-large"
