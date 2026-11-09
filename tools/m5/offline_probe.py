"""Run real application APIs in the extracted interpreter with external sockets denied."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

PROBE = r"""
import io, json, os, time
from pathlib import Path
import trimesh
from fastapi.testclient import TestClient
from app.main import app

source = Path(os.environ["RELIEF_ACCEPTANCE_SOURCE"])
output = Path(os.environ["RELIEF_ACCEPTANCE_OUTPUT"])
result = {"external_sockets": "denied by acceptance guard", "source": source.name}
with TestClient(app) as client:
    assert [m['model_id'] for m in client.get('/api/models').json()['models']] == ['da2-small']
    result['single_depth_model'] = 'da2-small'
    started = time.monotonic()
    response = client.post(
        "/api/projects/upload?model_id=da2-small",
        files={"image": ("new-offline-photo.png", source.read_bytes(), "image/png")},
    )
    assert response.status_code == 200, response.text
    sid = response.json()["id"]
    for _ in range(1200):
        document = client.get("/api/projects/" + sid).json()
        if document["status"] in ("ready", "error"):
            break
        time.sleep(0.2)
    assert document["status"] == "ready", document
    result["fresh_inference_seconds"] = round(time.monotonic() - started, 2)
    assert (
        client.post(
            f"/api/sessions/{sid}/editor/automatic-mask", json={"method": "auto"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/sessions/{sid}/editor/stroke",
            json={"tool": "raise", "points": [[0.5, 0.5]], "strength": 0.04},
        ).status_code
        == 200
    )
    assert client.get(f"/api/sessions/{sid}/preview/heightmap").status_code == 200
    isolated = client.post(
        f"/api/sessions/{sid}/editor/automatic-mask", json={"method": "u2netp"}
    )
    assert isolated.status_code == 200, isolated.text
    result["u2netp_offline"] = True
    result["mask_edit_and_preview"] = True
    original = client.get(f'/api/sessions/{sid}/params').json()
    response = client.put(
        f'/api/sessions/{sid}/params', json=original | {'model_width_mm': 160}
    )
    assert response.status_code == 200, response.text
    for action, width in [('undo', 150), ('redo', 160), ('undo', 150)]:
        token = client.get(f'/api/sessions/{sid}/editor').json()['project_history']['token']
        changed = client.post(
            f'/api/projects/{sid}/history', json={'action': action, 'expected_token': token}
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()['params']['model_width_mm'] == width
    result['project_undo_redo_offline'] = True
    for format in ("stl", "obj"):
        params = client.get(f"/api/sessions/{sid}/params").json() | {
            "resolution": 512,
            "output_format": format,
        }
        response = client.post(f"/api/sessions/{sid}/export", json=params)
        assert response.status_code == 200, response.text
        job = response.json()["job_id"]
        for _ in range(900):
            status = client.get("/api/jobs/" + job).json()
            if status["status"] != "processing":
                break
            time.sleep(0.2)
        assert status["status"] == "ready", status
        data = client.get(status["download_url"]).content
        mesh = trimesh.load(io.BytesIO(data), file_type=format, force="mesh")
        assert mesh.is_watertight and mesh.volume > 0
        assert abs(float(mesh.extents[0]) - 150) < 0.001
        result[format] = {"bytes": len(data), "triangles": len(mesh.faces), "watertight": True}
    assert client.get("/api/projects/" + sid).json()["id"] == sid
    result["project_saved"] = True
output.write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--installed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    installed = args.installed.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[2]
    guard = (root / "tools/m1/offline_guard/sitecustomize.py").read_text()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.update(
        P2R_DEVICE="cpu",
        P2R_DEFAULT_MODEL_ID="da2-small",
        P2R_DATA_DIR=str(output / "data"),
        P2R_MODELS_DIR=str(installed / "models"),
        HF_HOME=str(installed / "models"),
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        OMP_NUM_THREADS="4",
        MKL_NUM_THREADS="4",
        PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
        RELIEF_ACCEPTANCE_SOURCE=str(args.source.resolve()),
        RELIEF_ACCEPTANCE_OUTPUT=str(output / "results.json"),
    )
    interpreter = installed / (
        "runtime/python.exe" if os.name == "nt" else "runtime/bin/python3.12"
    )
    subprocess.run(
        [str(interpreter), "-s", "-c", f"exec({guard!r});exec({PROBE!r})"],
        cwd=installed / "application",
        env=env,
        check=True,
        timeout=600,
    )


if __name__ == "__main__":
    main()
