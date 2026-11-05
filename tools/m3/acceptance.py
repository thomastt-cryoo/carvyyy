"""Real HTTP M3 integration on the user's tiger/face, no fabricated AI depth.

Backend must be explicitly started offline with existing local models. This script
does not replace browser acceptance; it records numerical/export/persistence checks.
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
import time
from pathlib import Path

import httpx
import numpy as np
import psutil
import trimesh

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/m3/evidence"
CASES = {"tiger": "1b3f58f1ae934eb9bf9acbe9993df2ed", "face": "dfde6a13cb0f4d73a9b19cfb8e2cfbaf"}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(base_url="http://127.0.0.1:8098", timeout=300)
    process = next(
        p
        for p in psutil.process_iter(["name"])
        if p.info["name"] == "python.exe"
        and "uvicorn" in p.cmdline()
        and "8098" in p.cmdline()
        and not p.children()
    )

    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        return response

    def measured(callback):
        before = process.memory_info().rss
        peak = [before]
        stop = threading.Event()

        def sample():
            while not stop.wait(0.02):
                peak[0] = max(peak[0], process.memory_info().rss)

        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        start = time.perf_counter()
        try:
            response = callback()
            return response, {
                "wall_s": time.perf_counter() - start,
                "baseline_rss_mb": before / 2**20,
                "peak_rss_mb": peak[0] / 2**20,
            }
        finally:
            stop.set()
            sampler.join()

    results = []
    defaults = request("GET", "/api/models").json()["default_params"]
    for name, sid in CASES.items():
        base = f"/api/sessions/{sid}"
        original_params = request("GET", base + "/params").json()
        raw_bytes = request("GET", base + "/depth/export?source=ai&format=npy").content
        raw = np.load(io.BytesIO(raw_bytes), allow_pickle=False)
        record = {
            "case": name,
            "session_id": sid,
            "ai_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "original_browser_parameters": original_params,
            "operations": [],
            "exports": [],
        }
        request(
            "PATCH",
            f"/api/projects/{sid}",
            json={"name": "Tiger emblem" if name == "tiger" else "Face study"},
        )
        request("PUT", base + "/params", json=defaults)
        request("POST", base + "/editor/restore-ai", json={})
        automatic, timing = measured(
            lambda base=base: request(
                "POST", base + "/editor/automatic-mask", json={"method": "auto"}
            )
        )
        assert automatic.json()["segmentation"]["method"] == "Original image transparency"
        record["alpha_isolation"] = {"result": automatic.json()["segmentation"], "timing": timing}
        preset = "Ornament" if name == "tiger" else "Portrait"
        request("POST", f"/api/projects/{sid}/preset", json={"name": preset})
        initial = request("GET", base + "/depth/export?source=working&format=npy").content
        for tool in ["raise", "lower", "smooth", "flatten"]:
            stroke = {
                "tool": tool,
                "points": [[0.5, 0.45], [0.52, 0.46]],
                "strength": 0.05 if tool in {"raise", "lower"} else 0.5,
                "radius": 0.05,
                "level": 0.5,
            }
            response, timing = measured(
                lambda base=base, stroke=stroke: request(
                    "POST", base + "/editor/stroke", json=stroke
                )
            )
            changed = request("GET", base + "/depth/export?source=working&format=npy").content
            request("POST", base + "/editor/history", json={"channel": "depth", "action": "undo"})
            reverted = request("GET", base + "/depth/export?source=working&format=npy").content
            assert reverted == initial
            assert changed != initial
            request("POST", base + "/editor/history", json={"channel": "depth", "action": "redo"})
            assert (
                changed == request("GET", base + "/depth/export?source=working&format=npy").content
            )
            request("POST", base + "/editor/history", json={"channel": "depth", "action": "undo"})
            record["operations"].append(
                {"tool": tool, "changed": True, "undo_redo_exact": True, "timing": timing}
            )
        png = request("GET", base + "/depth/export?source=ai&format=png16").content
        assert png[24:26] == bytes([16, 0])
        imported = request(
            "POST", base + "/depth/import", files={"file": ("AI exchange.png", png)}
        ).json()
        near = np.load(
            io.BytesIO(request("GET", base + "/depth/export?source=working&format=npy").content)
        )
        record["png16_max_error"] = float(np.max(np.abs(near - raw)))
        assert record["png16_max_error"] <= 0.51 / 65535
        request("PUT", base + "/editor", json={"depth_source": "ai"})
        request(
            "PUT",
            base + "/editor",
            json={"depth_source": "imported", "import_id": imported["imported"]["id"]},
        )
        for channel, tool in [("mask", "remove"), ("mask", "keep"), ("depth", "raise")]:
            request(
                "POST",
                base + "/editor/stroke",
                json={
                    "channel": channel,
                    "tool": tool,
                    "points": [[0.05, 0.05]],
                    "radius": 0.02,
                    "strength": 0.03,
                },
            )
        params = request("GET", base + "/params").json()
        for original, label in [(True, "original"), (False, "edited")]:
            png_response, preview_timing = measured(
                lambda base=base, original=original: request(
                    "GET", base + f"/preview/heightmap?original={str(original).lower()}"
                )
            )
            (OUT / f"{name}-{label}-shaded.png").write_bytes(png_response.content)
            glb_response, glb_timing = measured(
                lambda base=base, original=original, params=params: request(
                    "POST", base + f"/preview/mesh?original={str(original).lower()}", json=params
                )
            )
            (OUT / f"{name}-{label}.glb").write_bytes(glb_response.content)
            record[label + "_preview_timing"] = preview_timing
            record[label + "_glb_timing"] = glb_timing
        editor_before = request("GET", base + "/editor").json()
        request("GET", base + "/preview/heightmap?original=true")
        assert request("GET", base + "/editor").json() == editor_before
        record["original_comparison_readonly"] = True
        assert request("GET", base + "/depth/export?source=ai&format=npy").content == raw_bytes
        record["original_ai_unchanged"] = True
        for format in ["stl", "obj"]:
            export_params = dict(
                params,
                resolution=512,
                output_format=format,
                decimate_ratio=0.15 if format == "obj" else 0,
            )

            def export(base=base, export_params=export_params):
                job = request("POST", base + "/export", json=export_params).json()["job_id"]
                while True:
                    status = request("GET", f"/api/jobs/{job}").json()
                    if status["status"] == "error":
                        raise RuntimeError(status["error"])
                    if status["status"] == "ready":
                        return request("GET", status["download_url"])
                    time.sleep(0.1)

            response, export_timing = measured(export)
            mesh = trimesh.load(io.BytesIO(response.content), file_type=format, force="mesh")
            assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume > 0
            assert np.isfinite(mesh.vertices).all() and abs(mesh.bounds[0, 2]) < 0.001
            meta = request("GET", f"/api/projects/{sid}").json()["image"]
            np.testing.assert_allclose(
                mesh.extents[:2], [150, 150 * meta["h"] / meta["w"]], atol=0.01
            )
            path = ROOT / f"data/m3/exports/{name}.{format}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
            record["exports"].append(
                {
                    "format": format,
                    "timing": export_timing,
                    "watertight": True,
                    "consistent_winding": True,
                    "triangles": len(mesh.faces),
                    "bounds_mm": mesh.bounds.tolist(),
                    "bytes": len(response.content),
                    "sha256": hashlib.sha256(response.content).hexdigest(),
                }
            )
        refused = request("POST", base + "/export-plan", json=dict(params, resolution=2048)).json()
        record["maximum_resource_plan"] = refused
        assert not refused["allowed"]
        rejected = client.post(base + "/export", json=dict(params, resolution=2048))
        assert rejected.status_code == 422
        # Keep canonical examples on their AI source and original dimensions.
        request("PUT", base + "/editor", json={"depth_source": "ai"})
        request("PUT", base + "/params", json=params)
        record["editor"] = request("GET", base + "/editor").json()
        record["inference_elapsed_s"] = request("GET", base + "/status").json()["elapsed_s"]
        results.append(record)
        (OUT / "integration-results.json").write_text(json.dumps(results, indent=2) + "\n")
        print(name, "all checks passed", flush=True)


if __name__ == "__main__":
    main()
