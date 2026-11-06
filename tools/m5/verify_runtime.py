"""Acceptance against a newly extracted production runtime, with real offline inference."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    release = args.release.resolve()
    root = args.root.resolve()
    assert args.resume or not root.exists(), "Use a new clean acceptance root"
    # Controlled server exposes only candidate component ZIPs and implements Range.
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(release), **kw)

        def log_message(self, *_):
            pass

        def do_GET(self):
            path = Path(self.translate_path(self.path))
            if not path.is_file() or path.suffix != ".zip":
                self.send_error(404)
                return
            size = path.stat().st_size
            value = self.headers.get("Range")
            offset = int(value[6:-1]) if value else 0
            self.send_response(206 if value else 200)
            self.send_header("Content-Length", str(size - offset))
            if value:
                self.send_header("Content-Range", f"bytes {offset}-{size - 1}/{size}")
            self.end_headers()
            with path.open("rb") as stream:
                stream.seek(offset)
                while chunk := stream.read(1024 * 1024):
                    self.wfile.write(chunk)

    server = ThreadingHTTPServer(("127.0.0.1", 18155), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    command = [
        str(args.launcher.resolve()),
        "--root",
        str(root),
        "--manifest",
        str(release / "release.json"),
        "--manifest-sha256",
        (release / "release.sha256").read_text().strip(),
        "--allow-local-http",
        "--no-browser",
    ]
    process = subprocess.Popen(command)
    started = time.monotonic()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    result = {"runtime": str(release.name)}
    try:
        while time.monotonic() - started < 600:
            running = root / "running.json"
            if running.exists():
                info = json.loads(running.read_text())
                break
            if process.poll() is not None:
                raise RuntimeError((root / "result.json").read_text())
            time.sleep(0.2)
        else:
            raise TimeoutError("Packaged application did not become ready")
        ready_path = root / "backend-ready.json"
        original_pid = json.loads(ready_path.read_text())["pid"]
        assert subprocess.run(command, timeout=10).returncode == 0
        assert json.loads(ready_path.read_text())["pid"] == original_pid
        result["duplicate_launcher_reused_backend"] = True
        url = info["app_url"]
        base = url.split("/?")[0]
        opener.open(url).read()
        for client, request in [
            (urllib.request, urllib.request.Request(base + "/api/models")),
            (
                opener,
                urllib.request.Request(
                    base + "/api/models", headers={"Origin": "https://unrelated.invalid"}
                ),
            ),
        ]:
            try:
                (
                    client.urlopen(request) if client is urllib.request else client.open(request)
                ).read()
            except urllib.error.HTTPError as error:
                assert error.code == 403
            else:
                raise AssertionError("Unauthorized packaged API access succeeded")
        result["unauthenticated_and_cross_origin_refused"] = True
        result["setup_seconds"] = round(time.monotonic() - started, 2)
        server.shutdown()  # Component downloads are unavailable for the following checks.

        def call(path, data=None, method=None, content_type="application/json"):
            request = urllib.request.Request(
                base + path, data=data, method=method, headers={"Content-Type": content_type}
            )
            response = opener.open(request, timeout=240)
            body = response.read()
            return (
                json.loads(body)
                if "application/json" in response.headers.get("Content-Type", "")
                else body
            )

        source = args.source.read_bytes()
        boundary = "relief-m5-test-upload"
        multipart = (
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
                'filename="offline-tiger.png"\r\n'
                "Content-Type: image/png\r\n\r\n"
            ).encode()
            + source
            + f"\r\n--{boundary}--\r\n".encode()
        )
        document = call(
            "/api/projects/upload?model_id=da2-small",
            multipart,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        sid = document["id"]
        inference_start = time.monotonic()
        for _ in range(900):
            document = call("/api/projects/" + sid)
            if document["status"] == "ready":
                break
            if document["status"] == "error":
                raise RuntimeError(document)
            time.sleep(0.2)
        assert document["status"] == "ready"
        result["fresh_inference_seconds"] = round(time.monotonic() - inference_start, 2)
        result["saved_project"] = sid
        for format in ("stl", "obj"):
            params = call(f"/api/sessions/{sid}/params") | {
                "resolution": 512,
                "output_format": format,
            }
            job = call(f"/api/sessions/{sid}/export", json.dumps(params).encode())["job_id"]
            for _ in range(900):
                state = call("/api/jobs/" + job)
                if state["status"] != "processing":
                    break
                time.sleep(0.2)
            assert state["status"] == "ready", state
            content = call(state["download_url"])
            assert len(content) > 1000
            result[format + "_bytes"] = len(content)
        call("/api/launcher/shutdown", b"")
        process.wait(timeout=30)
        assert process.returncode == 0
        running.unlink()
        process = subprocess.Popen(command)
        restart = time.monotonic()
        while time.monotonic() - restart < 300:
            if running.exists():
                info = json.loads(running.read_text())
                break
            if process.poll() is not None:
                raise RuntimeError("Offline relaunch failed")
            time.sleep(0.2)
        else:
            raise TimeoutError("Offline relaunch did not become ready")
        base = info["app_url"].split("/?")[0]
        opener.open(info["app_url"]).read()
        assert call("/api/projects/" + sid)["id"] == sid
        result["offline_reopen_seconds"] = round(time.monotonic() - restart, 2)
        result["project_preserved"] = True
        call("/api/launcher/shutdown", b"")
        process.wait(timeout=30)
        assert process.returncode == 0
        (root / "acceptance.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
    finally:
        server.server_close()
        if process.poll() is None:
            process.terminate()


if __name__ == "__main__":
    main()
