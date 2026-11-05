"""Seed isolated browser projects and measure M4 on genuine local predictions."""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

import numpy as np
import psutil
import trimesh
from fastapi.testclient import TestClient

from app import depth, sessions
from app.config import settings
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/m4/validation"
RUN = ROOT / "data/m4/run"


def checked(response):
    response.raise_for_status()
    return response


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cases():
    rows = json.loads((ROOT / "docs/m2/evidence/sessions.json").read_text(encoding="utf-8"))
    for row in rows:
        if row["case"] == "portrait":
            continue  # Use the user's portrait and a different ordinary photo.
        name = row["case"]
        raw = ROOT / "data/m2/run/sessions" / row["session_id"] / "raw_depth_da2-small.npy"
        yield name, ROOT / f"docs/m1/evidence/inputs/{name}.png", raw
    for name, sid in (
        ("face", "dfde6a13cb0f4d73a9b19cfb8e2cfbaf"),
        ("tiger", "1b3f58f1ae934eb9bf9acbe9993df2ed"),
    ):
        raw = ROOT / "data/m3/run/sessions" / sid / "raw_depth_da2-small.npy"
        yield name, ROOT / f"docs/m3/evidence/inputs/{name}.png", raw
    extra = ROOT / "data/m4/quality-research"
    ids = json.loads((extra / "extra-sessions.json").read_text(encoding="utf-8"))
    for name, sid in ids.items():
        raw = extra / "runtime/sessions" / sid / "raw_depth_da2-small.npy"
        yield name, extra / f"inputs/{name}.jpg", raw


def main():
    if settings.sessions_dir.resolve() != (RUN / "sessions").resolve():
        raise SystemExit("Set P2R_DATA_DIR to the isolated data/m4/run folder.")
    OUT.mkdir(parents=True, exist_ok=True)
    client = TestClient(app)
    results = {}
    index = OUT / "projects.json"
    previous = json.loads(index.read_text(encoding="utf-8")) if index.exists() else {}
    proc = psutil.Process()
    for name, photo, raw in cases():
        if name in previous:
            sid = previous[name]["id"]
        else:
            sid = checked(
                client.post(
                    "/api/projects/upload", files={"image": (photo.name, photo.read_bytes())}
                )
            ).json()["id"]
            target = depth.session_depth_path(sid, "da2-small")
            depth.load_normalized_depth(raw)
            shutil.copyfile(raw, target)
            sessions.write_status(sid, model_id="da2-small", status="ready", device="cpu")
            checked(client.patch(f"/api/projects/{sid}", json={"name": name.title() + " study"}))
            if name in {"tiger", "face", "pet"}:
                method = "u2netp" if name == "pet" else "alpha"
                if (
                    method == "alpha"
                    or checked(client.get(f"/api/sessions/{sid}/segmentation")).json()["available"]
                ):
                    checked(
                        client.post(
                            f"/api/sessions/{sid}/editor/automatic-mask", json={"method": method}
                        )
                    )
        results[name] = {
            "id": sid,
            "source": str(photo.relative_to(ROOT)),
            "depth_sha256": digest(raw),
        }
        assert digest(depth.session_depth_path(sid, "da2-small")) == results[name]["depth_sha256"]
    index.write_text(json.dumps(results, indent=2), encoding="utf-8")
    cam = OUT / "cam"
    cam.mkdir(exist_ok=True)
    results_export = []
    for name, fmt, reduction in (
        ("tiger", "stl", 0.95),
        ("tiger", "obj", 0.95),
        ("face", "stl", 0.0),
    ):
        sid = results[name]["id"]
        base = f"/api/sessions/{sid}"
        params = checked(client.get(base + "/params")).json()
        params.update(resolution=512, output_format=fmt, decimate_ratio=reduction)
        checked(client.put(base + "/editor", json={"cnc_refinement": True}))
        record = {"name": name, "format": fmt, "params": params, "refinement": True, "previews": {}}
        for resolution in (256, 512):
            start = time.perf_counter()
            preview = checked(
                client.post(base + f"/preview/mesh?resolution={resolution}", json=params)
            )
            record["previews"][resolution] = {
                "seconds": time.perf_counter() - start,
                "bytes": len(preview.content),
            }
        start = time.perf_counter()
        job_id = checked(client.post(base + "/export", json=params)).json()["job_id"]
        while True:
            status = checked(client.get(f"/api/jobs/{job_id}")).json()
            if status["status"] != "processing":
                break
            if time.perf_counter() - start > 120:
                raise RuntimeError("Export validation timed out.")
            time.sleep(0.1)
        assert status["status"] == "ready", status
        record["export_seconds"] = time.perf_counter() - start
        file = cam / f"m4-{name}-512.{fmt}"
        file.write_bytes(checked(client.get(status["download_url"])).content)
        mesh = trimesh.load(file, force="mesh")
        glb = cam / f"m4-{name}-{fmt}-inspection.glb"
        glb.write_bytes(checked(client.get(status["preview_url"])).content)
        inspection = trimesh.load(glb).to_geometry()
        assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume > 0
        assert inspection.is_watertight and len(inspection.faces) == len(mesh.faces)
        np.testing.assert_allclose(mesh.bounds, inspection.bounds, atol=0.0001)
        assert mesh.bounds[0, 2] == 0
        record.update(
            file=file.name,
            sha256=digest(file),
            triangles=len(mesh.faces),
            bounds_mm=mesh.bounds.tolist(),
            inspection_bytes=glb.stat().st_size,
            surface=status["surface"],
            settled_rss_mib=proc.memory_info().rss / 2**20,
        )
        results_export.append(record)
        (OUT / "geometry.json").write_text(json.dumps(results_export, indent=2), encoding="utf-8")
        print(name, fmt, len(mesh.faces), record["export_seconds"], flush=True)


if __name__ == "__main__":
    main()
