"""Real HTTP acceptance run. No mocked models; saves measured evidence and meshes.

Run from the repo root: .venv/Scripts/python.exe -m tools.m1.baseline
Use --offline after models are cached; --models da2-large for a separate model run.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import numpy as np
import trimesh
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/m1/evidence"
DATA = ROOT / "data/m1"


def peak_memory(pid: int) -> int | None:
    if sys.platform != "win32":
        return None

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t)
            for name in [
                "PeakWorkingSetSize",
                "WorkingSetSize",
                "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage",
                "PagefileUsage",
                "PeakPagefileUsage",
            ]
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        return None
    try:
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return counters.PeakWorkingSetSize
    finally:
        kernel.CloseHandle(handle)
    return None


def wait_status(client: httpx.Client, path: str, timeout: float = 1200) -> dict:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        response = client.get(path)
        response.raise_for_status()
        status = response.json()
        if status["status"] in {"ready", "error"}:
            if status["status"] == "error":
                raise RuntimeError(status.get("error"))
            return status
        time.sleep(0.25)
    raise TimeoutError(path)


def checked(response: httpx.Response) -> httpx.Response:
    response.raise_for_status()
    return response


def validate_mesh(path: Path) -> dict:
    mesh = trimesh.load(path, force="mesh")
    return {
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "positive_volume": bool(mesh.volume > 0),
        "faces": len(mesh.faces),
        "bounds_mm": mesh.bounds.tolist(),
        "bytes": path.stat().st_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--models", default="da2-small")
    parser.add_argument("--cases", default="portrait,pet,ornament,object,complex")
    parser.add_argument("--large-exports", action="store_true")
    parser.add_argument("--port", type=int, default=8095)
    args = parser.parse_args()
    # Fail before touching any service already running on the machine.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    DATA.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        P2R_DEVICE="cpu",
        P2R_DATA_DIR=str(ROOT / "data"),
        HF_HUB_DISABLE_TELEMETRY="1",
        DO_NOT_TRACK="1",
        OMP_NUM_THREADS="4",
        MKL_NUM_THREADS="4",
        HF_HUB_DISABLE_SYMLINKS_WARNING="1",
    )
    if args.offline:
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    label = ("offline" if args.offline else "online") + "-" + args.models.replace(",", "-")
    log = (DATA / f"server-{label}.log").open("w", encoding="utf-8")
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
        ],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    report = {
        "platform": platform.platform(),
        "python": sys.version,
        "offline": args.offline,
        "threads": 4,
        "server_pid": server.pid,
        "cases": [],
        "failures": [],
    }
    stop = threading.Event()
    peaks = []

    def monitor() -> None:
        while not stop.wait(0.2):
            value = peak_memory(server.pid)
            if value:
                peaks.append(value)

    threading.Thread(target=monitor, daemon=True).start()
    client = httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=1200)
    try:
        for _ in range(180):
            if server.poll() is not None:
                raise RuntimeError(f"Backend exited {server.returncode}; see {log.name}")
            try:
                report["health"] = checked(client.get("/api/health")).json()
                break
            except httpx.TransportError:
                time.sleep(0.5)
        else:
            raise TimeoutError("Backend startup")
        report["main_page_bytes"] = len(checked(client.get("/")).content)
        report["models"] = checked(client.get("/api/models")).json()
        for model in args.models.split(","):
            for name in args.cases.split(","):
                result = {"case": name, "model": model}
                out = EVIDENCE / f"{name}-{model}"
                out.mkdir(exist_ok=True)
                try:
                    started = time.perf_counter()
                    photo = (EVIDENCE / f"inputs/{name}.png").read_bytes()
                    created = checked(
                        client.post(
                            "/api/sessions", files={"image": (f"{name}.png", photo, "image/png")}
                        )
                    ).json()
                    result["upload_s"] = time.perf_counter() - started
                    sid = result["session_id"] = created["session_id"]
                    status = wait_status(client, f"/api/sessions/{sid}/status")
                    params = checked(client.get(f"/api/sessions/{sid}/params")).json()
                    if params["depth_model"] != model:
                        params["depth_model"] = model
                        checked(client.put(f"/api/sessions/{sid}/params", json=params))
                        status = wait_status(client, f"/api/sessions/{sid}/status")
                    result["inference_or_cache_s"] = status["elapsed_s"]
                    result["params"] = params
                    depth_path = ROOT / f"data/sessions/{sid}/raw_depth_{model}.npy"
                    depth = np.load(depth_path)
                    result["depth_shape"] = list(depth.shape)
                    result["depth_range"] = [float(depth.min()), float(depth.max())]
                    Image.fromarray((depth * 255).astype("uint8")).save(out / "depth.png")
                    for gray, filename in [(True, "heightmap.png"), (False, "shaded.png")]:
                        started = time.perf_counter()
                        response = checked(
                            client.get(
                                f"/api/sessions/{sid}/preview/heightmap", params={"grayscale": gray}
                            )
                        )
                        result[filename + "_s"] = time.perf_counter() - started
                        (out / filename).write_bytes(response.content)
                    started = time.perf_counter()
                    glb = checked(client.post(f"/api/sessions/{sid}/preview/mesh", json=params))
                    result["preview_3d_s"] = time.perf_counter() - started
                    (out / "preview.glb").write_bytes(glb.content)
                    cached_before = (
                        depth_path.stat().st_mtime_ns,
                        hashlib.sha256(depth_path.read_bytes()).hexdigest(),
                    )
                    changed = dict(params, gamma=2.2)
                    checked(client.put(f"/api/sessions/{sid}/params", json=changed))
                    changed_png = checked(client.get(f"/api/sessions/{sid}/preview/heightmap"))
                    result["settings_update_changes_preview"] = (
                        changed_png.content != (out / "shaded.png").read_bytes()
                    )
                    result["settings_preserve_depth_cache"] = cached_before == (
                        depth_path.stat().st_mtime_ns,
                        hashlib.sha256(depth_path.read_bytes()).hexdigest(),
                    )
                    checked(client.put(f"/api/sessions/{sid}/params", json=params))
                    exports = []
                    resolutions = (
                        [512, 1024, 2048] if args.large_exports and name == "portrait" else [512]
                    )
                    for resolution in resolutions:
                        formats = ["stl", "obj"] if resolution == 512 else ["stl"]
                        for fmt in formats:
                            export_params = dict(params, resolution=resolution, output_format=fmt)
                            started = time.perf_counter()
                            job = checked(
                                client.post(f"/api/sessions/{sid}/export", json=export_params)
                            ).json()
                            status = wait_status(client, f"/api/jobs/{job['job_id']}")
                            elapsed = time.perf_counter() - started
                            dest = DATA / f"{name}-{model}-{resolution}.{fmt}"
                            with client.stream("GET", status["download_url"]) as response:
                                response.raise_for_status()
                                with dest.open("wb") as output:
                                    for chunk in response.iter_bytes():
                                        output.write(chunk)
                            validation = validate_mesh(dest)
                            assert validation["watertight"] and validation["positive_volume"]
                            exports.append(
                                {
                                    "resolution": resolution,
                                    "format": fmt,
                                    "export_s_including_poll": elapsed,
                                    **validation,
                                }
                            )
                            print(json.dumps({"export": str(dest), **exports[-1]}), flush=True)
                    result["exports"] = exports
                    sheet = Image.new("RGB", (1200, 340), "white")
                    draw = ImageDraw.Draw(sheet)
                    for i, (path, title) in enumerate(
                        [
                            (EVIDENCE / f"inputs/{name}.png", "Input"),
                            (out / "depth.png", "AI depth"),
                            (out / "heightmap.png", "Heightmap"),
                            (out / "shaded.png", "Shaded relief"),
                        ]
                    ):
                        with Image.open(path) as image:
                            thumb = image.convert("RGB")
                            thumb.thumbnail((290, 295))
                            sheet.paste(thumb, (i * 300 + (300 - thumb.width) // 2, 30))
                        draw.text((i * 300 + 10, 8), title, fill="black")
                    sheet.save(out / "comparison.jpg", quality=92)
                    print(
                        json.dumps(
                            {
                                "finished": name,
                                "model": model,
                                "inference_or_cache_s": result["inference_or_cache_s"],
                            }
                        ),
                        flush=True,
                    )
                except Exception as exc:
                    result["error"] = str(exc)
                    report["failures"].append({"case": name, "model": model, "error": str(exc)})
                    print(json.dumps(report["failures"][-1]), flush=True)
                report["cases"].append(result)
                report["backend_peak_working_set_bytes"] = max(peaks, default=0)
                (EVIDENCE / f"results-{label}.json").write_text(
                    json.dumps(report, indent=2) + "\n", encoding="utf-8"
                )
    finally:
        stop.set()
        client.close()
        server.terminate()
        server.wait(timeout=30)
        log.close()
    if report["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
