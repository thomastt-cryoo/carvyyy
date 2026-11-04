"""Render surface-setting comparisons from the already verified real depth arrays."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from app import heightmap
from app.schemas import ReliefParams

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/m1/evidence"


def main() -> None:
    results = json.loads((EVIDENCE / "results-online-da2-small.json").read_text())
    variants = [
        ("Default", {}),
        ("No smoothing", {"smoothing": 0}),
        ("Smoothing 5", {"smoothing": 5}),
        ("No fine detail", {"detail_blend": 0}),
        ("Fine detail 0.7", {"detail_blend": 0.7}),
    ]
    for case in results["cases"]:
        sid = case["session_id"]
        depth = np.load(ROOT / f"data/sessions/{sid}/raw_depth_da2-small.npy")
        source = Image.open(EVIDENCE / f"inputs/{case['case']}.png").convert("RGB")
        luma = heightmap.luma_at_shape(source, depth.shape)
        sheet = Image.new("RGB", (1250, 300), "white")
        draw = ImageDraw.Draw(sheet)
        for column, (label, changes) in enumerate(variants):
            params = ReliefParams(**(case["params"] | changes))
            h = heightmap.compute_heightmap(depth, luma, params, target_long_side=1024)
            shade = heightmap.hillshade(h, params.total_width_mm, params.relief_height_mm)
            image = Image.fromarray((shade * 255).astype("uint8")).convert("RGB")
            image.thumbnail((244, 260))
            sheet.paste(image, (column * 250 + (250 - image.width) // 2, 30))
            draw.text((column * 250 + 8, 8), label, fill="black")
        path = EVIDENCE / f"{case['case']}-surface-comparison.jpg"
        sheet.save(path, quality=93)
        print(path.name)


if __name__ == "__main__":
    main()
