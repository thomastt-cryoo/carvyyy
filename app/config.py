"""Env-driven settings. All knobs are read here, once, with the P2R_ prefix."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    port: int = _env_int("P2R_PORT", 8090)
    host: str = os.environ.get("P2R_HOST", "0.0.0.0")

    data_dir: Path = Path(os.environ.get("P2R_DATA_DIR", "data"))
    sessions_dir: Path = Path(os.environ.get("P2R_SESSIONS_DIR", str(data_dir / "sessions")))
    models_dir: Path = Path(os.environ.get("P2R_MODELS_DIR", str(data_dir / "models")))
    cache_dir: Path = Path(os.environ.get("P2R_CACHE_DIR", str(data_dir / "cache")))

    # "auto" | "cpu" | "cuda" | "mps"  (auto precedence: cuda > mps > cpu)
    device_override: str = os.environ.get("P2R_DEVICE", "auto")

    max_infer_px: int = _env_int("P2R_MAX_INFER_PX", 1024)
    max_upload_bytes: int = _env_int("P2R_MAX_UPLOAD_MB", 40) * 1024 * 1024
    max_upload_megapixels: float = float(os.environ.get("P2R_MAX_UPLOAD_MEGAPIXELS", "30"))

    # M2: conservative preflight; all resolutions remain available when safe.
    export_memory_mb: int = _env_int("P2R_EXPORT_MEMORY_MB", 1536)
    memory_fraction: float = float(os.environ.get("P2R_MEMORY_FRACTION", "0.55"))
    export_max_triangles: int = _env_int("P2R_EXPORT_MAX_TRIANGLES", 9_000_000)
    max_image_aspect: float = float(os.environ.get("P2R_MAX_IMAGE_ASPECT", "64"))
    commercial_build: bool = _env_bool("P2R_COMMERCIAL_BUILD", True)
    cache_max_mb: int = _env_int("P2R_CACHE_MAX_MB", 2048)
    cache_retention_days: int = _env_int("P2R_CACHE_RETENTION_DAYS", 30)
    auto_clean_cache: bool = _env_bool("P2R_AUTO_CLEAN_CACHE", False)
    authorized_models: tuple[str, ...] = tuple(
        item.strip()
        for item in os.environ.get("P2R_AUTHORIZED_MODELS", "").split(",")
        if item.strip()
    )

    default_model_id: str = os.environ.get("P2R_DEFAULT_MODEL_ID", "da3mono-large")

    def __init__(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # HF_HOME should point at the mounted models volume so weights persist offline.
        os.environ.setdefault("HF_HOME", str(self.models_dir))
        # Apple-Silicon MPS doesn't implement every op; let torch fall back to CPU for
        # the stragglers instead of crashing mid-inference. Harmless off-MPS; setdefault
        # respects an explicit user override.
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")


settings = Settings()


# --- Model registry (SPEC §5.1.1) -------------------------------------------------

# Internal depth convention after adapter normalization is always "1.0 = closest to
# camera". Each backend declares its NATIVE convention so the adapter knows how to flip:
#   "disparity" → native larger = closer (DA2 relative models); no flip needed.
#   "depth"     → native larger = farther (DA3MONO direct depth); flip before normalize.


@dataclass(frozen=True)
class ModelSpec:
    model_id: str  # registry key / ReliefParams.depth_model value
    weights: str  # Hugging Face repo id
    backend: str  # "da2" (transformers) | "da3" (depth_anything_3)
    convention: str  # native output convention: "disparity" | "depth"
    license: str  # as listed on the HF page at build time
    role: str  # short UI hint (geometric vs artistic vs fast/CPU)
    available: bool  # False = adapter not wired yet (selecting it errors clearly)
    distribution_approved: bool = True


MODEL_REGISTRY: dict[str, ModelSpec] = {
    "da3mono-large": ModelSpec(
        model_id="da3mono-large",
        weights="depth-anything/DA3MONO-LARGE",
        backend="da3",
        convention="depth",
        license="Apache-2.0",  # per the HF license field, checked 2026-07-18
        role="Geometric fidelity (direct depth). Best true-to-life proportions.",
        available=True,  # M2.5: served by the isolated da3worker venv (subprocess)
    ),
    "da2-large": ModelSpec(
        model_id="da2-large",
        weights="depth-anything/Depth-Anything-V2-Large-hf",
        backend="da2",
        convention="disparity",
        license="CC-BY-NC-4.0",
        role="Artistic bas-relief look (exaggerated near-field).",
        available=True,
        distribution_approved=False,
    ),
    "da2-small": ModelSpec(
        model_id="da2-small",
        weights="depth-anything/Depth-Anything-V2-Small-hf",
        backend="da2",
        convention="disparity",
        license="Apache-2.0",
        role="Lightweight Apache-licensed CPU fallback.",
        available=True,
    ),
}


def resolve_default_model(device: str) -> str:
    """The model auto-selected when the user hasn't chosen one.

    The commercial application selects Small on every supported device.
    Legacy research configurations retain their internal model resolution.
    """
    if settings.commercial_build:
        return "da2-small"
    if device == "mps":
        return "da2-small" if settings.commercial_build else "da2-large"
    if device != "cuda":
        return "da2-small"
    spec = MODEL_REGISTRY.get(settings.default_model_id)
    if spec is not None and spec.available and model_use_allowed(spec.model_id):
        return settings.default_model_id
    return "da2-small" if settings.commercial_build else "da2-large"


def model_use_allowed(model_id: str) -> bool:
    spec = MODEL_REGISTRY[model_id]
    return (
        spec.distribution_approved
        or not settings.commercial_build
        or model_id in settings.authorized_models
    )
