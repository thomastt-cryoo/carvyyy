"""Disk accounting and explicit local storage maintenance."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from app.config import settings
from app.path_safety import UnsafePathError, contained_path, is_link

_cache_lock = threading.RLock()
_activity_lock = threading.Lock()
maintenance_lock = threading.RLock()
_recent: dict[str, float] = {}
_leases: dict[str, int] = {}
_HASH = re.compile(r"^[0-9a-f]{64}$")
_SID = re.compile(r"^[0-9a-f]{32}$")
_CACHE = re.compile(r"^raw_depth_(da2-small|da2-large|da3mono-large)_[0-9]+\.npy$")


def has_active_work() -> bool:
    with _activity_lock:
        return any(_leases.values())


def touch_session(sid: str) -> None:
    with _activity_lock:
        now = time.monotonic()
        _recent[sid] = now
        if len(_recent) > 2048:
            for key in [key for key, value in _recent.items() if now - value > 600]:
                _recent.pop(key, None)


@contextmanager
def session_lease(sid: str):
    touch_session(sid)
    with maintenance_lock, _activity_lock:
        _leases[sid] = _leases.get(sid, 0) + 1
    try:
        yield
    finally:
        with _activity_lock:
            count = _leases.get(sid, 1) - 1
            if count > 0:
                _leases[sid] = count
            else:
                _leases.pop(sid, None)
        touch_session(sid)


def is_leased(sid: str) -> bool:
    with _activity_lock:
        return bool(_leases.get(sid))


@contextmanager
def cache_access():
    with _cache_lock:
        yield


def _active_hashes() -> set[str]:
    now = time.monotonic()
    with _activity_lock:
        ids = {sid for sid, used in _recent.items() if now - used < 600}
        ids.update(sid for sid, count in _leases.items() if count)
    result = set()
    for sid in ids:
        if not _SID.fullmatch(sid):
            continue
        try:
            meta = json.loads(contained_path(settings.sessions_dir, sid, "meta.json").read_text())
            if _HASH.fullmatch(meta.get("image_hash", "")):
                result.add(meta["image_hash"])
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return result


def _cache_files() -> list[Path]:
    try:
        root = contained_path(settings.cache_dir)
    except UnsafePathError:
        return []
    result = []
    if not root.exists():
        return result
    for directory in root.iterdir():
        if is_link(directory) or not directory.is_dir() or not _HASH.fullmatch(directory.name):
            continue
        for path in directory.iterdir():
            # Only app-created duplicate depth files. No recursive delete, arbitrary
            # upload, model weight, original photo, editing journal or export is eligible.
            if (
                not is_link(path)
                and path.is_file()
                and _CACHE.fullmatch(path.name)
                and path.resolve().is_relative_to(root)
            ):
                result.append(path)
    return result


def cleanup_cache(
    *,
    dry_run: bool = True,
    max_mb: float | None = None,
    retention_days: float | None = None,
    now: float | None = None,
    expected_plan: str | None = None,
) -> dict:
    limit = (settings.cache_max_mb if max_mb is None else max_mb) * 1024**2
    age = (settings.cache_retention_days if retention_days is None else retention_days) * 86400
    if limit < 0 or age < 0:
        raise ValueError("Cache limits cannot be negative.")
    current_time = time.time() if now is None else now
    with _cache_lock:
        protected = _active_hashes()
        files = _cache_files()
        total = sum(path.stat().st_size for path in files)
        remaining, candidates, removed, errors = total, [], [], []
        for path in sorted(files, key=lambda path: (path.stat().st_mtime, path)):
            if path.parent.name in protected:
                continue
            stat = path.stat()
            if current_time - stat.st_mtime < age and remaining <= limit:
                continue
            record = {
                "file": str(path.relative_to(settings.cache_dir.resolve())),
                "bytes": stat.st_size,
            }
            candidates.append(record)
            remaining -= stat.st_size
        fingerprint = _fingerprint(
            [
                (row["file"], row["bytes"], (settings.cache_dir / row["file"]).stat().st_mtime_ns)
                for row in candidates
            ]
        )
        if expected_plan is not None and expected_plan != fingerprint:
            raise ValueError("Cache contents changed. Review the current cleanup plan and retry.")
        if not dry_run:
            for record in candidates:
                try:
                    path = contained_path(settings.cache_dir, record["file"])
                    path.unlink()
                    removed.append(record)
                except (OSError, UnsafePathError):
                    errors.append(record["file"])
        return {
            "dry_run": dry_run,
            "cache_bytes_before": total,
            "eligible_bytes": sum(item["bytes"] for item in candidates),
            "removed_bytes": sum(item["bytes"] for item in removed),
            "candidates": candidates,
            "plan": fingerprint,
            "errors": errors,
            "protected_active_images": len(protected),
            "documents_policy": (
                "Photos, raw session depth, imports, masks, edits, exports "
                "and model weights are never deleted."
            ),
        }


def _fingerprint(records: list) -> str:
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode()).hexdigest()


def recovery_root(*, pending: bool = False) -> Path:
    parent = settings.sessions_dir.absolute().parent
    return contained_path(parent, "project-purge" if pending else "project-trash")


def _tree(root: Path, *, strict: bool = False):
    """Walk only ordinary entries. Yield parents before children."""
    if is_link(root):
        if strict:
            raise UnsafePathError(
                "This folder contains a link. Review the files before removing it."
            )
        return
    if not root.is_dir():
        return
    stack = [root]
    while stack:
        current = stack.pop()
        if is_link(current):
            if strict:
                raise UnsafePathError("This project contains a linked folder.")
            continue
        for child in sorted(current.iterdir()):
            if is_link(child) or not (child.is_dir() or child.is_file()):
                if strict:
                    raise UnsafePathError("This project contains a link or special file.")
                continue
            yield child
            if child.is_dir():
                stack.append(child)


def _tree_bytes(root: Path) -> int:
    try:
        return sum(path.stat().st_size for path in _tree(root) if path.is_file())
    except OSError:
        return 0  # An inaccessible tree remains untouched.


def recovery_projects(*, pending: bool = False) -> list[dict]:
    try:
        root = recovery_root(pending=pending)
    except UnsafePathError:
        return []
    if not root.is_dir():
        return []
    result = []
    for path in sorted(root.iterdir()):
        if not _SID.fullmatch(path.name) or is_link(path) or not path.is_dir():
            continue
        try:
            value = json.loads(contained_path(path, "project.json").read_text(encoding="utf-8"))
            name = value["name"]
        except (OSError, ValueError, KeyError, TypeError):
            name = "Deleted project"
        result.append({"id": path.name, "name": name, "bytes": _tree_bytes(path)})
    return result


def purge_project(sid: str, *, pending: bool, expected_plan: str | None = None) -> dict:
    """Stage the selected project before unlinking files. A staged tree is resumable."""
    if not _SID.fullmatch(sid):
        raise ValueError("Choose a deleted project from the list.")
    with maintenance_lock:
        source = contained_path(recovery_root(pending=pending), sid)
        active = contained_path(settings.sessions_dir, sid)
        if active.exists() or is_leased(sid):
            raise ValueError("This project is active or in use.")
        if not source.is_dir():
            raise ValueError("This recovery copy is no longer available.")
        entries = list(_tree(source, strict=True))
        directories = [path.relative_to(source) for path in entries if path.is_dir()]
        files = []
        for path in entries:
            if path.is_file():
                stat = path.stat()
                files.append((str(path.relative_to(source)), stat.st_size, stat.st_mtime_ns))
        fingerprint = _fingerprint(sorted(files))
        result = {"plan": fingerprint, "bytes": sum(row[1] for row in files), "files": len(files)}
        if expected_plan is None:
            return result
        if fingerprint != expected_plan:
            raise ValueError(
                "The recovery copy changed. Review the current removal plan and retry."
            )
        if not pending:
            target = contained_path(recovery_root(pending=True), sid)
            if target.exists():
                raise ValueError("A removal is already pending for this project.")
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
            source = target

        # A crash or locked file leaves this UUID in project-purge. Never expose
        # a partially removed tree as a restorable project.
        removed_bytes = 0
        try:
            for relative, size, _ in files:
                contained_path(source, relative).unlink()
                removed_bytes += size
            for relative in reversed(directories):
                contained_path(source, relative).rmdir()
            source.rmdir()
        except (OSError, UnsafePathError):
            return {**result, "removed_bytes": removed_bytes, "pending": True}
        return {**result, "removed_bytes": removed_bytes, "pending": False}


def storage_summary() -> dict:
    working_bytes, export_bytes, inspection_bytes, active_bytes = 0, 0, 0, 0
    root = settings.sessions_dir
    with maintenance_lock, _cache_lock:
        for path in _tree(root):
            if not path.is_file():
                continue
            parts = path.relative_to(root).parts
            if not _SID.fullmatch(parts[0]):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if len(parts) == 4 and parts[1] == "exports" and _SID.fullmatch(parts[2]):
                if parts[3] == "inspection.glb":
                    inspection_bytes += size
                else:
                    export_bytes += size
            elif parts[1:] in {("editing", "working-depth.npy"), ("editing", "working-cache.json")}:
                working_bytes += size
            else:
                active_bytes += size
        deleted = recovery_projects()
        pending = recovery_projects(pending=True)
        cache_bytes = sum(path.stat().st_size for path in _cache_files())

    return {
        "cache_bytes": cache_bytes,
        "active_project_bytes": active_bytes,
        "protected_session_bytes": active_bytes + working_bytes + export_bytes + inspection_bytes,
        "working_cache_bytes": working_bytes,
        "export_bytes": export_bytes,
        "inspection_bytes": inspection_bytes,
        "deleted_project_bytes": sum(project["bytes"] for project in deleted),
        "pending_purge_bytes": sum(project["bytes"] for project in pending),
        "deleted_projects": deleted,
        "pending_purges": pending,
        "model_bytes": _tree_bytes(settings.models_dir),
        "cache_max_mb": settings.cache_max_mb,
        "cache_retention_days": settings.cache_retention_days,
        "automatic_cache_cleanup": settings.auto_clean_cache,
        "session_deletion_enabled": False,
    }
