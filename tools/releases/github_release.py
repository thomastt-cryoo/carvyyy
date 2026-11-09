"""Publish only audited dependencies; never upload the paid application or launcher."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ASSET = re.compile(r"(runtime|models)-(windows-x86_64|macos-aarch64)-([A-Za-z0-9._-]+)\.zip")


def dependency_inventory(folder: Path, version: str) -> list[dict]:
    paths = sorted(folder.rglob("*.zip"))
    expected = {
        (kind, target)
        for kind in ("runtime", "models")
        for target in ("windows-x86_64", "macos-aarch64")
    }
    found = set()
    result = []
    for path in paths:
        match = ASSET.fullmatch(path.name)
        if not match or match[3] != version or (match[1], match[2]) not in expected - found:
            raise ValueError(f"Refusing unexpected, duplicate or application asset: {path.name}")
        kind, target = match[1], match[2]
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if not names or any(
                not n.startswith(kind + "/")
                or ".." in n.split("/")
                or "\\" in n
                or n.endswith(".env")
                for n in names
            ):
                raise ValueError(f"Unexpected dependency contents: {path.name}")
            if kind == "models" and any(
                "da3" in n.lower() or "v2-large" in n.lower() for n in names
            ):
                raise ValueError("Only the Small depth model may be distributed")
        found.add((kind, target))
        result.append(
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": hashlib.file_digest(path.open("rb"), "sha256").hexdigest(),
                "path": str(path),
            }
        )
    if found != expected:
        raise ValueError("Both supported platforms must provide runtime and model archives")
    return result


class GitHub:
    def __init__(self, repository: str, token: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid GitHub repository")
        self.repository, self.token = repository, token

    def request(self, path, data=None, method="GET", content_type="application/json"):
        url = (
            path
            if path.startswith("https://uploads.github.com/")
            else "https://api.github.com" + path
        )
        headers = {
            "Authorization": "Bearer " + self.token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "PhotoRelief-Release",
            "Content-Type": content_type,
        }
        body = (
            json.dumps(data).encode()
            if data is not None and content_type == "application/json"
            else data
        )
        with urllib.request.urlopen(
            urllib.request.Request(url, data=body, method=method, headers=headers), timeout=600
        ) as response:
            payload = response.read()
            return json.loads(payload) if payload else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", args.version):
        raise ValueError("Invalid immutable release version")
    assets = dependency_inventory(args.assets, args.version)
    api = GitHub(args.repository, os.environ["GH_TOKEN"])
    prefix = "/repos/" + args.repository
    repository = api.request(prefix)
    if repository["private"]:
        raise RuntimeError(
            "Anonymous downloads require an already-public repository; "
            "visibility will not be changed"
        )
    tag = "components-" + args.version
    try:
        api.request(prefix + "/releases/tags/" + tag)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    else:
        raise RuntimeError("Release already exists: never overwrite a published version")
    # An orphan tree keeps GitHub's automatic source archives dependency-only.
    public = [{k: v for k, v in asset.items() if k != "path"} for asset in assets]
    inventory = (json.dumps({"version": args.version, "assets": public}, indent=2) + "\n").encode()
    readme = (
        "# Photo Relief Studio installation dependencies\n\n"
        "Runtime and licensed model components only. "
        "The application and Etsy customer ZIPs are not release assets. "
        "The Small depth model uses Apache-2.0; its pinned revision and "
        "dependency notices are inside the archives.\n"
    )
    tree = api.request(
        prefix + "/git/trees",
        {
            "tree": [
                {"path": "README.md", "mode": "100644", "type": "blob", "content": readme},
                {
                    "path": "DEPENDENCY-CHECKSUMS.json",
                    "mode": "100644",
                    "type": "blob",
                    "content": inventory.decode(),
                },
            ]
        },
        "POST",
    )
    commit = api.request(
        prefix + "/git/commits",
        {
            "message": "Installation dependency inventory " + args.version,
            "tree": tree["sha"],
            "parents": [],
        },
        "POST",
    )
    api.request(prefix + "/git/refs", {"ref": "refs/tags/" + tag, "sha": commit["sha"]}, "POST")
    release = api.request(
        prefix + "/releases",
        {
            "tag_name": tag,
            "name": "Installation components " + args.version,
            "draft": True,
            "prerelease": True,
            "make_latest": "false",
            "body": readme + "\nVersions are never replaced. "
            "Customer launchers pin every archive's size and SHA-256.\n",
        },
        "POST",
    )
    upload = release["upload_url"].split("{")[0]
    for asset in assets:
        uploaded = api.request(
            upload + "?name=" + urllib.parse.quote(asset["name"]),
            Path(asset["path"]).read_bytes(),
            "POST",
            "application/zip",
        )
        if (
            uploaded["size"] != asset["bytes"]
            or uploaded.get("digest") != "sha256:" + asset["sha256"]
        ):
            raise RuntimeError("GitHub asset digest or size disagrees; draft not published")
    api.request(
        upload + "?name=DEPENDENCY-CHECKSUMS.json", inventory, "POST", "application/octet-stream"
    )
    published = api.request(prefix + "/releases/" + str(release["id"]), {"draft": False}, "PATCH")
    if not published.get("immutable"):
        raise RuntimeError(
            "Release was not locked by GitHub. "
            "Enable repository release immutability before qualification"
        )
    args.output.write_text(
        json.dumps(
            {
                "url": published["html_url"],
                "tag": tag,
                "dependency_commit": commit["sha"],
                "immutable": True,
                "assets": public,
            },
            indent=2,
        )
        + "\n"
    )
    print("Published immutable dependency-only release:", published["html_url"])


if __name__ == "__main__":
    main()
