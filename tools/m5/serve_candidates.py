"""Controlled loopback component server for native setup UI acceptance."""

from __future__ import annotations

import argparse
import json
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    args = parser.parse_args()
    release = args.release.resolve()
    manifest = json.loads((release / "release.json").read_text())
    allowed = {component["url"].rsplit("/", 1)[1] for component in manifest["components"]}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            name = self.path.removeprefix("/")
            if name not in allowed:
                self.send_error(404)
                return
            file = release / name
            size = file.stat().st_size
            offset = 0
            value = self.headers.get("Range")
            if value:
                try:
                    offset = int(value.removeprefix("bytes=").removesuffix("-"))
                except ValueError:
                    self.send_error(416)
                    return
            if offset < 0 or offset >= size:
                self.send_error(416)
                return
            self.send_response(206 if value else 200)
            self.send_header("Content-Length", str(size - offset))
            if value:
                self.send_header("Content-Range", f"bytes {offset}-{size - 1}/{size}")
            self.end_headers()
            sent = 0
            try:
                with file.open("rb") as source:
                    source.seek(offset)
                    while chunk := source.read(65536):
                        control = json.loads(args.control.read_text())
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        sent += len(chunk)
                        time.sleep(float(control.get("delay", 0)))
                        if control.get("interrupt") and sent >= 262144:
                            self.connection.shutdown(socket.SHUT_RDWR)
                            self.connection.close()
                            return
            except (OSError, ConnectionError):
                return

    server = ThreadingHTTPServer(("127.0.0.1", 18155), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
