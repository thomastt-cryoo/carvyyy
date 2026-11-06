"""Upload immutable components to an owner-configured R2 custom domain."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # The launcher also refuses component redirects.


def verify_public_component(opener, component, file):
    size = component["size_bytes"]
    digest = hashlib.sha256()
    total = 0
    with opener.open(component["url"], timeout=60) as response:
        if response.status != 200:
            raise SystemExit("Public component did not return HTTP 200.")
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > size:
                raise SystemExit("Public custom-domain download exceeds the manifest size.")
            digest.update(chunk)
    if total != size or digest.hexdigest() != component["sha256"]:
        raise SystemExit("Public custom-domain download failed integrity verification.")
    # Check that an open-ended resume yields the expected range and bytes.
    offset = max(0, size - 1024)
    request = Request(component["url"], headers={"Range": f"bytes={offset}-"})
    with opener.open(request, timeout=60) as response, file.open("rb") as source:
        source.seek(offset)
        if (
            response.status != 206
            or response.headers.get("Content-Range") != f"bytes {offset}-{size - 1}/{size}"
            or response.read(1025) != source.read()
        ):
            raise SystemExit("Public custom domain did not serve the expected resume range.")


def main():
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError

    parser = argparse.ArgumentParser()
    parser.add_argument("release", type=Path)
    args = parser.parse_args()
    folder = args.release.resolve()
    endpoint = os.environ["R2_ENDPOINT"]
    bucket = os.environ["R2_BUCKET"]
    public = os.environ["R2_PUBLIC_BASE_URL"].rstrip("/")
    if any(
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        for url in map(urlparse, (endpoint, public))
    ):
        raise SystemExit("R2 endpoint and custom-domain base must use HTTPS.")
    if urlparse(public).hostname.endswith((".r2.dev", ".r2.cloudflarestorage.com")):
        raise SystemExit("Use the public custom domain connected to your R2 bucket.")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="auto",
        config=Config(
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )
    manifest = json.loads((folder / "release.json").read_text())
    components = []
    for component in manifest["components"]:
        if not component["url"].startswith(public + "/"):
            raise SystemExit("Manifest URL differs from the configured public base.")
        key = component["url"][len(public) + 1 :]
        file = folder / Path(key).name
        with file.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != component["sha256"] or file.stat().st_size != component["size_bytes"]:
            raise SystemExit("Local component failed verification.")
        components.append((component, key, file, digest))
    for component, key, file, digest in components:
        try:
            existing = client.head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
                raise
            existing = None
        if existing:
            if (
                existing["Metadata"].get("sha256") != digest
                or existing["ContentLength"] != component["size_bytes"]
            ):
                raise SystemExit("Immutable remote object differs. Use a new release version.")
            continue
        # Conditional create prevents concurrent publishers replacing immutable objects.
        with file.open("rb") as stream:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=stream,
                IfNoneMatch="*",
                Metadata={"sha256": digest},
                ContentType="application/zip",
                CacheControl="public, max-age=31536000, immutable, no-transform",
            )
        verified = client.head_object(Bucket=bucket, Key=key)
        if (
            verified["ContentLength"] != file.stat().st_size
            or verified["Metadata"].get("sha256") != digest
        ):
            raise SystemExit("R2 verification failed.")
    opener = build_opener(NoRedirect())
    for component, _, file, _ in components:
        verify_public_component(opener, component, file)
    print("R2 uploads and public custom-domain downloads verified.")


if __name__ == "__main__":
    main()
