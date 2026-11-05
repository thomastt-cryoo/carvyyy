"""Real M2 HTTP evidence using the genuine M1 AI cache, never fabricated depth.

An externally running M2 server is intentional so the same sessions can be
inspected in the browser. Read mask images before applying corrective selections.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/m2/evidence"


def checked(response):
    response.raise_for_status()
    return response


def wait(client, path):
    started = time.perf_counter()
    while time.perf_counter() - started < 900:
        state = checked(client.get(path)).json()
        if state["status"] == "error":
            raise RuntimeError(state["error"])
        if state["status"] == "ready":
            return state
        time.sleep(0.2)
    raise TimeoutError(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8097")
    parser.add_argument("--phase", choices=["automatic", "final"], default="automatic")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    records_file = OUT / "sessions.json"
    client = httpx.Client(base_url=args.url, timeout=900)
    records = []
    previous = json.loads((ROOT / "docs/m1/evidence/results-online-da2-small.json").read_text())
    if args.phase == "automatic":
        for row in previous["cases"]:
            name = row["case"]
            output = OUT / name
            output.mkdir(exist_ok=True)
            photo = ROOT / f"docs/m1/evidence/inputs/{name}.png"
            create = checked(
                client.post(
                    "/api/sessions", files={"image": (photo.name, photo.read_bytes(), "image/png")}
                )
            ).json()
            sid = create["session_id"]
            status = wait(client, f"/api/sessions/{sid}/status")
            base = f"/api/sessions/{sid}"
            params = checked(client.get(base + "/params")).json()
            old_depth = ROOT / f"data/sessions/{row['session_id']}/raw_depth_da2-small.npy"
            ai = checked(client.get(base + "/depth/export?source=ai&format=npy")).content
            ai_array = np.load(__import__("io").BytesIO(ai), allow_pickle=False)
            assert np.array_equal(ai_array, np.load(old_depth)), (
                "M1/M2 comparisons need identical genuine predictions"
            )
            record = {
                "case": name,
                "session_id": sid,
                "params": params,
                "genuine_m1_depth_identical": True,
                "ai_depth_sha256": hashlib.sha256(ai).hexdigest(),
                "depth_cache_operation_s": status["elapsed_s"],
            }
            (output / "ai-depth.npy").write_bytes(ai)
            (output / "ai-depth-16.png").write_bytes(
                checked(client.get(base + "/depth/export?source=ai&format=png16")).content
            )
            for original, prefix in [(True, "before"), (False, "initial")]:
                for gray, kind in [(True, "heightmap"), (False, "shaded")]:
                    (output / f"{prefix}-{kind}.png").write_bytes(
                        checked(
                            client.get(
                                base + "/preview/heightmap",
                                params={"original": original, "grayscale": gray},
                            )
                        ).content
                    )
                (output / f"{prefix}.glb").write_bytes(
                    checked(
                        client.post(
                            base + f"/preview/mesh?original={str(original).lower()}", json=params
                        )
                    ).content
                )
            started = time.perf_counter()
            auto = client.post(base + "/editor/automatic-mask", json={"method": "grabcut"})
            record["automatic_s"] = time.perf_counter() - started
            record["automatic_status"] = auto.status_code
            record["automatic_result"] = auto.json()
            if auto.is_success:
                (output / "automatic-mask.png").write_bytes(
                    checked(client.get(base + "/editor/image?view=mask")).content
                )
                (output / "automatic-shaded.png").write_bytes(
                    checked(client.get(base + "/preview/heightmap")).content
                )
                sheet = Image.new("RGB", (900, 330), "white")
                draw = ImageDraw.Draw(sheet)
                for column, (path, label) in enumerate(
                    [
                        (photo, "Original photo"),
                        (output / "automatic-mask.png", "Automatic GrabCut mask"),
                        (output / "automatic-shaded.png", "Automatic masked relief"),
                    ]
                ):
                    image = Image.open(path).convert("RGB")
                    image.thumbnail((294, 290))
                    sheet.paste(image, (column * 300 + (300 - image.width) // 2, 28))
                    draw.text((column * 300 + 8, 7), label, fill="black")
                sheet.save(output / "automatic-comparison.jpg", quality=93)
            records.append(record)
            records_file.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
            print(
                json.dumps(
                    {
                        "case": name,
                        "mask_status": auto.status_code,
                        "seconds": round(record["automatic_s"], 3),
                    }
                ),
                flush=True,
            )
    else:
        raise SystemExit("Run tools/m2/final_evidence.py --pid <backend PID> --export instead.")


if __name__ == "__main__":
    main()
