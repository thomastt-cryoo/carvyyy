"""Executable bootstrapper acceptance proof, using only Python's standard library.

The downloaded backend is explicitly a native demo, not simulated AI inference.
Tests resume, Range fallback, verification, traversal rejection and offline relaunch.
"""

from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import os
import platform
import socket
import subprocess
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "data/m1/bootstrap-proof")
    args = parser.parse_args()
    exe = args.exe.resolve()
    work = args.output.resolve()
    work.mkdir(parents=True, exist_ok=False)
    payload = work / "payload.zip"
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.write(exe, exe.name)
        archive.writestr("download-test.bin", os.urandom(2_000_000))
    original = payload.read_bytes()
    controls = {"interrupt": True, "ignore_range": False, "bytes": original, "requests": []}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            pass

        def do_GET(self) -> None:
            data = controls["bytes"]
            range_header = self.headers.get("Range")
            controls["requests"].append(range_header)
            offset = 0
            if range_header and not controls["ignore_range"]:
                offset = int(range_header.removeprefix("bytes=").split("-")[0])
            self.send_response(206 if offset else 200)
            self.send_header("Content-Length", str(len(data) - offset))
            if offset:
                self.send_header("Content-Range", f"bytes {offset}-{len(data) - 1}/{len(data)}")
            self.end_headers()
            try:
                end = min(len(data), offset + 262144) if controls["interrupt"] else len(data)
                for index in range(offset, end, 16384):
                    self.wfile.write(data[index : min(index + 16384, end)])
                    self.wfile.flush()
                    time.sleep(0.004)
                if controls["interrupt"]:
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
            except (ConnectionError, OSError):
                pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    manifest = {
        "schema_version": 1,
        "version": "m1-proof",
        "platform": {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}[platform.system()]
        + "-"
        + {"AMD64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64"}[platform.machine()],
        "components": [
            {
                "id": "native-demo",
                "url": f"http://127.0.0.1:{server.server_port}/payload.zip",
                "size_bytes": len(original),
                "unpacked_limit_bytes": 30_000_000,
                "sha256": sha(original),
            }
        ],
        "executable": exe.name,
        "arguments": ["--demo-backend", "{port}"],
    }
    manifest_path = work / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    results = {"platform": platform.platform(), "checks": [], "progress_samples": []}

    def command(root: Path, install_only: bool = True) -> list[str]:
        values = [
            str(exe),
            "--manifest",
            str(manifest_path),
            "--manifest-sha256",
            sha(manifest_path.read_bytes()),
            "--root",
            str(root),
            "--allow-local-http",
            "--no-browser",
        ]
        return values + (["--install-only"] if install_only else [])

    def run(root: Path) -> int:
        process = subprocess.Popen(command(root))
        setup_url = None
        started = time.monotonic()
        while process.poll() is None:
            if time.monotonic() - started > 60:
                process.kill()
                raise TimeoutError("bootstrap proof")
            if (root / "setup-url.txt").exists():
                setup_url = (root / "setup-url.txt").read_text()
                try:
                    with urllib.request.urlopen(setup_url + "status", timeout=1) as response:
                        sample = json.load(response)
                    if 0 < sample["downloaded"] < sample["total"]:
                        results["progress_samples"].append(sample)
                except (OSError, ValueError):
                    pass
            time.sleep(0.03)
        return process.returncode

    def check(name: str, condition: bool) -> None:
        results["checks"].append({"name": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)

    try:
        resumed_root = work / "resumed"
        check("interrupted download fails closed", run(resumed_root) != 0)
        partial = next((resumed_root / "downloads").glob("*.part"))
        check("interrupted bytes preserved", 0 < partial.stat().st_size < len(original))
        controls["interrupt"] = False
        check("retry completes verified installation", run(resumed_root) == 0)
        check("HTTP Range was used", any(controls["requests"]))
        check("genuine byte progress observed", len(results["progress_samples"]) > 0)

        ignored_root = work / "range-ignored"
        (ignored_root / "downloads").mkdir(parents=True)
        (ignored_root / "downloads" / f"{sha(original)}.part").write_bytes(original[:32768])
        controls["ignore_range"] = True
        check("server ignoring Range safely restarts", run(ignored_root) == 0)

        controls["bytes"] = original[:-1] + bytes([original[-1] ^ 1])
        corrupt_root = work / "corrupt"
        check("corrupt component is rejected", run(corrupt_root) != 0)
        check("corrupt component never installed", not (corrupt_root / "versions").exists())

        malicious = work / "traversal.zip"
        with zipfile.ZipFile(malicious, "w") as archive:
            archive.writestr("../escape.txt", "must not escape")
        controls["bytes"] = malicious.read_bytes()
        manifest["components"][0].update(
            sha256=sha(controls["bytes"]), size_bytes=len(controls["bytes"])
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        traversal_root = work / "traversal"
        check("archive traversal is rejected", run(traversal_root) != 0)
        check("archive did not write outside staging", not list(traversal_root.rglob("escape.txt")))

        manifest["components"][0].update(sha256=sha(original), size_bytes=len(original))
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        bad_pin = command(work / "bad-pin")
        bad_pin[bad_pin.index("--manifest-sha256") + 1] = "0" * 64
        check(
            "modified/untrusted manifest is rejected",
            subprocess.run(bad_pin, check=False).returncode != 0,
        )
        server.shutdown()
        server.server_close()
        process = subprocess.Popen(command(resumed_root, install_only=False))
        try:
            for _ in range(300):
                if (resumed_root / "running.json").exists():
                    break
                if process.poll() is not None:
                    raise RuntimeError("offline relaunch exited")
                time.sleep(0.05)
            running = json.loads((resumed_root / "running.json").read_text())
            with urllib.request.urlopen(running["app_url"] + "api/health") as response:
                health = json.load(response)
            check("offline relaunch starts downloaded native backend", health["status"] == "ok")
            results["offline_health"] = health
            results["offline_url"] = running["app_url"]
        finally:
            # Terminate the test backend as well as the parent, including on Windows.
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                # No broad process matching: target only this proof's child tree.
                subprocess.run(["pkill", "-TERM", "-P", str(process.pid)], check=False)
                process.terminate()
            process.wait(timeout=10)
        installed_exe = resumed_root / "versions/m1-proof" / exe.name
        with installed_exe.open("ab") as changed:
            changed.write(b"corrupt")
        check("corrupt installed executable is rejected before launch", run(resumed_root) != 0)
        launcher_zip = work / f"launcher-{manifest['platform']}.zip"
        with zipfile.ZipFile(launcher_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            archive.write(exe, exe.name)
            archive.writestr("README.txt", "M1 engineering prototype. Not a customer installer.\n")
        results.update(
            executable_bytes=exe.stat().st_size,
            compressed_launcher_bytes=launcher_zip.stat().st_size,
            launcher_sha256=sha(launcher_zip.read_bytes()),
        )
        check("launcher ZIP below preferred 19 MB", launcher_zip.stat().st_size < 19_000_000)
    finally:
        (work / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
