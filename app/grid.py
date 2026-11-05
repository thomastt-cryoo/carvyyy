"""M2 physical/grid planning. Sampling density never defines the stock dimensions."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.schemas import ReliefParams


@dataclass(frozen=True)
class GridPlan:
    rows: int
    columns: int
    image_width_mm: float
    image_height_mm: float
    frame_mm: float

    @property
    def width_mm(self) -> float:
        return self.image_width_mm + 2 * self.frame_mm

    @property
    def height_mm(self) -> float:
        return self.image_height_mm + 2 * self.frame_mm

    @property
    def triangles(self) -> int:
        perimeter = 2 * self.rows + 2 * self.columns - 4
        return 2 * (self.rows - 1) * (self.columns - 1) + 3 * perimeter

    @property
    def vertices(self) -> int:
        return self.rows * self.columns + 2 * self.rows + 2 * self.columns - 3

    def axes(self) -> tuple[np.ndarray, np.ndarray]:
        return (
            physical_axis(self.columns, self.image_width_mm, self.frame_mm),
            physical_axis(self.rows, self.image_height_mm, self.frame_mm)[::-1],
        )


def physical_axis(count: int, content_mm: float, frame_mm: float) -> np.ndarray:
    """Include both frame boundaries exactly while keeping a fixed vertex budget."""
    if count < 2:
        raise ValueError("A relief grid needs at least two vertices on each side.")
    if frame_mm <= 0:
        return np.linspace(0, content_mm, count)
    if count < 4:
        raise ValueError("A framed grid needs at least four vertices on each side.")
    lengths = np.array([frame_mm, content_mm, frame_mm])
    quotas = (count - 4) * lengths / lengths.sum()
    intervals = np.floor(quotas).astype(int) + 1
    remainder = count - 1 - intervals.sum()
    for index in np.argsort(-(quotas - np.floor(quotas)))[:remainder]:
        intervals[index] += 1
    edges = [0.0, frame_mm, frame_mm + content_mm, content_mm + 2 * frame_mm]
    return np.concatenate(
        [np.linspace(edges[i], edges[i + 1], intervals[i] + 1)[:-1] for i in range(3)]
        + [np.array([edges[-1]])]
    )


def plan_grid(shape: tuple[int, int], params: ReliefParams, long_side: int) -> GridPlan:
    height, width = shape
    if height < 1 or width < 1 or long_side < 4:
        raise ValueError("Invalid image or grid dimensions.")
    image_height = params.model_width_mm * height / width
    part_width = params.total_width_mm
    part_height = image_height + 2 * params.border_frame_mm
    minimum = 4 if params.border_frame_mm > 0 else 2
    scale = (long_side - 1) / max(part_width, part_height)
    columns = min(long_side, max(minimum, round(part_width * scale) + 1))
    rows = min(long_side, max(minimum, round(part_height * scale) + 1))
    return GridPlan(rows, columns, params.model_width_mm, image_height, params.border_frame_mm)


def plan_for_shape(
    shape: tuple[int, int], params: ReliefParams, image_shape: tuple[int, int] | None = None
) -> GridPlan:
    """Mesh an already sampled heightmap; actual sessions always supply source dimensions.

    The inferred fallback preserves the original public pure-function API and old
    tests that pass an already frame-padded array without source-image metadata.
    """
    rows, columns = shape
    if image_shape is None:
        pad = round(columns * params.border_frame_mm / params.total_width_mm)
        image_shape = (max(1, rows - 2 * pad), max(1, columns - 2 * pad))
    image_height = params.model_width_mm * image_shape[0] / image_shape[1]
    return GridPlan(rows, columns, params.model_width_mm, image_height, params.border_frame_mm)
