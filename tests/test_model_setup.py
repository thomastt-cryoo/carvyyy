"""Local model availability is distinct from licensing and runtime support."""

import json
import struct

from app import depth, model_status
from app.config import settings


def test_missing_complete_and_damaged_model_states(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "models_dir", tmp_path)
    monkeypatch.setattr(depth, "active_model_id", lambda: None)
    # Weight-file tests must not depend on the host having PyTorch installed.
    monkeypatch.setattr(model_status.importlib.util, "find_spec", lambda name: object())
    assert model_status.availability("da2-small")["setup_state"] == "download_required"
    root = tmp_path / "hub/models--depth-anything--Depth-Anything-V2-Small-hf/snapshots/test"
    root.mkdir(parents=True)
    (root / "config.json").write_text("{}")
    header = json.dumps({"weight": {"dtype": "F32", "shape": [2], "data_offsets": [0, 8]}}).encode()
    path = root / "model.safetensors"
    path.write_bytes(struct.pack("<Q", len(header)) + header + bytes(8))
    installed = model_status.availability("da2-small")
    assert installed["installed"] and installed["selectable"]
    monkeypatch.setattr(model_status.importlib.util, "find_spec", lambda name: None)
    missing_runtime = model_status.availability("da2-small")
    assert missing_runtime["setup_state"] == "setup_required"
    assert missing_runtime["installed"] and not missing_runtime["selectable"]
    path.write_bytes(b"truncated")
    damaged = model_status.availability("da2-small")
    assert damaged["setup_state"] == "damaged" and not damaged["selectable"]
    assert model_status.availability("da2-large")["setup_state"] == "restricted"


def test_mac_unsupported_model_cannot_be_selected(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "models_dir", tmp_path)
    monkeypatch.setattr(model_status.sys, "platform", "darwin")
    status = model_status.availability("da3mono-large")
    assert status["setup_state"] == "unsupported" and not status["selectable"]
