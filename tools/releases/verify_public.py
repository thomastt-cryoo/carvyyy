"""Verify actual stable GitHub asset URLs without GitHub credentials or cookies."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.release / "release.json").read_bytes())
    records = []
    # No Authorization, cookies, token query, API lookup or latest-release endpoint.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for item in manifest["components"]:
        if "bundled_path" in item:
            assert item["id"] == "application" and not item.get("url")
            continue
        url = item["url"]
        assert url.startswith("https://github.com/") and "/releases/download/components-" in url
        digest = hashlib.sha256()
        size = 0
        with opener.open(
            urllib.request.Request(url, headers={"User-Agent": "PhotoRelief-Anonymous-Test"}),
            timeout=180,
        ) as response:
            assert response.status == 200 and response.url.startswith("https://")
            final_host = urllib.parse.urlparse(response.url).hostname
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
        assert size == item["size_bytes"] and digest.hexdigest() == item["sha256"]
        offset = min(65536, size - 1)
        request = urllib.request.Request(
            url,
            headers={
                "Range": f"bytes={offset}-",
                "User-Agent": "PhotoRelief-Anonymous-Resume-Test",
            },
        )
        with opener.open(request, timeout=180) as response:
            assert response.status == 206
            assert response.headers["Content-Range"] == f"bytes {offset}-{size - 1}/{size}"
            # Confirm a real partial body. The native installation tests exercise the full transfer.
            assert response.read(min(1024, size - offset))
        records.append(
            {
                "url": url,
                "http_status": 200,
                "anonymous": True,
                "bytes": size,
                "sha256": digest.hexdigest(),
                "redirect_host": final_host,
                "range_status": 206,
            }
        )
    assert {item["id"] for item in manifest["components"] if "bundled_path" not in item} == {
        "runtime",
        "models",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {"platform": manifest["platform"], "downloads": records, "application_bundled": True},
            indent=2,
        )
        + "\n"
    )
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
