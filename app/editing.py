"""M2 reversible, source-aligned depth/mask editing and high-precision exchange.

The source photograph and raw model arrays are never overwritten. Small JSON
stroke journals and immutable import/mask files are the durable document; a float32
working cache is disposable. Every gesture is one undoable operation.
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
import uuid
from pathlib import Path, PurePosixPath
from typing import Literal

import cv2
import numpy as np
from PIL import Image
from pydantic import BaseModel, Field, field_validator
from scipy.ndimage import gaussian_filter

from app import depth
from app.config import settings
from app.path_safety import UnsafePathError, contained_path
from app.sessions import SOURCE_IMAGE_NAME, read_meta, session_dir, session_file


class EditingError(ValueError):
    pass


class DepthNotReadyError(EditingError):
    pass


class RevisionConflict(EditingError):
    pass


class Stroke(BaseModel):
    channel: Literal["depth", "mask"] = "depth"
    tool: Literal["raise", "lower", "smooth", "flatten", "keep", "remove"]
    points: list[tuple[float, float]] = Field(min_length=1, max_length=1024)
    radius: float = Field(0.04, ge=0.001, le=0.5)
    strength: float = Field(0.06, gt=0, le=1)
    level: float = Field(0.5, ge=0, le=1)
    expected_revision: int | None = Field(None, ge=0)

    @field_validator("points")
    @classmethod
    def valid_points(cls, value):
        if not all(np.isfinite([x, y]).all() and 0 <= x <= 1 and 0 <= y <= 1 for x, y in value):
            raise ValueError("Brush points must be finite normalized photo coordinates.")
        return value


class EditorSettings(BaseModel):
    depth_source: Literal["ai", "imported"] | None = None
    import_id: str | None = Field(None, pattern=r"^[0-9a-f]{32}$")
    mask_enabled: bool | None = None
    mask_feather_mm: float | None = Field(None, ge=0, le=10)
    mask_transition_mm: float | None = Field(None, ge=0.1, le=50)
    sculpt_strength: float | None = Field(None, ge=0, le=1)
    texture_guard: float | None = Field(None, ge=0, le=1)
    cnc_refinement: bool | None = None
    expected_revision: int | None = Field(None, ge=0)


_locks_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}
_grabcut_lock = threading.Lock()
MAX_OPERATIONS = 500
MAX_DOCUMENT_BYTES = 4_000_000


def lock_for(sid: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(sid, threading.RLock())


def _root(sid: str) -> Path:
    read_meta(sid)
    try:
        return contained_path(session_dir(sid), "editing")
    except UnsafePathError as exc:
        raise EditingError(
            "Linked editing folders are not supported. Restore the project folder."
        ) from exc


def _file(sid: str, relative: str) -> Path:
    value = PurePosixPath(relative)
    if value.is_absolute() or ".." in value.parts or "\\" in relative or ":" in relative:
        raise EditingError("Unsafe editing document path.")
    try:
        return contained_path(_root(sid), *value.parts)
    except UnsafePathError as exc:
        raise EditingError("Editing document path leaves its session or follows a link.") from exc


def _atomic_json(path: Path, value: dict) -> None:
    content = json.dumps(value, indent=2, allow_nan=False)
    if len(content.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise EditingError(
            "The editing journal reached its safe size limit. Export working depth, "
            "then import it as a new source to continue; existing saved work is unchanged."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{uuid.uuid4().hex}.tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(path)


def _save_array(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{uuid.uuid4().hex}.tmp")
    with temp.open("xb") as file:
        np.save(file, np.asarray(array, dtype=np.float32), allow_pickle=False)
    temp.replace(path)


def read_state(sid: str) -> dict:
    path = _file(sid, "state.json")
    if not path.exists():
        return {
            "version": 1,
            "revision": 0,
            "depth_source": "ai",
            "imported": None,
            "imports": [],
            "mask_enabled": False,
            "mask_feather_mm": 0.8,
            "mask_transition_mm": 4.0,
            "sculpt_strength": 0.0,
            "texture_guard": 0.0,
            "cnc_refinement": False,
            "histories": {},
        }
    try:
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            raise ValueError("journal is too large")
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("version") != 1 or not isinstance(state["histories"], dict):
            raise ValueError("unsupported document version")
        state.setdefault("cnc_refinement", False)
        return state
    except (ValueError, KeyError, AttributeError, OSError) as exc:
        raise EditingError(
            "Cannot read the editing journal. Original photo and AI depth are safe."
        ) from exc


def _key(state: dict, model_id: str) -> str:
    return (
        f"imported:{state['imported']['id']}"
        if state["depth_source"] == "imported"
        else f"ai:{model_id}"
    )


def _history(state: dict, key: str) -> dict:
    return state["histories"].setdefault(key, {"cursor": 0, "operations": []})


def _check_revision(state: dict, expected: int | None) -> None:
    if expected is not None and expected != state["revision"]:
        raise RevisionConflict(
            "This session changed in another request. Reload the editor and retry."
        )


def _commit(sid: str, state: dict) -> None:
    state["revision"] += 1
    _atomic_json(_file(sid, "state.json"), state)


def _append(sid: str, state: dict, key: str, operation: dict) -> None:
    history = _history(state, key)
    operations = history["operations"][: history["cursor"]]
    if len(operations) >= MAX_OPERATIONS:
        raise EditingError(
            "This layer has 500 gestures. Export the corrected depth before starting a new layer."
        )
    operations.append(operation)
    history.update(operations=operations, cursor=len(operations))
    _commit(sid, state)


def public_state(sid: str, model_id: str) -> dict:
    with lock_for(sid):
        state = read_state(sid)
        result = {key: value for key, value in state.items() if key != "histories"}
        for channel, key in [("depth", _key(state, model_id)), ("mask", "mask")]:
            history = _history(state, key)
            result[channel + "_undo"] = history["cursor"] > 0
            result[channel + "_redo"] = history["cursor"] < len(history["operations"])
            result[channel + "_operations"] = history["cursor"]
        result["depth_orientation"] = "white is nearer / higher relief (before optional inversion)"
        result["ai_available"] = depth.session_depth_path(sid, model_id).is_file()
        return result


def update_settings(sid: str, change: EditorSettings) -> None:
    with lock_for(sid):
        state = read_state(sid)
        _check_revision(state, change.expected_revision)
        fields = change.model_dump(exclude_none=True, exclude={"expected_revision"})
        import_id = fields.pop("import_id", None)
        if import_id:
            available = state.get("imports", []) or (
                [state["imported"]] if state["imported"] else []
            )
            selected = next((item for item in available if item["id"] == import_id), None)
            if selected is None:
                raise EditingError("This saved imported depth version is not available.")
            state["imported"] = selected
            fields["depth_source"] = "imported"
        if fields.get("depth_source") == "imported" and state["imported"] is None:
            raise EditingError("Import a depth map before selecting the imported source.")
        state.update(fields)
        _commit(sid, state)


def brush_weights(shape: tuple[int, int], stroke: Stroke) -> tuple[slice, slice, np.ndarray]:
    """Continuous soft union of the gesture, independent of pointer event density."""
    height, width = shape
    radius = max(0.5, stroke.radius * max(height, width))
    points = np.asarray(stroke.points) * [width - 1, height - 1]
    x0, y0 = np.maximum(0, np.floor(points.min(axis=0) - radius)).astype(int)
    x1, y1 = np.minimum([width, height], np.ceil(points.max(axis=0) + radius + 1)).astype(int)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    weights = np.zeros(xx.shape, dtype=np.float32)
    points = cv2.approxPolyDP(points.astype(np.float32).reshape(-1, 1, 2), 0.2, False).reshape(
        -1, 2
    )
    pairs = list(zip(points[:-1], points[1:], strict=True)) or [(points[0], points[0])]
    for start, end in pairs:
        delta = end - start
        denominator = max(float(delta @ delta), 1e-12)
        t = np.clip(((xx - start[0]) * delta[0] + (yy - start[1]) * delta[1]) / denominator, 0, 1)
        distance = np.sqrt(
            (xx - start[0] - t * delta[0]) ** 2 + (yy - start[1] - t * delta[1]) ** 2
        )
        t = np.clip(1 - distance / radius, 0, 1)
        np.maximum(weights, t * t * (3 - 2 * t), out=weights)
    return slice(y0, y1), slice(x0, x1), weights


def apply_stroke(array: np.ndarray, stroke: Stroke) -> np.ndarray:
    """Pure brush operation. Raise/lower strength is a fraction of normalized relief."""
    output = np.asarray(array, dtype=np.float32).copy()
    rows, cols, weights = brush_weights(output.shape, stroke)
    patch = output[rows, cols]
    alpha = weights * stroke.strength
    if stroke.tool in {"raise", "lower"}:
        patch += alpha * (1 if stroke.tool == "raise" else -1)
    elif stroke.tool in {"flatten", "keep", "remove"}:
        level = stroke.level if stroke.tool == "flatten" else float(stroke.tool == "keep")
        patch += alpha * (level - patch)
    elif stroke.tool == "smooth":
        sigma = np.clip(stroke.radius * max(output.shape) * 0.15, 0.5, 20)
        # A halo avoids a seam at the bounding box of the brush calculation.
        halo = int(np.ceil(sigma * 3))
        r0, r1 = max(0, rows.start - halo), min(output.shape[0], rows.stop + halo)
        c0, c1 = max(0, cols.start - halo), min(output.shape[1], cols.stop + halo)
        smoothed = gaussian_filter(output[r0:r1, c0:c1], sigma=sigma)
        target = smoothed[rows.start - r0 : rows.stop - r0, cols.start - c0 : cols.stop - c0]
        patch += alpha * (target - patch)
    return np.clip(output, 0, 1).astype(np.float32)


def add_stroke(sid: str, model_id: str, stroke: Stroke) -> None:
    if (stroke.channel == "mask") != (stroke.tool in {"keep", "remove"}):
        raise EditingError("Keep/remove tools paint the mask; depth tools paint the depth layer.")
    with lock_for(sid):
        state = read_state(sid)
        _check_revision(state, stroke.expected_revision)
        # Ensure the selected immutable source exists before recording a gesture.
        base_depth(sid, model_id, state)
        if stroke.channel == "mask":
            state["mask_enabled"] = True
        key = "mask" if stroke.channel == "mask" else _key(state, model_id)
        _append(
            sid,
            state,
            key,
            {"kind": "stroke", **stroke.model_dump(exclude={"channel", "expected_revision"})},
        )


def history_action(
    sid: str, model_id: str, channel: str, action: str, expected_revision: int | None = None
) -> None:
    if channel not in {"depth", "mask"} or action not in {"undo", "redo", "reset"}:
        raise EditingError("Unknown history action or layer.")
    with lock_for(sid):
        state = read_state(sid)
        _check_revision(state, expected_revision)
        key = "mask" if channel == "mask" else _key(state, model_id)
        history = _history(state, key)
        if action == "reset":
            _append(sid, state, key, {"kind": "reset"})
        else:
            history["cursor"] = max(
                0,
                min(
                    len(history["operations"]), history["cursor"] + (1 if action == "redo" else -1)
                ),
            )
            _commit(sid, state)


def base_depth(sid: str, model_id: str, state: dict, *, source: str | None = None) -> np.ndarray:
    source = source or state["depth_source"]
    if source == "imported":
        if state["imported"] is None:
            raise DepthNotReadyError("No imported depth map is available.")
        path = _file(sid, state["imported"]["working_file"])
    else:
        path = depth.session_depth_path(sid, model_id)
    if not path.exists():
        raise DepthNotReadyError(
            f"Depth for '{model_id}' is not ready. "
            "Wait for inference or choose an installed source."
        )
    try:
        return depth.load_normalized_depth(path)
    except (OSError, ValueError, EOFError) as exc:
        raise EditingError(
            "The saved depth source is damaged. Restore a backup or import a corrected depth map; "
            "the source has not been overwritten."
        ) from exc


def working_inputs(
    sid: str, model_id: str, state: dict | None = None
) -> tuple[np.ndarray, np.ndarray, dict]:
    with lock_for(sid):
        state = read_state(sid) if state is None else state
        base = base_depth(sid, model_id, state)
        key = _key(state, model_id)
        history = _history(state, key)
        operations = history["operations"][: history["cursor"]]
        cache_key = hashlib.sha256(
            json.dumps({"key": key, "ops": operations}, sort_keys=True).encode()
        ).hexdigest()
        marker, cache = _file(sid, "working-cache.json"), _file(sid, "working-depth.npy")
        working = None
        if operations and marker.exists() and cache.exists():
            try:
                if json.loads(marker.read_text()).get("key") == cache_key:
                    loaded = depth.load_normalized_depth(cache)
                    if loaded.shape == base.shape:
                        working = loaded
            except (OSError, ValueError, EOFError, AttributeError):
                pass  # Disposable cache: replay immutable source and saved gestures.
        if working is None:
            working = base.copy() if operations else base
            for op in operations:
                working = (
                    base.copy()
                    if op["kind"] == "reset"
                    else apply_stroke(
                        working,
                        Stroke(channel="depth", **{k: v for k, v in op.items() if k != "kind"}),
                    )
                )
            if operations:
                _save_array(cache, working)
                _atomic_json(marker, {"key": cache_key})
        mask = np.ones(base.shape, dtype=np.float32)
        mh = _history(state, "mask")
        for op in mh["operations"][: mh["cursor"]]:
            if op["kind"] == "replace":
                mask = np.load(_file(sid, op["file"]), allow_pickle=False)
                mask = cv2.resize(
                    mask, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_LINEAR
                )
            elif op["kind"] == "reset":
                mask.fill(1)
            else:
                mask = apply_stroke(
                    mask, Stroke(channel="mask", **{k: v for k, v in op.items() if k != "kind"})
                )
        return working, np.clip(mask, 0, 1), state


def decode_depth(data: bytes) -> np.ndarray:
    if len(data) > settings.max_upload_bytes:
        raise EditingError("Depth file exceeds the upload size limit.")
    try:
        if data.startswith(b"\x93NUMPY"):
            header = io.BytesIO(data)
            version = np.lib.format.read_magic(header)
            reader = (
                np.lib.format.read_array_header_1_0
                if version == (1, 0)
                else np.lib.format.read_array_header_2_0
            )
            shape, _, dtype = reader(header, max_header_size=1024)
            if (
                len(shape) != 2
                or min(shape) < 2
                or dtype.kind != "f"
                or np.prod(shape, dtype=object) > settings.max_upload_megapixels * 1_000_000
            ):
                raise EditingError("NPY depth dimensions or dtype exceed the supported limits.")
            array = np.load(io.BytesIO(data), allow_pickle=False, max_header_size=1024)
            if array.dtype.kind != "f":
                raise EditingError("NPY depth must contain floating-point values in 0 to 1.")
        else:
            with Image.open(io.BytesIO(data)) as image:
                if image.format != "PNG" or data[24:26] != bytes([16, 0]):
                    raise EditingError(
                        "Use a 16-bit grayscale PNG or lossless floating-point NPY. "
                        "8-bit/color images are not depth exchange files."
                    )
                if image.width * image.height > settings.max_upload_megapixels * 1_000_000:
                    raise EditingError("Depth map exceeds the pixel limit.")
                array = np.asarray(image, dtype=np.float32) / 65535.0
        if (
            array.ndim != 2
            or min(array.shape) < 2
            or array.size > settings.max_upload_megapixels * 1_000_000
        ):
            raise EditingError(
                "Depth map must be a 2D image of at least 2 by 2 pixels within the pixel limit."
            )
        if not np.isfinite(array).all() or array.min() < 0 or array.max() > 1:
            raise EditingError(
                "Depth values must be finite and in the range 0 to 1; white means nearer."
            )
        return np.asarray(array, dtype=np.float32)
    except EditingError:
        raise
    except Exception as exc:
        raise EditingError(
            "Could not decode depth. Use a 16-bit grayscale PNG or float NPY."
        ) from exc


def import_depth(
    sid: str,
    data: bytes,
    filename: str,
    *,
    white_is_far: bool = False,
    alignment: str = "match",
    expected_revision: int | None = None,
) -> dict:
    native = decode_depth(data)
    meta = read_meta(sid)
    photo_ratio = meta["width"] / meta["height"]
    difference = abs((native.shape[1] / native.shape[0]) / photo_ratio - 1)
    if alignment not in {"match", "stretch"}:
        raise EditingError("Unknown alignment policy.")
    if difference > 0.01 and alignment != "stretch":
        raise EditingError(
            "Depth map aspect ratio differs from the photo. Align/crop it first, "
            "or explicitly choose Stretch to photo."
        )
    scale = min(1.0, settings.max_infer_px / max(meta["width"], meta["height"]))
    shape = (max(2, round(meta["height"] * scale)), max(2, round(meta["width"] * scale)))
    normalized = 1 - native if white_is_far else native
    working = cv2.resize(normalized, (shape[1], shape[0]), interpolation=cv2.INTER_LINEAR)
    with lock_for(sid):
        state = read_state(sid)
        _check_revision(state, expected_revision)
        identifier = uuid.uuid4().hex
        relative = f"imports/{identifier}.npy"
        _save_array(_file(sid, relative), working)
        original = _file(sid, f"imports/{identifier}.original")
        original.write_bytes(data)
        state["imported"] = {
            "id": identifier,
            "filename": Path(filename).name,
            "original_shape": list(native.shape),
            "working_shape": list(shape),
            "working_file": relative,
            "white_is_far": white_is_far,
            "alignment": alignment,
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        state.setdefault("imports", []).append(state["imported"].copy())
        state["depth_source"] = "imported"
        _commit(sid, state)
        return state["imported"]


def encode_depth(array: np.ndarray, output_format: str) -> bytes:
    data = np.asarray(array, dtype=np.float32)
    if data.ndim != 2 or not np.isfinite(data).all() or data.min() < 0 or data.max() > 1:
        raise EditingError("Cannot export invalid normalized depth.")
    output = io.BytesIO()
    if output_format == "npy":
        np.save(output, data, allow_pickle=False)
    elif output_format == "png16":
        Image.fromarray(np.rint(data * 65535).astype(np.uint16)).save(output, format="PNG")
    else:
        raise EditingError("Choose png16 or npy for depth exchange.")
    return output.getvalue()


def restore_ai(sid: str, model_id: str, expected_revision: int | None = None) -> None:
    with lock_for(sid):
        state = read_state(sid)
        _check_revision(state, expected_revision)
        base_depth(sid, model_id, state, source="ai")
        state.update(
            depth_source="ai",
            mask_enabled=False,
            sculpt_strength=0.0,
            texture_guard=0.0,
            cnc_refinement=False,
        )
        _append(sid, state, _key(state, model_id), {"kind": "reset"})


def automatic_mask(
    sid: str,
    model_id: str,
    *,
    rectangle: list[float] | None = None,
    method: str = "auto",
    expected_revision: int | None = None,
) -> dict:
    from app import segmentation

    if method not in {"auto", "grabcut", "u2netp", "alpha"}:
        raise EditingError("Unknown automatic isolation method.")
    alpha_path = session_file(sid, "source-alpha.png")
    if method == "alpha" or (method == "auto" and alpha_path.is_file()):
        if not alpha_path.is_file():
            raise EditingError(
                "This image has no original transparency mask. Choose another isolation method."
            )
        with lock_for(sid):
            state = read_state(sid)
            _check_revision(state, expected_revision)
            raw = base_depth(sid, model_id, state)
            with Image.open(alpha_path) as image:
                mask = np.asarray(image.convert("L"), dtype=np.float32) / 255
            mask = cv2.resize(mask, (raw.shape[1], raw.shape[0]), interpolation=cv2.INTER_LINEAR)
            if rectangle is not None:
                if len(rectangle) != 4 or not np.isfinite(rectangle).all():
                    raise EditingError("Draw a valid subject rectangle.")
                x0, y0, x1, y1 = np.clip(rectangle, 0, 1)
                if x1 <= x0 or y1 <= y0:
                    raise EditingError("Draw a valid subject rectangle.")
                selection = np.zeros_like(mask)
                selection[
                    int(y0 * mask.shape[0]) : int(y1 * mask.shape[0]),
                    int(x0 * mask.shape[1]) : int(x1 * mask.shape[1]),
                ] = 1
                mask *= selection
            relative = f"masks/{uuid.uuid4().hex}.npy"
            _save_array(_file(sid, relative), mask)
            state["mask_enabled"] = True
            _append(
                sid,
                state,
                "mask",
                {"kind": "replace", "file": relative, "method": "alpha", "rectangle": rectangle},
            )
            return {
                "method": "Original image transparency",
                "foreground_fraction": float(mask.mean()),
                "note": "Used the cutout already present in your image. "
                "Keep/remove brushes remain available.",
            }
    use_model = method == "u2netp" or (method == "auto" and segmentation.status()["available"])
    if not use_model:
        result = _grabcut_mask(
            sid, model_id, rectangle=rectangle, expected_revision=expected_revision
        )
        if method == "auto":
            result["note"] = "Optional U2NETP absent; used GrabCut. " + result["note"]
        return result
    with lock_for(sid):
        state = read_state(sid)
        _check_revision(state, expected_revision)
        raw = base_depth(sid, model_id, state)
        try:
            with Image.open(session_file(sid, SOURCE_IMAGE_NAME)) as photo:
                photo = photo.convert("RGB")
                photo.thumbnail((1024, 1024))
                mask = segmentation.predict(photo, rectangle)
        except (ValueError, MemoryError) as exc:
            raise EditingError(str(exc) or "Isolation ran out of memory. Try GrabCut.") from exc
        mask = cv2.resize(mask, (raw.shape[1], raw.shape[0]), interpolation=cv2.INTER_LINEAR)
        relative = f"masks/{uuid.uuid4().hex}.npy"
        _save_array(_file(sid, relative), mask)
        state["mask_enabled"] = True
        coverage = float(mask.mean())
        _append(
            sid,
            state,
            "mask",
            {
                "kind": "replace",
                "file": relative,
                "method": "u2netp",
                "rectangle": rectangle,
                "foreground_fraction": coverage,
            },
        )
        return {
            "method": "U2NETP local salient-object segmentation",
            "foreground_fraction": coverage,
            "note": "Inspect the mask. Thin structures, clipped subjects and multiple "
            "objects may need keep/remove corrections.",
        }


def _grabcut_mask(
    sid: str,
    model_id: str,
    *,
    rectangle: list[float] | None = None,
    expected_revision: int | None = None,
) -> dict:
    """Depth-assisted color/graph segmentation. This is not semantic recognition."""
    with lock_for(sid):
        state = read_state(sid)
        _check_revision(state, expected_revision)
        raw = base_depth(sid, model_id, state)
        with Image.open(session_file(sid, SOURCE_IMAGE_NAME)) as image:
            image = image.convert("RGB")
            image.thumbnail((512, 512))
            rgb = np.asarray(image).copy()
        h, w = rgb.shape[:2]
        if min(h, w) < 8:
            raise EditingError(
                "This image is too narrow for automatic isolation. Use keep/remove brushes."
            )
        labels = np.full((h, w), cv2.GC_PR_BGD, dtype=np.uint8)
        if rectangle is not None:
            if len(rectangle) != 4 or not np.isfinite(rectangle).all():
                raise EditingError(
                    "Selection rectangle must contain four finite normalized coordinates."
                )
            x0, y0, x1, y1 = np.clip(rectangle, 0, 1)
            if x1 - x0 < 0.01 or y1 - y0 < 0.01:
                raise EditingError("Draw a rectangle around the complete subject.")
            labels.fill(cv2.GC_BGD)
            labels[
                int(y0 * h) : max(int(y0 * h) + 1, int(y1 * h)),
                int(x0 * w) : max(int(x0 * w) + 1, int(x1 * w)),
            ] = cv2.GC_PR_FGD
        else:
            near = cv2.resize(raw, (w, h), interpolation=cv2.INTER_LINEAR)
            labels[near >= np.quantile(near, 0.55)] = cv2.GC_PR_FGD
            center = np.zeros((h, w), dtype=bool)
            center[h // 8 : 7 * h // 8, w // 8 : 7 * w // 8] = True
            seeds = (near >= np.quantile(near, 0.9)) & center
            if not seeds.any() or np.ptp(near) < 0.01:
                labels[h // 8 : 7 * h // 8, w // 8 : 7 * w // 8] = cv2.GC_PR_FGD
                seeds = np.zeros((h, w), dtype=bool)
                seeds[3 * h // 8 : 5 * h // 8, 3 * w // 8 : 5 * w // 8] = True
            labels[seeds] = cv2.GC_FGD
            labels[[0, -1], :] = cv2.GC_BGD
            labels[:, [0, -1]] = cv2.GC_BGD
        try:
            with _grabcut_lock:
                cv2.setRNGSeed(42)
                cv2.grabCut(
                    rgb,
                    labels,
                    None,
                    np.zeros((1, 65)),
                    np.zeros((1, 65)),
                    4,
                    cv2.GC_INIT_WITH_MASK,
                )
        except cv2.error as exc:
            raise EditingError(
                "Automatic isolation could not find both subject and background. "
                "Select a tighter rectangle or paint the mask manually."
            ) from exc
        mask = np.isin(labels, [cv2.GC_FGD, cv2.GC_PR_FGD]).astype(np.float32)
        coverage = float(mask.mean())
        if coverage < 0.001:
            raise EditingError(
                "Automatic isolation found no foreground. "
                "Draw a subject rectangle or use keep/remove brushes."
            )
        mask = cv2.resize(mask, (raw.shape[1], raw.shape[0]), interpolation=cv2.INTER_LINEAR)
        relative = f"masks/{uuid.uuid4().hex}.npy"
        _save_array(_file(sid, relative), mask)
        state["mask_enabled"] = True
        _append(
            sid,
            state,
            "mask",
            {
                "kind": "replace",
                "file": relative,
                "method": "grabcut",
                "rectangle": rectangle,
                "foreground_fraction": coverage,
            },
        )
        return {
            "method": "GrabCut color/graph segmentation with depth initialization",
            "foreground_fraction": coverage,
            "note": (
                "Inspect the mask. Color similarity, clipped subjects and thin structures "
                "can need manual correction."
            ),
        }
