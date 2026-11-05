"""Controlled real-image comparison, CPU/RSS timings and STL/OBJ verification.

Uses the already proven genuine M1 AI arrays. No replacement or invented depth.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import threading
import time
import zipfile
from pathlib import Path

import httpx
import numpy as np
import psutil
import trimesh
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/m2/evidence"


def checked(response):
    response.raise_for_status()
    return response


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8097")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()
    client = httpx.Client(base_url=args.url, timeout=300)
    process = psutil.Process(args.pid)
    records = json.loads((OUT / "sessions.json").read_text())
    results = []

    def measured(callback):
        baseline = process.memory_info().rss
        peak = [baseline]
        stop = threading.Event()

        def sample():
            while not stop.wait(0.02):
                peak[0] = max(peak[0], process.memory_info().rss)

        worker = threading.Thread(target=sample, daemon=True)
        worker.start()
        started = time.perf_counter()
        try:
            response = callback()
            return response, {
                "wall_s": time.perf_counter() - started,
                "baseline_rss_mb": baseline / 2**20,
                "peak_rss_mb": peak[0] / 2**20,
                "settled_rss_mb": process.memory_info().rss / 2**20,
            }
        finally:
            stop.set()
            worker.join()

    for record in records:
        name, sid = record["case"], record["session_id"]
        output = OUT / name
        base = f"/api/sessions/{sid}"
        params = record["params"]
        # Re-runs are deterministic and start with original AI + no depth strokes.
        checked(client.post(base + "/editor/restore-ai", json={}))
        checked(client.put(base + "/params", json=params))
        auto, auto_timing = measured(
            lambda base=base: checked(
                client.post(base + "/editor/automatic-mask", json={"method": "u2netp"})
            )
        )
        checked(
            client.put(
                base + "/editor",
                json={
                    "mask_feather_mm": 0.8,
                    "mask_transition_mm": 4.0,
                    "sculpt_strength": 0.45,
                    "texture_guard": 0.8,
                },
            )
        )
        result = {
            "case": name,
            "session_id": sid,
            "original_params": params,
            "u2netp": auto.json()["segmentation"],
            "segmentation_timing": auto_timing,
            "manual_corrections": [],
            "exports": [],
        }
        # Initial automatic+processing result remains available even after optional manual work.
        for view in ["mask", "processed"]:
            (output / f"final-{view}.png").write_bytes(
                checked(client.get(base + f"/editor/image?view={view}")).content
            )
        for original, prefix in [(True, "before"), (False, "after")]:
            for gray, kind in [(True, "heightmap"), (False, "shaded")]:
                response, timing = measured(
                    lambda base=base, original=original, gray=gray: checked(
                        client.get(
                            base + "/preview/heightmap",
                            params={"original": original, "grayscale": gray},
                        )
                    )
                )
                (output / f"{prefix}-{kind}.png").write_bytes(response.content)
                result[f"{prefix}_{kind}_timing"] = timing
            response, timing = measured(
                lambda base=base, original=original, params=params: checked(
                    client.post(
                        base + f"/preview/mesh?original={str(original).lower()}", json=params
                    )
                )
            )
            (output / f"{prefix}.glb").write_bytes(response.content)
            result[f"{prefix}_glb_timing"] = timing
        for source in ["ai", "working"]:
            for format, ext in [("png16", "png"), ("npy", "npy")]:
                content = checked(
                    client.get(base + f"/depth/export?source={source}&format={format}")
                ).content
                (output / f"final-{source}-depth.{ext}").write_bytes(content)
                if source == "ai" and format == "npy":
                    assert hashlib.sha256(content).hexdigest() == record["ai_depth_sha256"]
        result["ai_sha_unchanged"] = True
        state = checked(client.get(base + "/editor")).json()
        (output / "editor-state.json").write_text(json.dumps(state, indent=2) + "\n")
        # A complete journal plus immutable mask allows exact replay, without any weights.
        session = ROOT / f"data/m2/run/sessions/{sid}/editing"
        (output / "edit-journal.json").write_bytes((session / "state.json").read_bytes())
        with zipfile.ZipFile(output / "editing-document.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(session / "state.json", "state.json")
            journal = json.loads((session / "state.json").read_text())
            for history in journal["histories"].values():
                for operation in history["operations"]:
                    if operation.get("file"):
                        archive.write(session / operation["file"], operation["file"])
        if args.export:
            for format in ["stl", "obj"]:
                configured = dict(params, resolution=512, output_format=format)
                plan = checked(client.post(base + "/export-plan", json=configured)).json()

                def export(base=base, configured=configured):
                    job = checked(client.post(base + "/export", json=configured)).json()["job_id"]
                    while True:
                        status = checked(client.get(f"/api/jobs/{job}")).json()
                        if status["status"] == "error":
                            raise RuntimeError(status["error"])
                        if status["status"] == "ready":
                            return checked(client.get(status["download_url"]))
                        time.sleep(0.05)

                response, timing = measured(export)
                # Large final solids stay local; report reimport topology and hashes.
                local = ROOT / f"data/m2/exports/{name}.{format}"
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(response.content)
                mesh = trimesh.load(io.BytesIO(response.content), file_type=format, force="mesh")
                assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume > 0
                assert np.isfinite(mesh.vertices).all()
                width, height = Image.open(ROOT / f"docs/m1/evidence/inputs/{name}.png").size
                np.testing.assert_allclose(mesh.extents[:2], [150, 150 * height / width], atol=2e-5)
                assert mesh.bounds[0, 2] == 0
                result["exports"].append(
                    {
                        "format": format,
                        "timing": timing,
                        "triangles": len(mesh.faces),
                        "bytes": len(response.content),
                        "watertight": bool(mesh.is_watertight),
                        "winding_consistent": bool(mesh.is_winding_consistent),
                        "bounds_mm": mesh.bounds.tolist(),
                        "volume_mm3": float(mesh.volume),
                        "sha256": hashlib.sha256(response.content).hexdigest(),
                        "plan": plan,
                    }
                )
            checked(client.put(base + "/params", json=params))
        sheet = Image.new("RGB", (1200, 700), "#f2f2ee")
        draw = ImageDraw.Draw(sheet)
        tiles = [
            (ROOT / f"docs/m1/evidence/inputs/{name}.png", "Source (same as M1)"),
            (output / "final-ai-depth.png", "Original genuine AI depth"),
            (output / "final-processed.png", "Processed depth (mask + bounded detail)"),
            (output / "final-mask.png", "Optional local U2NETP mask"),
            (output / "before-shaded.png", "Before: original pipeline"),
            (output / "after-shaded.png", "After: mask + optional processing"),
        ]
        for index, (path, label) in enumerate(tiles):
            column, row = index % 3, index // 3
            image = Image.open(path)
            if image.mode in {"I;16", "I;16B", "I"}:
                # Pillow's direct RGB conversion saturates 16-bit values at 255.
                # Only the display tile is scaled; the exchange PNG stays 16-bit.
                image = Image.fromarray(np.rint(np.asarray(image) / 257).astype(np.uint8))
            image = image.convert("RGB")
            image.thumbnail((390, 310))
            sheet.paste(image, (column * 400 + (400 - image.width) // 2, row * 350 + 32))
            draw.text((column * 400 + 8, row * 350 + 9), label, fill="#202020")
        sheet.save(output / "comparison.jpg", quality=94)
        results.append(result)
        (OUT / "final-results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(
            name,
            "mask",
            round(auto_timing["wall_s"], 3),
            "exports",
            len(result["exports"]),
            flush=True,
        )


if __name__ == "__main__":
    main()
