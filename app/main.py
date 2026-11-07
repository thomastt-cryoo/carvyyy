"""FastAPI app: static frontend + /api routes."""

from __future__ import annotations

import io
import logging
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from app import (  # noqa: F401
    checkpoints,
    depth,
    editing,
    heightmap,
    jobs,
    meshing,
    pipeline,
    storage,
)
from app.config import MODEL_REGISTRY, model_use_allowed, resolve_default_model, settings
from app.editor_api import maintenance_router
from app.editor_api import router as editor_router
from app.model_status import availability
from app.projects_api import router as project_router
from app.resources import ResourceLimitError, require_export_plan
from app.schemas import (
    ErrorResponse,
    ExportJobResponse,
    HealthResponse,
    ImageInfo,
    JobStatusResponse,
    ModelInfo,
    ModelsResponse,
    ReliefParams,
    SessionCreateResponse,
    StatusResponse,
)
from app.sessions import (
    SOURCE_IMAGE_NAME,
    InvalidImageError,
    SessionNotFoundError,
    create_session,
    read_meta,
    read_params,
    session_file,
    write_params,
)

logger = logging.getLogger("photo2relief")

PREVIEW_MAX_PX = 1024  # SPEC §4: preview PNG capped at ≤ 1024 px
PREVIEW_MESH_MAX_PX = 512  # Detailed preview; export inspection serves the validated job mesh.
_mesh_preview_slots = threading.BoundedSemaphore(2)


def _error(status_code: int, error: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(error=error, detail=detail).model_dump(),
    )


def _not_found(session_id: str) -> JSONResponse:
    return _error(404, "not_found", f"No session {session_id}")


class ProjectFileResponse(FileResponse):
    """Protect the file until ASGI has finished sending it."""

    def __init__(self, sid: str, parts: tuple[str, ...], **kwargs):
        self.sid = sid
        self.parts = parts
        super().__init__(session_file(sid, *parts), **kwargs)

    async def __call__(self, scope, receive, send):
        with storage.session_lease(self.sid):
            try:
                path = session_file(self.sid, *self.parts)
                if not path.is_file():
                    raise SessionNotFoundError(self.sid)
            except SessionNotFoundError:
                await _error(404, "not_found", "This project file is unavailable.")(
                    scope, receive, send
                )
                return
            await super().__call__(scope, receive, send)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # SPEC §5.1: log the chosen device and model loudly at startup.
    cuda_available, mps_available, torch_version = _torch_info()
    device = depth.select_device()
    logger.warning(
        "photo2relief starting: device=%s cuda_available=%s mps_available=%s torch=%s "
        "default_model=%s (models lazy-load on first inference)",
        device,
        cuda_available,
        mps_available,
        torch_version,
        resolve_default_model(device),
    )
    if settings.auto_clean_cache:
        storage.cleanup_cache(dry_run=False)
    yield


app = FastAPI(title="Photo2Relief", lifespan=_lifespan)
app.include_router(editor_router)
app.include_router(maintenance_router)
app.include_router(project_router)


@app.exception_handler(editing.EditingError)
async def editing_error(request, exc):
    if isinstance(exc, editing.DepthNotReadyError):
        return _error(409, "depth_not_ready", str(exc))
    if isinstance(exc, editing.RevisionConflict):
        return _error(409, "revision_conflict", str(exc))
    return _error(400, "editing_error", str(exc))


@app.exception_handler(SessionNotFoundError)
async def missing_editor_session(request, exc):
    return _error(404, "not_found", "The editing session no longer exists.")


@app.exception_handler(ResourceLimitError)
async def resource_error(request, exc):
    return _error(422, "resource_limit", str(exc))


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _torch_info() -> tuple[bool, bool, str | None]:
    """(cuda_available, mps_available, torch_version)."""
    try:
        import torch
    except ImportError:
        return False, False, None
    return torch.cuda.is_available(), depth._mps_available(torch), torch.__version__


@app.get("/api/launcher/status")
async def launcher_status():
    return {"can_shutdown": False}


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    cuda_available, mps_available, torch_version = _torch_info()
    return HealthResponse(
        status="ok",
        device=depth.select_device(),
        cuda_available=cuda_available,
        mps_available=mps_available,
        torch_version=torch_version,
        model_loaded=depth.active_model_id() is not None,
        active_model=depth.active_model_id(),
    )


