"""Intel support keeps the model choice and archive trust boundary unchanged."""

import hashlib
import json

import pytest
from PIL import Image

from app import depth, onnx_depth
from app.config import MODEL_REGISTRY
from tools.m5.package_runtime import native_target


@pytest.mark.parametrize(
    "os_name,machine,expected",
    [
        ("Windows", "AMD64", "windows-x86_64"),
        ("Darwin", "arm64", "macos-aarch64"),
        ("Darwin", "x86_64", "macos-x86_64"),
    ],
)
def test_native_target_preserves_each_architecture(os_name, machine, expected):
    assert native_target(os_name, machine) == expected


def test_other_native_targets_are_refused():
    with pytest.raises(ValueError):
        native_target("Windows", "ARM64")


def test_intel_backend_never_loads_removed_models(monkeypatch):
    monkeypatch.setattr(depth.settings, "depth_runtime", "onnx")
    assert isinstance(depth._make_backend(MODEL_REGISTRY["da2-small"]), onnx_depth.OnnxDA2Backend)
    with pytest.raises(depth.BackendUnavailableError):
        depth._make_backend(MODEL_REGISTRY["da2-large"])


def test_intel_model_status_rejects_corruption_before_loading_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(onnx_depth.settings, "models_dir", tmp_path)
    folder = tmp_path / "depth"
    (folder / "processor").mkdir(parents=True)
    path = folder / "da2-small.onnx"
    path.write_bytes(b"authenticated model fixture")
    (folder / "processor/preprocessor_config.json").write_text("{}")
    meta = {
        "model_id": "da2-small",
        "source_revision": onnx_depth.SMALL_REVISION,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    (folder / "metadata.json").write_text(json.dumps(meta))
    assert onnx_depth.installed()
    path.write_bytes(b"corrupt model of equal size!")
    assert not onnx_depth.installed()
    backend = onnx_depth.OnnxDA2Backend(MODEL_REGISTRY["da2-small"])
    with pytest.raises(depth.DepthInferenceError, match="missing or damaged"):
        backend.load("cpu")
    with pytest.raises(depth.DepthInferenceError, match="not loaded"):
        backend.infer(Image.new("RGB", (10, 10)))
