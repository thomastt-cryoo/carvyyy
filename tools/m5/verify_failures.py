"""Controlled network failure checks against a pinned native candidate."""

from __future__ import annotations

import argparse
import http.server
import json
import shutil
import socket
import subprocess
import threading
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    release = args.release.resolve()
    manifest = json.loads((release / "release.json").read_text())
    app = next(c for c in manifest["components"] if c["id"] == "application")
    controls = {"mode": "interrupt", "ranges": []}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            controls["ranges"].append(self.headers.get("Range"))
            data = (release / app["url"].rsplit("/", 1)[1]).read_bytes()
            value = self.headers.get("Range")
            offset = int(value[6:-1]) if value else 0
            self.send_response(206 if value else 200)
            self.send_header("Content-Length", str(len(data) - offset))
            if value:
                self.send_header("Content-Range", f"bytes {offset}-{len(data) - 1}/{len(data)}")
            self.end_headers()
            if controls["mode"] == "interrupt":
                self.wfile.write(data[offset : offset + 65536])
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
            elif controls["mode"] == "corrupt":
                self.wfile.write(bytes([data[offset] ^ 1]) + data[offset + 1 :])
            else:
                self.wfile.write(data[offset:])

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 18155), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    root = output / "installation"
    downloads = root / "downloads"
    downloads.mkdir(parents=True)
    (root / "data").mkdir()
    (root / "data/project-sentinel").write_bytes(b"preserve customer work")
    for component in manifest["components"]:
        if component["id"] != "application":
            shutil.copy2(
                release / component["url"].rsplit("/", 1)[1],
                downloads / (component["sha256"] + ".zip"),
            )
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
        "--install-only",
    ]
    try:
        first = subprocess.run(command, timeout=120)
        assert first.returncode != 0
        partial = downloads / (app["sha256"] + ".part")
        assert 0 < partial.stat().st_size < app["size_bytes"]
        assert not (root / "versions").exists()
        controls["mode"] = "corrupt"
        second = subprocess.run(command, timeout=120)
        assert second.returncode != 0
        assert not partial.exists()
        assert any(value and value.startswith("bytes=65536-") for value in controls["ranges"])
        assert not (root / "versions").exists()
        controls["mode"] = "complete"
        third = subprocess.run(command, timeout=600)
        assert third.returncode == 0
        assert (root / "data/project-sentinel").read_bytes() == b"preserve customer work"
        record = {
            "interrupted_download_preserved": True,
            "http_range_used": True,
            "complete_corruption_rejected_and_discarded": True,
            "retry_installation_passed": True,
            "customer_data_preserved": True,
        }
        (output / "results.json").write_text(json.dumps(record, indent=2))
        print(json.dumps(record, indent=2))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
