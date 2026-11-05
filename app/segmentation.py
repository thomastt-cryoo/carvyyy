"""Optional verified, offline-only U2NETP salient-object isolation on CPU.

No runtime download. A fresh short-lived ORT session avoids permanently retaining
its activation arena beside the depth model. Only one segmentation runs at once.
"""

from __future__ import annotations

import hashlib
import importlib.util
import threading

import cv2
import numpy as np
from PIL import Image

from app.config import settings

MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx"
MODEL_SHA256 = "309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8"
MODEL_BYTES = 4_574_861
_lock = threading.Lock()


def model_path():
    return settings.models_dir / "segmentation" / "u2netp.onnx"


def status() -> dict:
    path = model_path()
    runtime = importlib.util.find_spec("onnxruntime") is not None
    weights = path.is_file() and path.stat().st_size == MODEL_BYTES
    return {
        "available": runtime and weights,
        "runtime_installed": runtime,
        "weights_installed": weights,
        "model": "U2NETP",
        "model_bytes": MODEL_BYTES,
        "sha256": MODEL_SHA256,
        "license": "Apache-2.0 (U-2-Net)",
        "note": "Optional local CPU model; no downloads during editing. Checksum verified on use.",
    }


def predict(photo: Image.Image, rectangle: list[float] | None = None) -> np.ndarray:
    if not status()["available"]:
        raise ValueError(
            "Optional U2NETP is not installed. Install the segmentation extra and verified "
            "weights with tools/m2/install_segmentation.py, or choose GrabCut."
        )
    path = model_path()
    if hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256:
        raise ValueError("U2NETP checksum mismatch. Reinstall the verified model weights.")
    photo = photo.convert("RGB")
    w, h = photo.size
    box = (0, 0, w, h)
    if rectangle is not None:
        if len(rectangle) != 4 or not np.isfinite(rectangle).all():
            raise ValueError("Selection must contain four finite normalized coordinates.")
        x0, y0, x1, y1 = np.clip(rectangle, 0, 1)
        if x1 - x0 < 0.01 or y1 - y0 < 0.01:
            raise ValueError("Draw a rectangle around the complete subject.")
        box = (
            int(x0 * w),
            int(y0 * h),
            max(int(x0 * w) + 1, int(x1 * w)),
            max(int(y0 * h) + 1, int(y1 * h)),
        )
    image = np.asarray(photo.crop(box).resize((320, 320), Image.Resampling.LANCZOS))
    tensor = image.astype(np.float32) / max(float(image.max()), 1e-6)
    tensor = (tensor - np.array([0.485, 0.456, 0.406], np.float32)) / np.array(
        [0.229, 0.224, 0.225], np.float32
    )
    with _lock:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
        prediction = session.run(
            None, {session.get_inputs()[0].name: tensor.transpose(2, 0, 1)[None]}
        )[0][0, 0]
        del session
    if not np.isfinite(prediction).all() or float(np.ptp(prediction)) < 1e-6:
        raise ValueError("U2NETP could not separate a subject. Select a region or paint the mask.")
    prediction = (prediction - prediction.min()) / np.ptp(prediction)
    mask = np.zeros((h, w), np.float32)
    mask[box[1] : box[3], box[0] : box[2]] = cv2.resize(
        prediction, (box[2] - box[0], box[3] - box[1]), interpolation=cv2.INTER_LINEAR
    )
    return mask
