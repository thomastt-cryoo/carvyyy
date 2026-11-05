"""The shipped workspace graph must be self-contained, without a CDN build step."""

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from app.main import app

STATIC = Path(__file__).parents[1] / "static"


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script" and attributes.get("src"):
            self.paths.append(attributes["src"])
        if tag == "link" and attributes.get("rel") == "stylesheet":
            self.paths.append(attributes["href"])


def test_workspace_static_asset_graph_is_local_and_served():
    client = TestClient(app)
    source = client.get("/").text
    parser = Assets()
    parser.feed(source)
    mappings = json.loads(re.search(r'<script type="importmap">(.*?)</script>', source, re.S)[1])[
        "imports"
    ]
    visited = set()
    for url in parser.paths:
        assert not urlsplit(url).scheme and not urlsplit(url).netloc
        assert client.get(url).status_code == 200
    pending = [STATIC / urlsplit(url).path.lstrip("/") for url in parser.paths]
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        assert path.resolve().is_relative_to(STATIC.resolve())
        assert path.is_file(), path
        url = "/" + path.relative_to(STATIC).as_posix()
        assert client.get(url).status_code == 200
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".css":
            assert not re.search(r"@import|https?://", text)
        if path.suffix == ".js":
            imports = re.findall(
                r'(?m)^\s*(?:import|export)\b[\w*{},\s]+?\bfrom\s*[\'"]([^\'"]+)[\'"]',
                text,
            )
            for item in imports:
                target = mappings.get(item, item)
                assert not re.match(r"\w+:", target), target
                target = urlsplit(target).path
                pending.append(
                    STATIC / target.lstrip("/") if target.startswith("/") else path.parent / target
                )
    assert STATIC / "workspace.js" in visited
    assert STATIC / "vendor/three/three.module.js" in visited
