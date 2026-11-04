"""Fetch openly available photographs and create a declared synthetic ornament."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/m1/evidence/inputs"
BASE = "https://raw.githubusercontent.com/scikit-image/scikit-image/v0.19.3/skimage/data/"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sources = [
        ("portrait", "astronaut.png", "NASA / Eileen Collins; public domain"),
        ("pet", "chelsea.png", "Stefan van der Walt; CC0"),
        ("object", "coffee.png", "Rachel Michetti; CC0"),
        ("complex", "rocket.jpg", "SpaceX / DSCOVR launch; public domain"),
    ]
    records = []
    for name, filename, credit in sources:
        path = OUT / f"{name}.png"
        url = BASE + filename
        if not path.exists():
            raw = OUT / filename
            urllib.request.urlretrieve(url, raw)
            with Image.open(raw) as image:
                image.convert("RGB").save(path)
            if raw != path:
                raw.unlink()
        records.append({"id": name, "url": url, "credit": credit, "kind": "photograph"})

    # A lit decorative medallion, a reproducible fixture rather than a photograph.
    y, x = np.mgrid[-1:1:512j, -1:1:512j]
    r, angle = np.hypot(x, y), np.arctan2(y, x)
    mask = r < 0.86
    z = np.maximum(0, 1 - (r / 0.86) ** 2) * 0.15
    z += np.exp(-(((r - 0.6) / 0.05) ** 2)) * 0.1
    z += np.exp(-(((r - 0.32 - 0.06 * np.cos(angle * 8)) / 0.08) ** 2)) * 0.2
    z = np.where(mask, z, 0)
    dy, dx = np.gradient(z, 2 / 512)
    light = np.clip((-dx * 0.4 - dy * 0.5 + 0.7) / np.sqrt(dx**2 + dy**2 + 1), 0, 1)
    rgb = np.full((512, 512, 3), 68.0)
    rgb[mask] = (light[mask, None] * 0.8 + 0.2) * np.array([218, 185, 128])
    Image.fromarray(rgb.astype("uint8")).save(OUT / "ornament.png")
    records.append(
        {
            "id": "ornament",
            "credit": "Project-generated procedural medallion",
            "kind": "synthetic shaded fixture",
            "url": None,
        }
    )
    for row in records:
        path = OUT / f"{row['id']}.png"
        row.update(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    (OUT / "sources.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
