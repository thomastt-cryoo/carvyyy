"""Packaged browser access must reject unrelated sites and unauthenticated clients."""

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.local_security import LocalAccess


def test_launch_authentication_and_origin_checks():
    app = Starlette(
        routes=[
            Route("/", lambda request: PlainTextResponse("workspace")),
            Route("/api/health", lambda request: PlainTextResponse("ready")),
        ]
    )
    token = "a" * 64
    client = TestClient(
        LocalAccess(app, token=token, port=12345), base_url="http://127.0.0.1:12345"
    )
    assert client.get("/").status_code == 403
    assert client.get("/?launch=wrong").status_code == 403
    assert client.get("/?launch=%C3%A9").status_code == 403
    response = client.get(f"/?launch={token}")
    assert response.text == "workspace"
    assert "HttpOnly" in response.history[0].headers["set-cookie"]
    assert client.get("/", headers={"Origin": "https://attacker.invalid"}).status_code == 403
    assert client.get("/", headers={"Host": "attacker.invalid"}).status_code == 403
    assert client.get("/", headers={"Origin": "http://127.0.0.1:12345"}).status_code == 200
    client.cookies.clear()
    assert client.get("/api/health").status_code == 403
    assert client.get("/api/health", headers={"X-Relief-Token": token}).status_code == 200


def test_shutdown_requires_authentication_and_idle_backend():
    app = LocalAccess(Starlette(), token="b" * 64, port=12346)
    app.shutdown = lambda: False
    client = TestClient(app, base_url="http://127.0.0.1:12346")
    assert client.post("/api/launcher/shutdown").status_code == 403
    client.get("/?launch=" + "b" * 64)
    assert client.post("/api/launcher/shutdown").status_code == 409
    app.shutdown = lambda: True
    assert client.post("/api/launcher/shutdown").json() == {"stopping": True}
