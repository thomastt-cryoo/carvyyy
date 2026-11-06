"""Per-launch browser authentication for the packaged loopback service."""

from __future__ import annotations

import secrets
from http.cookies import SimpleCookie
from urllib.parse import parse_qs


class LocalAccess:
    def __init__(self, app, *, token: str, port: int):
        self.app = app
        self.token = token
        self.authority = f"127.0.0.1:{port}"
        self.origin = f"http://{self.authority}"
        self.shutdown = None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        host = headers.get(b"host", b"").decode("latin1")
        origin = headers.get(b"origin", b"").decode("latin1")
        if host != self.authority or (origin and origin != self.origin):
            return await self.reject(send)
        query = parse_qs(scope.get("query_string", b"").decode("ascii", errors="ignore"))
        supplied = query.get("launch", [""])[0]
        if (
            scope["path"] == "/"
            and supplied
            and secrets.compare_digest(supplied.encode(), self.token.encode())
        ):
            await send(
                {
                    "type": "http.response.start",
                    "status": 303,
                    "headers": [
                        (b"location", b"/"),
                        (
                            b"set-cookie",
                            (
                                f"relief_access={self.token}; HttpOnly; SameSite=Strict; Path=/"
                            ).encode(),
                        ),
                        (b"referrer-policy", b"no-referrer"),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            return await send({"type": "http.response.body", "body": b""})
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get(b"cookie", b"").decode("latin1"))
        except Exception:
            return await self.reject(send)
        cookie = cookies.get("relief_access")
        credential = cookie.value if cookie else ""
        # The launcher readiness probe uses the same secret without browser cookies.
        if scope["path"] == "/api/health":
            credential = headers.get(b"x-relief-token", credential.encode()).decode("latin1")
        if not secrets.compare_digest(credential.encode(), self.token.encode()):
            return await self.reject(send)
        if scope["path"] == "/api/launcher/status":
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            return await send({"type": "http.response.body", "body": b'{"can_shutdown":true}'})
        if scope["path"] == "/api/launcher/shutdown" and scope["method"] == "POST":
            if self.shutdown is not None:
                if not self.shutdown():
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 409,
                            "headers": [
                                (b"content-type", b"application/json"),
                            ],
                        }
                    )
                    return await send(
                        {
                            "type": "http.response.body",
                            "body": b'{"detail":"Work is running. Try quitting again shortly."}',
                        }
                    )
                await send(
                    {
                        "type": "http.response.start",
                        "status": 202,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                return await send({"type": "http.response.body", "body": b'{"stopping":true}'})
        await self.app(scope, receive, send)

    @staticmethod
    async def reject(send):
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"text/plain"),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send(
            {"type": "http.response.body", "body": b"Open Photo Relief Studio from its launcher."}
        )