@app.post(
    "/api/sessions",
    response_model=SessionCreateResponse,
    responses={400: {"model": ErrorResponse}},
)
async def create_session_endpoint(image: UploadFile):
    data = await image.read(settings.max_upload_bytes + 1)
    try:
        info = create_session(data, image.filename or "upload")
    except InvalidImageError as exc:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(error="invalid_image", detail=str(exc)).model_dump(),
        )

    # Run depth inference for the default model in the background; client polls /status.
    # Persist params.json with that same model_id up front -- ReliefParams()'s own
    # default assumes CUDA, which would silently disagree with a CPU session's actual
    # model and make every preview request 409 until the user explicitly picks one.
    model_id = resolve_default_model(depth.select_device())
    write_params(info.session_id, ReliefParams(depth_model=model_id))
    depth.start_inference_job(info.session_id, model_id)

    return SessionCreateResponse(
        session_id=info.session_id,
        image=ImageInfo(w=info.width, h=info.height),
        status="processing",
    )


@app.get(
    "/api/sessions/{session_id}/status",
    response_model=StatusResponse,
    responses={404: {"model": ErrorResponse}},
)
async def session_status(session_id: str):
    try:
        meta = read_meta(session_id)
    except SessionNotFoundError:
        return _not_found(session_id)
    return StatusResponse(
        status=meta.get("status", "created"),
        model_id=meta.get("model_id"),
        device=meta.get("device"),
        elapsed_s=meta.get("elapsed_s"),
        error=meta.get("error"),
        eta_s=depth.estimate_inference_s(meta.get("model_id"), meta.get("device")),
        width=meta.get("width"),
        height=meta.get("height"),
        original_filename=meta.get("original_filename"),
    )


@app.get(
    "/api/sessions/{session_id}/source",
    responses={404: {"model": ErrorResponse}},
)
async def session_source(session_id: str):
    """The normalized session image (upload-area thumbnail; works across resume)."""
    try:
        path = session_file(session_id, SOURCE_IMAGE_NAME)
    except SessionNotFoundError:
        return _not_found(session_id)
    if not path.exists():
        return _not_found(session_id)
    cutout = session_file(session_id, "original-cutout.png")
    return ProjectFileResponse(
        session_id, ((cutout if cutout.exists() else path).name,), media_type="image/png"
    )


@app.get(
    "/api/sessions/{session_id}/params",
    response_model=ReliefParams,
    responses={404: {"model": ErrorResponse}},
)
async def get_params(session_id: str):
    try:
        return read_params(session_id)
    except SessionNotFoundError:
        return _not_found(session_id)


@app.put(
    "/api/sessions/{session_id}/params",
    response_model=ReliefParams,
    responses={404: {"model": ErrorResponse}},
)
async def put_params(session_id: str, params: ReliefParams):
    try:
        meta = read_meta(session_id)
    except SessionNotFoundError:
        return _not_found(session_id)

    if params.depth_model != meta.get("model_id") and not model_use_allowed(params.depth_model):
        return _error(
            403,
            "model_authorization_required",
            "This model needs separate commercial authorization. Choose DA2 Small.",
        )
    if params.depth_model != "da2-small" and params.depth_model != meta.get("model_id"):
        return _error(422, "model_unavailable", "Choose Depth Anything V2 Small.")
    write_params(session_id, params)
    # Changing the depth model requires (cached) re-inference; everything else in
    # ReliefParams is a cheap heightmap re-run and needs no backend work here.
    if params.depth_model != meta.get("model_id"):
        depth.start_inference_job(session_id, params.depth_model)
    return params


