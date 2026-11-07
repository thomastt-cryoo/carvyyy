"""Durable project-wide undo/redo over settings and immutable editing references."""

from __future__ import annotations

import copy
import json
import threading
import uuid
from contextlib import contextmanager, suppress

from app import editing, sessions
from app.schemas import ReliefParams

_local = threading.local()


def _active() -> set[str]:
    if not hasattr(_local, "projects"):
        _local.projects = set()
    return _local.projects


def _path(sid: str, name: str):
    return sessions.session_file(sid, "history", name)


def _index(sid: str) -> dict:
    path = _path(sid, "index.json")
    return (
        json.loads(path.read_text())
        if path.exists()
        else {"entries": [], "cursor": 0, "transaction": "initial"}
    )


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    sessions.atomic_json(path, value)


def _capture(sid: str) -> dict:
    editor = editing.read_state(sid)
    revision = editor.pop("revision")
    project = sessions.session_file(sid, "project.json")
    saved = json.loads(project.read_text()) if project.exists() else {}
    saved.pop("updated_at", None)
    return {
        "params": sessions.read_params(sid).model_dump(),
        "editor": editor,
        "project": saved,
        "revision": revision,
    }


def _restore(sid: str, document: dict, keep_revision: bool = False) -> None:
    params = ReliefParams.model_validate(document["params"])
    current_revision = editing.read_state(sid)["revision"]
    revision = document["revision"] if keep_revision else current_revision + 1
    editor = document["editor"] | {"revision": revision}
    sessions.atomic_json(sessions.params_path(sid), params.model_dump())
    editing._atomic_json(editing._file(sid, "state.json"), editor)
    if document["project"]:
        sessions.atomic_json(sessions.session_file(sid, "project.json"), document["project"])


def _recover(sid: str) -> None:
    pending = _path(sid, "pending.json")
    if pending.exists():
        transaction = json.loads(pending.read_text())
        if _index(sid)["transaction"] != transaction["id"]:
            _restore(sid, transaction["before"], keep_revision=True)
        pending.unlink(missing_ok=True)


def recover(sid: str) -> None:
    if sid in _active():
        return
    with editing.lock_for(sid):
        _active().add(sid)
        try:
            _recover(sid)
        finally:
            _active().remove(sid)


def _diff(before, after, path=()) -> list[dict]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        keys = before.keys() | after.keys()
        if not path:
            keys -= {"revision"}
        for key in sorted(keys):
            if key in before and key in after:
                changes.extend(_diff(before[key], after[key], (*path, key)))
            else:
                changes.append(
                    {
                        "path": [*path, key],
                        "before": {"exists": key in before, "value": before.get(key)},
                        "after": {"exists": key in after, "value": after.get(key)},
                    }
                )
        return changes
    if isinstance(before, list) and isinstance(after, list):
        start = 0
        while start < min(len(before), len(after)) and before[start] == after[start]:
            start += 1
        return [
            {"path": list(path), "start": start, "before": before[start:], "after": after[start:]}
        ]
    return [
        {
            "path": list(path),
            "before": {"exists": True, "value": before},
            "after": {"exists": True, "value": after},
        }
    ]


def _apply(document: dict, changes: list[dict], direction: str) -> dict:
    result = copy.deepcopy(document)
    other = "before" if direction == "after" else "after"
    for change in changes:
        target = result
        path = change["path"]
        for key in path[:-1]:
            target = target[key]
        if "start" in change:
            values = target[path[-1]]
            start = change["start"]
            values[start : start + len(change[other])] = copy.deepcopy(change[direction])
        elif change[direction]["exists"]:
            target[path[-1]] = copy.deepcopy(change[direction]["value"])
        else:
            target.pop(path[-1], None)
    return result


@contextmanager
def record(sid: str):
    """Group nested writes into one user action and recover incomplete writes."""
    if sid in _active() or not sessions.params_path(sid).exists():
        yield
        return
    with editing.lock_for(sid):
        _active().add(sid)
        committed = False
        before = None
        pending = _path(sid, "pending.json")
        try:
            _recover(sid)
            before = _capture(sid)
            identifier = uuid.uuid4().hex
            _write(pending, {"id": identifier, "before": before})
            yield
            changes = _diff(before, _capture(sid))
            if changes:
                _write(_path(sid, identifier + ".json"), changes)
                index = _index(sid)
                entries = index["entries"][: index["cursor"]] + [identifier]
                _write(
                    _path(sid, "index.json"),
                    {"entries": entries, "cursor": len(entries), "transaction": identifier},
                )
            committed = True
        except BaseException:
            if before is not None:
                _restore(sid, before, keep_revision=True)
            raise
        finally:
            if committed:
                with suppress(OSError):
                    pending.unlink(missing_ok=True)
            _active().remove(sid)


def status(sid: str) -> dict:
    recover(sid)
    with editing.lock_for(sid):
        index = _index(sid)
        return {
            "undo": index["cursor"] > 0,
            "redo": index["cursor"] < len(index["entries"]),
            "token": index["transaction"],
        }


@contextmanager
def repair(sid: str):
    """Explicit repair creates a new baseline and keeps the previous index."""
    with editing.lock_for(sid):
        _active().add(sid)
        try:
            yield
            index = _path(sid, "index.json")
            if index.exists():
                _write(_path(sid, f"before-repair-{uuid.uuid4().hex}.json"), _index(sid))
            _write(index, {"entries": [], "cursor": 0, "transaction": uuid.uuid4().hex})
            _path(sid, "pending.json").unlink(missing_ok=True)
        finally:
            _active().remove(sid)


def move(sid: str, direction: str, expected_token: str) -> None:
    with editing.lock_for(sid):
        _active().add(sid)
        before = None
        committed = False
        pending = _path(sid, "pending.json")
        try:
            _recover(sid)
            index = _index(sid)
            if index["transaction"] != expected_token:
                raise editing.RevisionConflict("This project changed. Reload it before undoing.")
            cursor = index["cursor"]
            if (direction == "undo" and cursor == 0) or (
                direction == "redo" and cursor == len(index["entries"])
            ):
                return
            entry = cursor - 1 if direction == "undo" else cursor
            changes = json.loads(_path(sid, index["entries"][entry] + ".json").read_text())
            before = _capture(sid)
            identifier = uuid.uuid4().hex
            _write(pending, {"id": identifier, "before": before})
            _restore(sid, _apply(before, changes, "before" if direction == "undo" else "after"))
            index.update(cursor=cursor + (-1 if direction == "undo" else 1), transaction=identifier)
            _write(_path(sid, "index.json"), index)
            committed = True
        except BaseException:
            if before is not None:
                _restore(sid, before, keep_revision=True)
            raise
        finally:
            if committed:
                with suppress(OSError):
                    pending.unlink(missing_ok=True)
            _active().remove(sid)
