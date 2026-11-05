"""Explicit authored correction of the real cat example, separate from automatic results."""

import hashlib
import json
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/m2/evidence/pet"


def main():
    rows = json.loads((OUT.parent / "sessions.json").read_text())
    row = next(row for row in rows if row["case"] == "pet")
    base = f"/api/sessions/{row['session_id']}"
    client = httpx.Client(base_url="http://127.0.0.1:8097", timeout=120)

    def request(method, path, **kwargs):
        response = client.request(method, base + path, **kwargs)
        response.raise_for_status()
        return response

    strokes = [
        {
            "channel": "depth",
            "tool": "smooth",
            "points": [[0.07, 0.70], [0.20, 0.77], [0.33, 0.83]],
            "radius": 0.08,
            "strength": 0.9,
        },
        {
            "channel": "mask",
            "tool": "remove",
            "points": [[0.04, 0.72], [0.14, 0.83], [0.24, 0.91]],
            "radius": 0.085,
            "strength": 1,
        },
        {
            "channel": "mask",
            "tool": "remove",
            "points": [[0.02, 0.96], [0.32, 0.96]],
            "radius": 0.07,
            "strength": 1,
        },
    ]
    original = request("GET", "/depth/export?source=ai&format=npy").content
    request("POST", "/editor/restore-ai", json={})
    request("POST", "/editor/automatic-mask", json={"method": "u2netp"})
    request(
        "PUT",
        "/editor",
        json={
            "mask_feather_mm": 0.8,
            "mask_transition_mm": 4.0,
            "sculpt_strength": 0.45,
            "texture_guard": 0.8,
        },
    )
    for stroke in strokes:
        request("POST", "/editor/stroke", json=stroke)
    working = request("GET", "/depth/export?source=working&format=npy").content
    request("POST", "/editor/history", json={"channel": "depth", "action": "undo"})
    undone = request("GET", "/depth/export?source=working&format=npy").content
    request("POST", "/editor/history", json={"channel": "depth", "action": "redo"})
    redone = request("GET", "/depth/export?source=working&format=npy").content
    assert working == redone and working != undone
    assert original == request("GET", "/depth/export?source=ai&format=npy").content
    (OUT / "authored-shaded.png").write_bytes(request("GET", "/preview/heightmap").content)
    (OUT / "authored-mask.png").write_bytes(request("GET", "/editor/image?view=mask").content)
    (OUT / "authored.glb").write_bytes(request("POST", "/preview/mesh", json=row["params"]).content)
    (OUT / "authored-depth-16.png").write_bytes(
        request("GET", "/depth/export?source=working&format=png16").content
    )
    result = {
        "label": "Human-authored demonstration, not recovered AI anatomy",
        "strokes": strokes,
        "undo_redo_working_bytes_identical": True,
        "original_ai_sha256": hashlib.sha256(original).hexdigest(),
        "original_ai_unchanged": True,
        "state": request("GET", "/editor").json(),
    }
    (OUT / "authored-corrections.json").write_text(json.dumps(result, indent=2) + "\n")
    sheet = Image.new("RGB", (1000, 400), "#f2f2ee")
    draw = ImageDraw.Draw(sheet)
    for i, (path, title) in enumerate(
        [
            (OUT / "after-shaded.png", "Automatic + optional processing"),
            (OUT / "authored-shaded.png", "Authored: smooth / remove stray whisker ridges"),
        ]
    ):
        photo = Image.open(path).convert("RGB")
        photo.thumbnail((490, 350))
        sheet.paste(photo, (i * 500 + (500 - photo.width) // 2, 40))
        draw.text((i * 500 + 8, 12), title, fill="black")
    sheet.save(OUT / "authored-comparison.jpg", quality=94)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