def _encode_png_l(render: np.ndarray) -> bytes:
    img = Image.fromarray((np.clip(render, 0.0, 1.0) * 255).astype(np.uint8), mode="L")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@app.get(
    "/api/sessions/{session_id}/preview/heightmap",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def preview_heightmap(session_id: str, grayscale: bool = False, original: bool = False):
    try:
        params = read_params(session_id)
    except SessionNotFoundError:
        return _not_found(session_id)

    h, image_shape = pipeline.render_heightmap(
        session_id, params, PREVIEW_MAX_PX, original=original
    )
    part_height = (
        params.model_width_mm * image_shape[0] / image_shape[1] + 2 * params.border_frame_mm
    )
    render = (
        h
        if grayscale
        else heightmap.hillshade(
            h, params.total_width_mm, params.relief_height_mm, model_height_mm=part_height
        )
    )
    return Response(content=_encode_png_l(render), media_type="image/png")


@app.get("/api/models", response_model=ModelsResponse)
async def list_models() -> ModelsResponse:
    """Registry contents for the UI's depth-model dropdown (SPEC §5.1.1)."""
    default_model = "da2-small"
    return ModelsResponse(
        models=[
            ModelInfo(
                model_id=s.model_id,
                role=s.role,
                license=s.license,
                available=s.available,
                distribution_approved=s.distribution_approved,
                authorization_required=not s.distribution_approved,
                use_allowed=model_use_allowed(s.model_id),
                platform_available=(s.backend != "da3" or sys.platform != "darwin"),
                availability_reason=(
                    "The DA3 worker is not supported on macOS/MPS."
                    if s.backend == "da3" and sys.platform == "darwin"
                    else None
                ),
                **availability(s.model_id),
            )
            for s in MODEL_REGISTRY.values()
            if s.model_id == "da2-small"
        ],
        default_model=default_model,
        default_params=ReliefParams(depth_model=default_model),
    )


@app.post(
    "/api/sessions/{session_id}/preview/mesh",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def preview_mesh(
    session_id: str,
    params: ReliefParams,
    original: bool = False,
    resolution: int = Query(256, ge=256, le=PREVIEW_MESH_MAX_PX),
):
    """Responsive 256/512 GLB. Export inspection uses the validated job artifact."""
    if resolution not in (256, 512):
        return _error(422, "invalid_resolution", "Preview resolution must be 256 or 512.")
    try:
        read_meta(session_id)
    except SessionNotFoundError:
        return _not_found(session_id)

    with _mesh_preview_slots:
        h, image_shape = pipeline.render_heightmap(
            session_id, params, resolution, original=original
        )
        mesh = meshing.build_relief_mesh(h, params, image_shape=image_shape)
        return Response(content=meshing.export_bytes(mesh, "glb"), media_type="model/gltf-binary")


@app.post(
    "/api/sessions/{session_id}/export",
    response_model=ExportJobResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def export_session(session_id: str, params: ReliefParams):
    try:
        read_meta(session_id)
    except SessionNotFoundError:
        return _not_found(session_id)

    state = editing.read_state(session_id)
    editing.base_depth(session_id, params.depth_model, state)
    meta = read_meta(session_id)
    require_export_plan((meta["height"], meta["width"]), params)

    write_params(session_id, params)
    job_id = jobs.start_export_job(session_id, params)
    return ExportJobResponse(job_id=job_id)


@app.get(
    "/api/jobs/{job_id}",
    response_model=JobStatusResponse,
    responses={404: {"model": ErrorResponse}},
)
async def job_status(job_id: str):
    job = jobs.get_job(job_id)
    if job is None:
        return _error(404, "not_found", f"No job {job_id}")
    return JobStatusResponse(
        status=job.status,
        error=job.error,
        download_url=f"/api/jobs/{job_id}/download" if job.status == "ready" else None,
        preview_url=f"/api/jobs/{job_id}/preview"
        if job.status == "ready" and job.preview_path
        else None,
        inspection_note=job.inspection_note,
        surface=job.surface,
        progress=job.progress,
        stage=job.stage,
        triangles=job.triangles,
        file_bytes=job.file_bytes,
        width_mm=job.width_mm,
        height_mm=job.height_mm,
    )


@app.get(
    "/api/jobs/{job_id}/download",
    responses={404: {"model": ErrorResponse}},
)
async def job_download(job_id: str):
    job = jobs.get_job(job_id)
    if job is None or job.status != "ready" or job.file_path is None:
        return _error(404, "not_found", f"No completed job {job_id}")
    media_type = "application/sla" if job.filename.endswith(".stl") else "model/obj"
    return ProjectFileResponse(
        job.session_id,
        ("exports", job.job_id, job.filename),
        media_type=media_type,
        filename=job.filename,
    )


@app.get("/api/jobs/{job_id}/preview")
def job_preview(job_id: str):
    job = jobs.get_job(job_id)
    if job is None or job.status != "ready" or job.preview_path is None:
        return _error(404, "not_found", f"No completed inspection for {job_id}")
    return ProjectFileResponse(
        job.session_id, ("exports", job.job_id, "inspection.glb"), media_type="model/gltf-binary"
    )


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
