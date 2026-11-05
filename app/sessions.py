"""Session directory management: one directory per upload under P2R_SESSIONS_DIR.

No database — each session is `data/sessions/{session_id}/` holding the EXIF-corrected
source image plus (from M2 onward) cached depth maps and params.json.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import pillow_heif
from PIL import Image, ImageOps

from app.config import settings
from app.path_safety import UnsafePathError, contained_path
from app.schemas import ReliefParams

pillow_heif.register_heif_opener()

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF"}
SOURCE_IMAGE_NAME = "source.png"
META_FILE_NAME = "meta.json"
PARAMS_FILE_NAME = "params.json"

# Session ids are uuid4().hex — exactly 32 lowercase hex chars. Everything else is
# rejected before it can touch the filesystem, so a hand-crafted id (e.g. "..") can
# never be joined into a path that escapes the sessions dir. Defense-in-depth: the
# FastAPI path param can't contain "/" either, but validating here is cheap and makes
# the guarantee explicit rather than relying on framework routing behavior.
_SESSION_ID_RE = re.compile(r"\A[0-9a-f]{32}\Z")


_meta_lock = Lock()


class InvalidImageError(ValueError):
    """Raised when an upload fails type/size/decoding validation."""


class SessionNotFoundError(KeyError):
    """Raised when a session id has no directory on disk."""


@dataclass
class SessionInfo:
    session_id: str
    width: int
    height: int
    image_hash: str


def session_dir(session_id: str) -> Path:
    # Reject any id that isn't a canonical session id *before* it reaches a path join,
    # so a malformed/hostile id can never escape sessions_dir. A bad id maps to no real
    # session, so SessionNotFoundError is the right signal (endpoints already 404 it).
    if not _SESSION_ID_RE.match(session_id):
        raise SessionNotFoundError(session_id)
    from app.storage import touch_session

    touch_session(session_id)
    try:
        return contained_path(settings.sessions_dir, session_id)
    except UnsafePathError as exc:
        raise SessionNotFoundError(session_id) from exc


def session_file(session_id: str, *parts: str) -> Path:
    try:
        return contained_path(session_dir(session_id), *parts)
    except UnsafePathError as exc:
        raise SessionNotFoundError(session_id) from exc


def meta_path(session_id: str) -> Path:
    return session_file(session_id, META_FILE_NAME)


def read_meta(session_id: str) -> dict:
    path = meta_path(session_id)
    if not path.exists():
        raise SessionNotFoundError(session_id)
    return json.loads(path.read_text())


def write_status(session_id: str, **fields: object) -> dict:
    """Merge status fields (status, model_id, device, elapsed_s, error) into meta.json."""
    with _meta_lock:
        meta = read_meta(session_id)
        meta.update(fields)
        atomic_json(meta_path(session_id), meta)
        return meta


def params_path(session_id: str) -> Path:
    return session_file(session_id, PARAMS_FILE_NAME)


def read_params(session_id: str) -> ReliefParams:
    """Load persisted params, or the schema defaults if none have been saved yet."""
    if not session_dir(session_id).exists():
        raise SessionNotFoundError(session_id)
    path = params_path(session_id)
    if not path.exists():
        return ReliefParams()
    return ReliefParams.model_validate_json(path.read_text())


def write_params(session_id: str, params: ReliefParams) -> None:
    if not session_dir(session_id).exists():
        raise SessionNotFoundError(session_id)
    atomic_json(params_path(session_id), params.model_dump())


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def create_session(image_bytes: bytes, filename: str) -> SessionInfo:
    """Validate an uploaded image, EXIF-correct it, and persist it as a new session."""
    if len(image_bytes) > settings.max_upload_bytes:
        raise InvalidImageError(
            f"Image exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB upload limit."
        )

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            if img.format not in ALLOWED_FORMATS:
                raise InvalidImageError(
                    f"Unsupported image format '{img.format}'. Use JPEG, PNG, WebP, or HEIC."
                )

            megapixels = (img.width * img.height) / 1_000_000
            if min(img.width, img.height) < 2:
                raise InvalidImageError("Use a photograph at least 2 by 2 pixels in size.")
            mp_limit = settings.max_upload_megapixels
            if megapixels > mp_limit:
                raise InvalidImageError(
                    f"Image is {megapixels:.1f} MP; the limit is {mp_limit:.0f} MP."
                )
            if max(img.width, img.height) / min(img.width, img.height) > settings.max_image_aspect:
                raise InvalidImageError(
                    f"This photograph is too narrow for meaningful AI depth estimation "
                    f"(maximum aspect ratio {settings.max_image_aspect:g}:1). "
                    "Crop it to a less extreme rectangle before uploading."
                )

            corrected = ImageOps.exif_transpose(img)
            if corrected is None:
                corrected = img
            original = corrected.copy()
            # Composite cutouts on neutral white for inference instead of exposing
            # hidden transparent RGB pixels as a black rectangular background.
            alpha = (
                corrected.convert("RGBA").getchannel("A")
                if "A" in corrected.getbands() or "transparency" in corrected.info
                else None
            )
            if alpha is not None:
                if alpha.getextrema()[1] == 0:
                    raise InvalidImageError(
                        "This image is fully transparent. Choose an image with a visible subject."
                    )
                backdrop = Image.new("RGBA", corrected.size, (255, 255, 255, 255))
                corrected = Image.alpha_composite(backdrop, corrected.convert("RGBA"))
            corrected = corrected.convert("RGB")
    except InvalidImageError:
        raise
    except Exception as exc:  # noqa: BLE001 - any decode failure is a validation error
        raise InvalidImageError(
            "This image could not be read. Try opening it in an image editor "
            "and saving a new JPEG, PNG, WebP, or HEIC file."
        ) from exc

    session_id = uuid.uuid4().hex
    published = session_dir(session_id)
    # A failed disk write never publishes a half-created project to the library.
    out_dir = contained_path(settings.sessions_dir, f".upload-{session_id}")

    # Persist the normalized PNG, then hash those exact bytes. The hash is the depth
    # cache key, so re-uploading the same photo (a new session) reuses cached depth.
    source_path = out_dir / SOURCE_IMAGE_NAME
    staged = False
    try:
        out_dir.mkdir(parents=True, exist_ok=False)
        staged = True
        corrected.save(source_path, format="PNG")
        # Retain exact upload and alpha without exposing an unfinished project.
        (out_dir / "original-upload.bin").write_bytes(image_bytes)
        if alpha is not None and alpha.getextrema()[0] < 255:
            original.convert("RGBA").save(out_dir / "original-cutout.png", format="PNG")
            alpha.save(out_dir / "source-alpha.png", format="PNG")
        image_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        info = SessionInfo(session_id, corrected.width, corrected.height, image_hash)
        _write_meta(out_dir, info, original_filename=filename)
        out_dir.rename(published)
    except OSError as exc:
        # Only our own unpublished upload files are eligible; never recurse.
        if staged:
            try:
                contained_path(settings.sessions_dir, out_dir.name)
                for child in out_dir.iterdir():
                    contained_path(out_dir, child.name).unlink()
                out_dir.rmdir()
            except (OSError, UnsafePathError):
                pass
        raise InvalidImageError(
            "The photo could not be saved. Check disk space and folder write access, then retry."
        ) from exc
    return info


def _write_meta(out_dir: Path, info: SessionInfo, *, original_filename: str) -> None:
    meta = {
        "session_id": info.session_id,
        "original_filename": original_filename,
        "width": info.width,
        "height": info.height,
        "image_hash": info.image_hash,
        "status": "created",
        "model_id": None,
        "device": None,
        "elapsed_s": None,
        "error": None,
    }
    (out_dir / META_FILE_NAME).write_text(json.dumps(meta, indent=2))
