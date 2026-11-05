"""Read-only local setup checks. Never download or load a model to inspect it."""

from __future__ import annotations

import importlib.util
import json
import struct
import sys
from functools import lru_cache
from pathlib import Path

from app import depth
from app.config import MODEL_REGISTRY, model_use_allowed, settings


@lru_cache(maxsize=24)
def _valid_weights(filename: str, size: int, modified: int, config_modified: int) -> bool:
    """Validate small headers and complete tensor offsets, without loading tensor data."""
    path = Path(filename)
    try:
        if not isinstance(json.loads((path.parent / "config.json").read_text()), dict):
            return False
        with path.open("rb") as file:
            header_size = struct.unpack("<Q", file.read(8))[0]
            if not 2 <= header_size <= 4 * 1024**2 or header_size + 8 >= size:
                return False
            header = json.loads(file.read(header_size))
        offsets = [v["data_offsets"] for k, v in header.items() if k != "__metadata__"]
        payload = size - header_size - 8
        return (
            bool(offsets)
            and max(end for _, end in offsets) == payload
            and all(0 <= start <= end <= payload for start, end in offsets)
        )
    except (OSError, ValueError, TypeError, KeyError, struct.error):
        return False


def availability(model_id: str) -> dict:
    spec = MODEL_REGISTRY[model_id]
    location = settings.models_dir / "hub" / ("models--" + spec.weights.replace("/", "--"))
    files = [
        p
        for p in location.glob("snapshots/*/model.safetensors")
        if p.is_file() and (p.parent / "config.json").is_file()
    ]
    installed = any(
        _valid_weights(
            str(p),
            p.stat().st_size,
            p.stat().st_mtime_ns,
            (p.parent / "config.json").stat().st_mtime_ns,
        )
        for p in files
    )
    runtime = (
        depth._da3_worker_python().is_file()
        if spec.backend == "da3"
        else importlib.util.find_spec("torch") is not None
    )
    if not model_use_allowed(model_id):
        state, reason = "restricted", "Requires separate commercial authorization."
    elif spec.backend == "da3" and sys.platform == "darwin":
        state, reason = "unsupported", "This model's runtime is not supported on macOS."
    elif files and not installed:
        state, reason = (
            "damaged",
            "Model files are incomplete or damaged. Repair local application setup.",
        )
    elif not installed:
        state, reason = (
            "download_required",
            "Model files are not installed. Complete application setup before using it.",
        )
    elif not runtime:
        state, reason = (
            "setup_required",
            "The local model runtime is not installed. Complete application setup.",
        )
    elif depth.active_model_id() == model_id:
        state, reason = "loaded", "Installed and loaded locally."
    else:
        state, reason = "installed", "Installed; ready for local processing."
    return {
        "setup_state": state,
        "installed": installed,
        "runtime_installed": runtime,
        "selectable": state in {"installed", "loaded"},
        "setup_reason": reason,
        "activity": "processing locally" if depth.model_is_processing(model_id) else None,
    }
