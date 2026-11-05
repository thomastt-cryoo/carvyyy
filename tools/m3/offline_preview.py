"""Local acceptance proxy: browser CSP forbids all external origins.

Run the normal offline-configured backend on 8098 first. This proxy is a test
fixture, not a distribution component. It records paths/statuses only.
"""

import json
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

POLICY = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "connect-src 'self' blob:; font-src 'self'; worker-src 'self' blob:; "
    "object-src 'none'; frame-src 'none'; base-uri 'self'"
)
TRACE = Path("data/m3/offline-browser-requests.jsonl")
TRACE_LOCK = Lock()


class OfflinePreview(BaseHTTPRequestHandler):
    def forward(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        request = urllib.request.Request(
            "http://127.0.0.1:8098" + self.path,
            data=body if body else None,
            method=self.command,
            headers={
                key: value
                for key, value in self.headers.items()
                if key.lower() not in {"host", "connection", "accept-encoding"}
            },
        )
        try:
            response = urllib.request.urlopen(request, timeout=120)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            content = response.read()
            self.send_response(response.status)
            for key, value in response.headers.items():
                if key.lower() not in {
                    "content-length",
                    "connection",
                    "transfer-encoding",
                    "cache-control",
                    "content-security-policy",
                }:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Content-Security-Policy", POLICY)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
            TRACE.parent.mkdir(parents=True, exist_ok=True)
            with TRACE_LOCK, TRACE.open("a", encoding="utf-8") as trace:
                trace.write(
                    json.dumps(
                        {"method": self.command, "path": self.path, "status": response.status}
                    )
                    + "\n"
                )

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = forward

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    TRACE.parent.mkdir(parents=True, exist_ok=True)
    TRACE.write_text("", encoding="utf-8")
    print("External-origin-blocked browser acceptance: http://127.0.0.1:8100", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8100), OfflinePreview).serve_forever()
