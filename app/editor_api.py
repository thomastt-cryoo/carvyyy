"""M2 functional document API; browser controls remain separate from M3 design."""

from __future__ import annotations

import io
from typing import Literal

import numpy as np
from fastapi import APIRouter, UploadFile
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field

from app import editing, pipeline, segmentation, storage
from app.config import settings
from app.resources import export_plan
from app.schemas import ReliefParams
from app.sessions import SOURCE_IMAGE_NAME, read_meta, read_params, session_dir

router = APIRouter(prefix="/api/sessions/{sid}")
maintenance_router = APIRouter(prefix="/api/storage")


class HistoryAction(BaseModel):
    channel: Literal["depth", "mask"]
    action: Literal["undo", "redo", "reset"]
    expected_revision: int | None = Field(None, ge=0)


class AutoMask(BaseModel):
    method: Literal["auto", "grabcut", "u2netp"] = "auto"
    rectangle: list[float] | None = Field(None, min_length=4, max_length=4)
    expected_revision: int | None = Field(None, ge=0)


class CacheCleanup(BaseModel):
    dry_run: bool = True
    max_mb: float | None = Field(None, ge=0)
    retention_days: float | None = Field(None, ge=0)


class RestoreAI(BaseModel):
    expected_revision: int | None = Field(None, ge=0)


@maintenance_router.get("")
def storage_info():
    return storage.storage_summary()


@router.get("/segmentation")
def segmentation_status(sid: str):
    read_meta(sid)
    return segmentation.status()


@maintenance_router.post("/cleanup")
def clean_cache(request: CacheCleanup):
    return storage.cleanup_cache(**request.model_dump())


@router.get("/editor")
def editor_state(sid: str):
    return editing.public_state(sid, read_params(sid).depth_model)


@router.put("/editor")
def editor_settings(sid: str, change: editing.EditorSettings):
    editing.update_settings(sid, change)
    return editor_state(sid)


@router.post("/editor/stroke")
def editor_stroke(sid: str, stroke: editing.Stroke):
    editing.add_stroke(sid, read_params(sid).depth_model, stroke)
    return editor_state(sid)


@router.post("/editor/history")
def editor_history(sid: str, command: HistoryAction):
    editing.history_action(
        sid,
        read_params(sid).depth_model,
        command.channel,
        command.action,
        command.expected_revision,
    )
    return editor_state(sid)


@router.post("/editor/restore-ai")
def restore_ai(sid: str, request: RestoreAI):
    editing.restore_ai(sid, read_params(sid).depth_model, request.expected_revision)
    return editor_state(sid)


@router.post("/editor/automatic-mask")
def editor_auto_mask(sid: str, request: AutoMask):
    result = editing.automatic_mask(
        sid,
        read_params(sid).depth_model,
        rectangle=request.rectangle,
        method=request.method,
        expected_revision=request.expected_revision,
    )
    return {**editor_state(sid), "segmentation": result}


@router.post("/depth/import")
async def import_depth(
    sid: str,
    file: UploadFile,
    white_is_far: bool = False,
    alignment: Literal["match", "stretch"] = "match",
    expected_revision: int | None = None,
):
    data = await file.read(settings.max_upload_bytes + 1)
    editing.import_depth(
        sid,
        data,
        file.filename or "depth",
        white_is_far=white_is_far,
        alignment=alignment,
        expected_revision=expected_revision,
    )
    return editor_state(sid)


@router.get("/depth/export")
def export_depth(
    sid: str,
    source: Literal["ai", "imported", "working"] = "working",
    format: Literal["png16", "npy"] = "png16",
):
    params = read_params(sid)
    state = editing.read_state(sid)
    array = (
        editing.working_inputs(sid, params.depth_model, state)[0]
        if source == "working"
        else editing.base_depth(sid, params.depth_model, state, source=source)
    )
    extension = "png" if format == "png16" else "npy"
    return Response(
        editing.encode_depth(array, format),
        media_type="image/png" if format == "png16" else "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="depth-{source}.{extension}"',
            "X-Depth-Convention": "higher-is-nearer",
            "X-Depth-Precision": "16-bit" if format == "png16" else "float32",
        },
    )


@router.get("/editor/image")
def editor_image(
    sid: str, view: Literal["photo", "working", "ai", "mask", "processed"] = "working"
):
    if view == "photo":
        with Image.open(session_dir(sid) / SOURCE_IMAGE_NAME) as source:
            photo = source.convert("RGB")
            photo.thumbnail((768, 768))
            encoded = io.BytesIO()
            photo.save(encoded, format="PNG")
        return Response(encoded.getvalue(), media_type="image/png")
    params = read_params(sid)
    working, mask, state = editing.working_inputs(sid, params.depth_model)
    if view == "mask":
        array = mask
    elif view == "ai":
        array = editing.base_depth(sid, params.depth_model, state, source="ai")
    elif view == "processed":
        # The editing canvas stays aligned with the photograph, without a stock frame.
        array, _ = pipeline.render_heightmap(
            sid, params.model_copy(update={"border_frame_mm": 0}), 512, state=state
        )
    else:
        array = working
    output = io.BytesIO()
    Image.fromarray(np.rint(np.clip(array, 0, 1) * 255).astype(np.uint8)).save(output, format="PNG")
    return Response(
        output.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"}
    )


@router.post("/export-plan")
def plan_export(sid: str, params: ReliefParams):
    meta = read_meta(sid)
    return export_plan((meta["height"], meta["width"]), params).as_dict()
