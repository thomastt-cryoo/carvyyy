"""In-memory export job tracking (SPEC Sec4 /api/jobs/*).

Job status is transient; saved sessions, editor journals and export files survive
app restarts. Each job owns a separate file so later edits cannot replace its download.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from app import cnc, editing, meshing, pipeline, storage
from app.resources import require_export_plan
from app.schemas import ReliefParams
from app.sessions import read_meta, session_file

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._ -]")
MAX_INSPECTION_TRIANGLES = 2_250_000
INSPECTION_LIMIT_REASON = (
    "This mesh exceeds the in-app inspection limit. Download it to inspect in your CAM software, "
    "or choose a smaller export for in-app inspection."
)


@dataclass
class ExportJob:
    job_id: str
    session_id: str
    status: str = "processing"  # "processing" | "ready" | "error"
    error: str | None = None
    file_path: Path | None = None
    preview_path: Path | None = None
    inspection_note: str | None = None
    surface: dict | None = None
    filename: str | None = None
    elapsed_s: float | None = None
    # Export summary (SPEC §5.4): triangle count, file size, physical dims.
    triangles: int | None = None
    file_bytes: int | None = None
    width_mm: float | None = None
    height_mm: float | None = None
    # Coarse stage-based progress (SPEC §4's `progress?`). A true ETA isn't honest --
    # the big steps are single opaque library calls -- but stage boundaries are.
    progress: float = 0.0  # 0..1
    stage: str | None = None
    editor_snapshot: dict | None = None


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="export")
_lock = threading.RLock()
_jobs: dict[str, ExportJob] = {}


def get_job(job_id: str) -> ExportJob | None:
    with _lock:
        return _jobs.get(job_id)


def start_export_job(session_id: str, params: ReliefParams) -> str:
    job_id = uuid.uuid4().hex
    job = ExportJob(job_id=job_id, session_id=session_id)
    with editing.lock_for(session_id):
        job.editor_snapshot = editing.read_state(session_id)
        with _lock:
            completed = [key for key, old in _jobs.items() if old.status != "processing"]
            for key in completed[:-127]:
                _jobs.pop(key, None)  # Completed files remain in their protected sessions.
            _jobs[job_id] = job
    _executor.submit(_run_export, job, params)
    return job_id


def _fmt_dim_mm(mm: float) -> str:
    rounded = round(mm, 1)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded)


def _export_stem(original_filename: str) -> str:
    """Base the export filename on the uploaded photo's name, not the session id."""
    stem = Path(original_filename).stem.strip()
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", stem)
    return cleaned or "photo2relief"


def _set_progress(job: ExportJob, progress: float, stage: str) -> None:
    with _lock:
        job.progress = progress
        job.stage = stage


def _run_export(job: ExportJob, params: ReliefParams) -> None:
    with storage.session_lease(job.session_id):
        _run_export_leased(job, params)


def _run_export_leased(job: ExportJob, params: ReliefParams) -> None:
    started = time.monotonic()
    try:
        # Weights are rough shares of wall time at resolution=1024 on the dev box;
        # watertight validation dominates, serialization of ~100 MB comes second.
        _set_progress(job, 0.05, "loading depth")
        meta = read_meta(job.session_id)
        image_shape = (meta["height"], meta["width"])
        require_export_plan(image_shape, params)

        _set_progress(job, 0.15, "shaping heightmap")
        h, image_shape = pipeline.render_heightmap(
            job.session_id, params, params.resolution, state=job.editor_snapshot
        )
        _set_progress(job, 0.3, "building mesh")
        mesh = meshing.build_export_mesh(
            h,
            params,
            on_stage=lambda frac, stage: _set_progress(job, frac, stage),
            image_shape=image_shape,
        )
        _set_progress(job, 0.76, "measuring surface")
        surface = cnc.surface_report(mesh)
        _set_progress(job, 0.8, f"writing {params.output_format.upper()}")
        data = meshing.export_bytes(mesh, params.output_format)

        # Filename encodes the stock size (matches the UI's "Stock" readout): full
        # width/height including the border frame, plus thickness (base + relief).
        model_height_mm = (
            params.model_width_mm * image_shape[0] / image_shape[1] + 2 * params.border_frame_mm
        )
        thickness_mm = params.base_thickness_mm + params.relief_height_mm
        stem = _export_stem(read_meta(job.session_id).get("original_filename") or "")
        filename = (
            f"{stem}_"
            f"{_fmt_dim_mm(params.total_width_mm)}x{_fmt_dim_mm(model_height_mm)}"
            f"x{_fmt_dim_mm(thickness_mm)}mm."
            f"{params.output_format}"
        )
        out_path = session_file(job.session_id, "exports", job.job_id, filename)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = out_path.with_suffix(".tmp")
        try:
            temporary.write_bytes(data)
            temporary.replace(out_path)
        finally:
            temporary.unlink(missing_ok=True)
        file_bytes = len(data)
        del data
        preview_path, inspection_note = None, None
        if len(mesh.faces) <= MAX_INSPECTION_TRIANGLES:
            _set_progress(job, 0.95, "preparing inspection")
            target = session_file(job.session_id, "exports", job.job_id, "inspection.glb")
            try:
                target.write_bytes(meshing.export_bytes(mesh, "glb"))
                preview_path = target
            except (OSError, MemoryError, ValueError):
                inspection_note = (
                    "The export is ready. Its in-app inspection copy could not be saved."
                )
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
        else:
            inspection_note = INSPECTION_LIMIT_REASON

        with _lock:
            # Endpoint readers don't take this lock, so publish status *last*: they must
            # never observe "ready" while file_path/filename are still None.
            job.preview_path = preview_path
            job.inspection_note = inspection_note
            job.surface = surface
            job.file_path = out_path
            job.filename = filename
            job.triangles = len(mesh.faces)
            job.file_bytes = file_bytes
            job.width_mm = params.total_width_mm
            job.height_mm = round(model_height_mm, 2)
            job.elapsed_s = round(time.monotonic() - started, 3)
            job.progress = 1.0
            job.stage = "done"
            job.status = "ready"
    except Exception as exc:  # noqa: BLE001 - surface any failure via job status
        with _lock:
            job.error = (
                "Not enough memory to finish this export. Choose 512 resolution "
                "or close other applications and retry."
                if isinstance(exc, MemoryError)
                else str(exc)
            )
            job.elapsed_s = round(time.monotonic() - started, 3)
            job.status = "error"
