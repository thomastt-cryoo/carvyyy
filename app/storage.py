"""M2 safe maintenance of disposable shared depth caches, never customer documents."""

from __future__ import annotations

import json
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from app.config import settings

_cache_lock = threading.RLock()
_activity_lock = threading.Lock()
_recent: dict[str, float] = {}
_leases: dict[str, int] = {}
_HASH = re.compile(r"^[0-9a-f]{64}$")
_SID = re.compile(r"^[0-9a-f]{32}$")
_CACHE = re.compile(r"^raw_depth_(da2-small|da2-large|da3mono-large)_[0-9]+\.npy$")


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
    with _activity_lock:
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
            meta = json.loads((settings.sessions_dir / sid / "meta.json").read_text())
            if _HASH.fullmatch(meta.get("image_hash", "")):
                result.add(meta["image_hash"])
        except (OSError, ValueError):
            continue
    return result


def _cache_files() -> list[Path]:
    root = settings.cache_dir.resolve()
    result = []
    if not root.exists():
        return result
    for directory in root.iterdir():
        if directory.is_symlink() or not directory.is_dir() or not _HASH.fullmatch(directory.name):
            continue
        for path in directory.iterdir():
            # Only app-created duplicate depth files. No recursive delete, arbitrary
            # upload, model weight, original photo, editing journal or export is eligible.
            if (
                not path.is_symlink()
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
        for path in sorted(files, key=lambda path: path.stat().st_mtime):
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
            if not dry_run:
                try:
                    # Resolve/containment was checked above; recheck immediately before unlink.
                    if (
                        not path.resolve().is_relative_to(settings.cache_dir.resolve())
                        or path.is_symlink()
                    ):
                        continue
                    path.unlink()
                    removed.append(record)
                except OSError:
                    errors.append(record["file"])
        return {
            "dry_run": dry_run,
            "cache_bytes_before": total,
            "eligible_bytes": sum(item["bytes"] for item in candidates),
            "removed_bytes": sum(item["bytes"] for item in removed),
            "candidates": candidates,
            "errors": errors,
            "protected_active_images": len(protected),
            "documents_policy": (
                "Photos, raw session depth, imports, masks, edits, exports "
                "and model weights are never deleted."
            ),
        }


def storage_summary() -> dict:
    def size(directory):
        if not directory.exists():
            return 0
        return sum(
            path.stat().st_size
            for path in directory.rglob("*")
            if path.is_file() and not path.is_symlink()
        )

    return {
        "cache_bytes": sum(path.stat().st_size for path in _cache_files()),
        "protected_session_bytes": size(settings.sessions_dir),
        "model_bytes": size(settings.models_dir),
        "cache_max_mb": settings.cache_max_mb,
        "cache_retention_days": settings.cache_retention_days,
        "automatic_cache_cleanup": settings.auto_clean_cache,
        "session_deletion_enabled": False,
    }
