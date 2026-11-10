"""The same pinned Small weights on the supported Intel Mac CPU runtime."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache

import cv2
import numpy as np

from app.config import settings
from app.path_safety import contained_path

SMALL_REVISION = "5426e4f0f36572d16453bbda7a8389317b1bef99"


def model_path():
    return contained_path(settings.models_dir, "depth", "da2-small.onnx")


@lru_cache(maxsize=8)
def _valid_model(filename, size, modified, metadata_modified):
    from pathlib import Path

    path = Path(filename)
    try:
        metadata = json.loads((path.parent / "metadata.json").read_bytes())
        return (
            metadata["model_id"] == "da2-small"
            and metadata["source_revision"] == SMALL_REVISION
            and metadata["bytes"] == size
            and metadata["sha256"] == hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
            and (path.parent / "processor/preprocessor_config.json").is_file()
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def installed():
    try:
        path = model_path()
        meta = path.parent / "metadata.json"
        return path.is_file() and _valid_model(
            str(path), path.stat().st_size, path.stat().st_mtime_ns, meta.stat().st_mtime_ns
        )
    except OSError:
        return False


class OnnxDA2Backend:
    def __init__(self, spec):
        self.spec = spec
        self.session = None
        self.processor = None

    def load(self, device):
        from app.depth import DepthInferenceError

        if device != "cpu" or self.spec.model_id != "da2-small":
            raise DepthInferenceError("The Intel runtime uses the Small model on CPU.")
        if not installed():
            raise DepthInferenceError(
                "The Small model is missing or damaged. Repair application setup."
            )
        import onnxruntime as ort
        from transformers.models.dpt.image_processing_pil_dpt import DPTImageProcessorPil

        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        self.processor = DPTImageProcessorPil.from_pretrained(
            model_path().parent / "processor", local_files_only=True
        )
        self.session = ort.InferenceSession(
            str(model_path()), options, providers=["CPUExecutionProvider"]
        )

    def infer(self, image):
        from app.depth import DepthInferenceError, normalize_to_closest

        if self.session is None:
            raise DepthInferenceError("Small model is not loaded.")
        pixels = self.processor(images=image, return_tensors="np")["pixel_values"]
        native = self.session.run(None, {"pixel_values": np.asarray(pixels, dtype=np.float32)})[0]
        native = cv2.resize(native[0], (image.width, image.height), interpolation=cv2.INTER_CUBIC)
        return normalize_to_closest(native, self.spec.convention)

    def unload(self):
        self.session = None
        self.processor = None
