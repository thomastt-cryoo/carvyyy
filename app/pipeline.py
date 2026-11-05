"""One M2 document pipeline shared by heightmap, GLB and both mesh exports."""

from __future__ import annotations

import threading

from PIL import Image

from app import editing, heightmap
from app.schemas import ReliefParams
from app.sessions import SOURCE_IMAGE_NAME, read_meta, session_dir

_render_slots = threading.BoundedSemaphore(2)


def render_heightmap(
    sid: str,
    params: ReliefParams,
    long_side: int,
    *,
    state: dict | None = None,
    original: bool = False,
):
    with _render_slots:
        return _render_heightmap(sid, params, long_side, state=state, original=original)


def _render_heightmap(sid, params, long_side, *, state=None, original=False):
    if original:
        state = editing.read_state(sid)
        state.update(
            depth_source="ai",
            histories={},
            mask_enabled=False,
            sculpt_strength=0.0,
            texture_guard=0.0,
        )
    working, mask, state = editing.working_inputs(sid, params.depth_model, state)
    meta = read_meta(sid)
    shape = (meta["height"], meta["width"])
    with Image.open(session_dir(sid) / SOURCE_IMAGE_NAME) as image:
        luma = heightmap.luma_at_shape(image.convert("RGB"), working.shape)
    result = heightmap.compute_heightmap(
        working,
        luma,
        params,
        long_side,
        image_shape=shape,
        mask=mask if state["mask_enabled"] else None,
        feather_mm=state["mask_feather_mm"],
        transition_mm=state["mask_transition_mm"],
        sculpt_strength=state["sculpt_strength"],
        texture_guard=state["texture_guard"],
    )
    return result, shape
