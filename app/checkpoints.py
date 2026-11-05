"""Explicit reversible editing checkpoints. Archived histories are never deleted."""

from __future__ import annotations

import json
import uuid

from pydantic import BaseModel, Field

from app import editing, project_store
from app.editor_api import router
from app.sessions import read_params


class Checkpoint(BaseModel):
    channel: str = Field(pattern=r"^(depth|mask)$")
    expected_revision: int | None = None


class Restore(BaseModel):
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    expected_revision: int | None = None


def archive(sid: str, state: dict, channel: str) -> str:
    identifier = uuid.uuid4().hex
    path = editing._file(sid, f"checkpoints/{identifier}.json")
    project_store.atomic_json(path, state)
    index = editing._file(sid, "checkpoints/index.json")
    value = json.loads(index.read_text()) if index.exists() else {"items": []}
    value["items"].append(
        {"id": identifier, "channel": channel, "created_at": project_store.timestamp()}
    )
    project_store.atomic_json(index, value)
    return identifier


@router.get("/editor/checkpoints")
def checkpoints(sid: str):
    path = editing._file(sid, "checkpoints/index.json")
    return json.loads(path.read_text()) if path.exists() else {"items": []}


@router.post("/editor/checkpoint")
def checkpoint(sid: str, request: Checkpoint):
    model = read_params(sid).depth_model
    with editing.lock_for(sid):
        state = editing.read_state(sid)
        editing._check_revision(state, request.expected_revision)
        working, mask, _ = editing.working_inputs(sid, model, state)
        identifier = archive(sid, state, request.channel)
        if request.channel == "mask":
            relative = f"masks/{uuid.uuid4().hex}.npy"
            editing._save_array(editing._file(sid, relative), mask)
            state["histories"]["mask"] = {
                "cursor": 1,
                "operations": [{"kind": "replace", "file": relative, "method": "checkpoint"}],
            }
        else:
            old_key = editing._key(state, model)
            version = uuid.uuid4().hex
            relative = f"imports/{version}.npy"
            editing._save_array(editing._file(sid, relative), working)
            editing._file(sid, f"imports/{version}.original").write_bytes(
                editing.encode_depth(working, "npy")
            )
            imported = {
                "id": version,
                "filename": "Depth checkpoint",
                "original_shape": list(working.shape),
                "working_shape": list(working.shape),
                "working_file": relative,
                "white_is_far": False,
                "alignment": "match",
                "checkpoint": identifier,
            }
            state.setdefault("imports", []).append(imported)
            state.update(imported=imported, depth_source="imported")
            state["histories"].pop(old_key, None)
        editing._commit(sid, state)
    return editing.public_state(sid, model)


@router.post("/editor/checkpoints/restore")
def restore(sid: str, request: Restore):
    with editing.lock_for(sid):
        current = editing.read_state(sid)
        editing._check_revision(current, request.expected_revision)
        path = editing._file(sid, f"checkpoints/{request.id}.json")
        if not path.is_file():
            raise editing.EditingError("That history checkpoint is not available.")
        archived = json.loads(path.read_text())
        if archived.get("version") != 1:
            raise editing.EditingError("This checkpoint uses an unsupported document version.")
        archive(sid, current, "before restore")
        archived["revision"] = current["revision"]
        editing._commit(sid, archived)
    return editing.public_state(sid, read_params(sid).depth_model)
