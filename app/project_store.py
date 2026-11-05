"""Local project metadata layered over the existing immutable session documents."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from app import editing, sessions
from app.config import settings


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def document(sid: str) -> dict:
    from app import depth

    root = sessions.session_dir(sid)
    if (
        not root.is_dir()
        or root.is_symlink()
        or not root.resolve().is_relative_to(settings.sessions_dir.resolve())
    ):
        raise sessions.SessionNotFoundError(sid)
    issues = []
    try:
        meta = sessions.read_meta(sid)
        if (
            not isinstance(meta, dict)
            or not all(
                isinstance(meta.get(key), int) and meta[key] > 0 for key in ["width", "height"]
            )
            or not isinstance(meta.get("original_filename"), str)
        ):
            raise ValueError("Invalid project metadata")
    except (ValueError, KeyError, OSError):
        meta = {}
        issues.append("Project information needs repair.")
    path = sessions.session_file(sid, "project.json")
    try:
        saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(saved, dict) or saved.get("version", 1) != 1:
            raise ValueError("Unknown project metadata")
        if saved and (not isinstance(saved.get("name"), str) or not saved["name"].strip()):
            raise ValueError("Invalid project name")
    except (ValueError, OSError):
        saved = {}
        issues.append("The project name/settings record needs repair.")
    if not sessions.session_file(sid, sessions.SOURCE_IMAGE_NAME).is_file():
        issues.append("The original image is missing. Restore this project from a backup.")
    try:
        sessions.read_params(sid)
    except (ValueError, OSError):
        issues.append("Shaping settings need repair.")
    modified = max(
        [root.stat().st_mtime]
        + [
            p.stat().st_mtime
            for p in [
                path,
                sessions.session_file(sid, "params.json"),
                sessions.session_file(sid, "editing", "state.json"),
            ]
            if p.is_file()
        ]
    )
    return {
        "id": sid,
        "name": saved.get("name") or Path(meta.get("original_filename") or "Untitled project").stem,
        "created_at": saved.get("created_at")
        or datetime.fromtimestamp(root.stat().st_ctime, UTC).isoformat(),
        "updated_at": datetime.fromtimestamp(modified, UTC).isoformat(),
        "preset": saved.get("preset", "Custom"),
        "preset_undo": bool(saved.get("preset_undo")),
        "image": {"w": meta.get("width"), "h": meta.get("height")},
        "status": meta.get("status", "error"),
        "interrupted": meta.get("status") == "processing" and not depth.is_processing(sid),
        "issues": issues,
        "thumbnail": f"/api/sessions/{sid}/source",
    }


def read(sid: str) -> dict:
    info = document(sid)
    path = sessions.session_file(sid, "project.json")
    if path.exists():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not isinstance(value.get("name"), str):
                raise ValueError("Invalid project information")
            return value
        except (ValueError, OSError) as exc:
            raise editing.EditingError(
                "Repair this project's information before changing it."
            ) from exc
    return {
        "version": 1,
        "name": info["name"],
        "created_at": info["created_at"],
        "preset": "Custom",
    }


def write(sid: str, value: dict) -> None:
    value["updated_at"] = timestamp()
    atomic_json(sessions.session_file(sid, "project.json"), value)


def all_projects() -> list[dict]:
    items = []
    for path in settings.sessions_dir.iterdir():
        if not sessions._SESSION_ID_RE.fullmatch(path.name) or path.is_symlink():
            continue
        try:
            items.append(document(path.name))
        except (OSError, sessions.SessionNotFoundError):
            continue
    return sorted(items, key=lambda row: row["updated_at"], reverse=True)


def repair(sid: str, reset_settings: bool = False) -> dict:
    from app.config import resolve_default_model
    from app.depth import select_device
    from app.schemas import ReliefParams

    document(sid)  # Validate directory containment and existence.
    with editing.lock_for(sid):
        try:
            with Image.open(sessions.session_file(sid, sessions.SOURCE_IMAGE_NAME)) as photo:
                photo.verify()
                width, height = photo.size
        except (OSError, ValueError) as exc:
            raise editing.EditingError(
                "The original image is missing or damaged. Restore this project from a backup "
                "or create a new project from the original photo. Existing work has been kept."
            ) from exc
        backup = sessions.session_file(sid, "recovery", str(time.time_ns()))
        backup.mkdir(parents=True)
        for name in ["meta.json", "project.json", "params.json"]:
            path = sessions.session_file(sid, name)
            if path.is_file():
                (backup / name).write_bytes(path.read_bytes())
        try:
            params = sessions.read_params(sid)
        except (ValueError, OSError):
            if not reset_settings:
                raise editing.EditingError(
                    "Choose Restore default settings to repair damaged shaping settings. "
                    "A backup is kept."
                ) from None
            params = ReliefParams(depth_model=resolve_default_model(select_device()))
            sessions.write_params(sid, params)
        try:
            name = read(sid).get("name", "Recovered project")
        except editing.EditingError:
            name = "Recovered project"
        atomic_json(
            sessions.session_file(sid, "meta.json"),
            {
                "session_id": sid,
                "original_filename": name + ".png",
                "width": width,
                "height": height,
                "image_hash": hashlib.sha256(
                    sessions.session_file(sid, sessions.SOURCE_IMAGE_NAME).read_bytes()
                ).hexdigest(),
                "status": "ready"
                if sessions.session_file(sid, f"raw_depth_{params.depth_model}.npy").exists()
                else "created",
                "model_id": params.depth_model,
                "device": None,
                "elapsed_s": None,
                "error": None,
            },
        )
        write(sid, {"version": 1, "name": name, "created_at": timestamp(), "preset": "Custom"})
    return document(sid)
