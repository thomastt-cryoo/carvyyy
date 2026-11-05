"""M3 project library, explicit presets and recoverable local deletion."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, UploadFile
from pydantic import BaseModel, Field, field_validator

from app import depth, editing, jobs, project_store, sessions, storage
from app.config import MODEL_REGISTRY, resolve_default_model, settings
from app.model_status import availability
from app.path_safety import UnsafePathError, contained_path
from app.schemas import ReliefParams

router = APIRouter(prefix="/api/projects")
PRESETS = {
    "Portrait": (
        {"gamma": 1.1, "smoothing": 1.8, "detail_blend": 0.04},
        {"sculpt_strength": 0.25, "texture_guard": 0.85},
    ),
    "Pet": (
        {"gamma": 1.1, "smoothing": 2.2, "detail_blend": 0.035},
        {"sculpt_strength": 0.35, "texture_guard": 0.9},
    ),
    "Object": (
        {"gamma": 1.0, "smoothing": 1.8, "detail_blend": 0.04},
        {"sculpt_strength": 0.2, "texture_guard": 0.9},
    ),
    "Ornament": (
        {"gamma": 1.0, "smoothing": 1.2, "detail_blend": 0.08},
        {"sculpt_strength": 0.0, "texture_guard": 0.3},
    ),
}


class Rename(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        value = " ".join(value.split())
        if not value:
            raise ValueError("Enter a project name.")
        return value


class Preset(BaseModel):
    name: Literal["Portrait", "Pet", "Object", "Ornament", "Custom"]
    expected_revision: int | None = None


class Repair(BaseModel):
    reset_settings: bool = False


@router.get("")
def project_list():
    return {"projects": project_store.all_projects()}


@router.get("/deleted")
def deleted_projects():
    with storage.maintenance_lock:
        return {"projects": storage.recovery_projects()}


@router.post("/upload")
async def upload_project(image: UploadFile, model_id: str | None = None):
    if model_id is not None and model_id not in MODEL_REGISTRY:
        raise editing.EditingError("Unknown depth model.")
    if model_id is not None and not availability(model_id)["selectable"]:
        raise editing.EditingError(availability(model_id)["setup_reason"])
    content = await image.read(settings.max_upload_bytes + 1)
    try:
        info = sessions.create_session(content, image.filename or "New project")
    except sessions.InvalidImageError as exc:
        raise editing.EditingError(str(exc)) from exc
    selected = model_id or resolve_default_model(depth.select_device())
    sessions.write_params(info.session_id, ReliefParams(depth_model=selected))
    project_store.write(
        info.session_id,
        {
            "version": 1,
            "name": Path(image.filename or "New project").stem,
            "created_at": project_store.timestamp(),
            "preset": "Custom",
        },
    )
    sessions.write_status(info.session_id, model_id=selected)
    if model_id:
        depth.start_inference_job(info.session_id, model_id)
    return project_store.document(info.session_id)


@router.get("/{sid}")
def project(sid: str):
    return project_store.document(sid)


@router.patch("/{sid}")
def rename(sid: str, request: Rename):
    with editing.lock_for(sid):
        value = project_store.read(sid)
        value["name"] = request.name
        project_store.write(sid, value)
    return project(sid)


@router.post("/{sid}/repair")
def repair(sid: str, request: Repair):
    return project_store.repair(sid, request.reset_settings)


@router.post("/{sid}/retry")
def retry(sid: str):
    params = sessions.read_params(sid)
    if not availability(params.depth_model)["selectable"]:
        raise editing.EditingError(availability(params.depth_model)["setup_reason"])
    depth.start_inference_job(sid, params.depth_model)
    return {"status": "processing"}


@router.post("/{sid}/preset")
def apply_preset(sid: str, request: Preset):
    with editing.lock_for(sid):
        state = editing.read_state(sid)
        editing._check_revision(state, request.expected_revision)
        saved = project_store.read(sid)
        if request.name != "Custom":
            shape, surface = PRESETS[request.name]
            params = sessions.read_params(sid)
            # Save the reversal first, before touching either settings file.
            saved["preset_undo"] = {
                "params": {k: getattr(params, k) for k in shape},
                "editor": {k: state[k] for k in surface},
            }
            saved["preset"] = request.name
            project_store.write(sid, saved)
            sessions.write_params(sid, params.model_copy(update=shape))
            editing.update_settings(sid, editing.EditorSettings(**surface))
        else:
            saved["preset"] = "Custom"
            project_store.write(sid, saved)
    return {
        "project": project(sid),
        "params": sessions.read_params(sid),
        "editor": editing.public_state(sid, sessions.read_params(sid).depth_model),
    }


@router.post("/{sid}/undo-preset")
def undo_preset(sid: str):
    with editing.lock_for(sid):
        saved = project_store.read(sid)
        previous = saved.get("preset_undo")
        if not previous:
            raise editing.EditingError("No preset change to undo.")
        sessions.write_params(sid, sessions.read_params(sid).model_copy(update=previous["params"]))
        editing.update_settings(sid, editing.EditorSettings(**previous["editor"]))
        saved.update(preset="Custom", preset_undo=None)
        project_store.write(sid, saved)
    return {
        "project": project(sid),
        "params": sessions.read_params(sid),
        "editor": editing.public_state(sid, sessions.read_params(sid).depth_model),
    }


@router.delete("/{sid}")
def delete_project(sid: str):
    with editing.lock_for(sid), storage.maintenance_lock:
        root = sessions.session_dir(sid)
        project_store.document(sid)
        with jobs._lock:
            exporting = any(
                job.session_id == sid and job.status == "processing" for job in jobs._jobs.values()
            )
        if storage.is_leased(sid) or depth.is_processing(sid) or exporting:
            raise editing.RevisionConflict(
                "This project is still processing. Wait for it to finish before deleting."
            )
        try:
            destination = contained_path(storage.recovery_root(), sid)
        except UnsafePathError as exc:
            raise editing.EditingError("The recovery folder is linked or unsafe.") from exc
        if destination.exists():
            raise editing.EditingError("A recoverable copy already exists. Restore it first.")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            root.rename(destination)
        except OSError as exc:
            raise editing.RevisionConflict(
                "The project is in use. Close its files and retry."
            ) from exc
    return {"deleted": True, "recoverable": True, "id": sid}


@router.post("/{sid}/restore")
def restore_project(sid: str):
    with editing.lock_for(sid), storage.maintenance_lock:
        target = sessions.session_dir(sid)
        try:
            source = contained_path(storage.recovery_root(), sid)
        except UnsafePathError as exc:
            raise editing.EditingError("The recovery folder is linked or unsafe.") from exc
        if not source.is_dir() or target.exists():
            raise editing.EditingError("The deleted project cannot be restored to this location.")
        try:
            source.rename(target)
        except OSError as exc:
            raise editing.RevisionConflict(
                "The recovery copy is in use. Close its files and retry."
            ) from exc
    return project(sid)
