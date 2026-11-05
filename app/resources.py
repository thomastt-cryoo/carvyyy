"""M2 conservative export preflight, before constructing any large mesh arrays."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import psutil

from app.config import settings
from app.grid import GridPlan, plan_grid
from app.schemas import ReliefParams


class ResourceLimitError(ValueError):
    pass


@dataclass(frozen=True)
class ExportPlan:
    grid: GridPlan
    triangles: int
    output_triangles_estimate: int
    output_bytes_estimate: int
    memory_bytes_estimate: int
    memory_budget_bytes: int
    allowed: bool
    message: str

    def as_dict(self) -> dict:
        result = asdict(self)
        result["grid"].update(width_mm=self.grid.width_mm, height_mm=self.grid.height_mm)
        return result


def export_plan(
    image_shape: tuple[int, int],
    params: ReliefParams,
    *,
    available_bytes: int | None = None,
    budget_bytes: int | None = None,
) -> ExportPlan:
    grid = plan_grid(image_shape, params, params.resolution)
    faces = grid.triangles
    output_faces = max(4, round(faces * (1 - params.decimate_ratio)))
    output_bytes = (
        84 + 50 * output_faces
        if params.output_format == "stl"
        else grid.vertices * 100 + output_faces * 70
    )
    # Includes construction temporaries, trimesh edge validation, serialization and
    # decimation workspace. Whole-solid decimation cannot reduce initial peak RAM.
    memory_bytes = 64 * 1024**2 + grid.vertices * 240 + faces * 360
    if params.decimate_ratio:
        memory_bytes += grid.vertices * 120 + faces * 100
    available = psutil.virtual_memory().available if available_bytes is None else available_bytes
    configured = settings.export_memory_mb * 1024**2 if budget_bytes is None else budget_bytes
    budget = max(0, min(configured, int(available * settings.memory_fraction)))
    allowed = memory_bytes <= budget and faces <= settings.export_max_triangles
    message = (
        "Ready to export. Estimates are conservative; other applications also use memory."
        if allowed
        else f"This export needs about {memory_bytes / 1024**2:.0f} MB of working memory; "
        f"the current safety budget is {budget / 1024**2:.0f} MB. "
        "Choose a lower resolution or close other applications. Decimation reduces "
        "the file size, but still builds the full grid first."
    )
    return ExportPlan(
        grid, faces, output_faces, output_bytes, memory_bytes, budget, allowed, message
    )


def require_export_plan(image_shape: tuple[int, int], params: ReliefParams) -> ExportPlan:
    plan = export_plan(image_shape, params)
    if not plan.allowed:
        raise ResourceLimitError(plan.message)
    return plan
