"""Upload immutable components to an owner-configured R2 custom domain."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen


def main():
    import boto3
    from botocore.exceptions import ClientError

    parser = argparse.ArgumentParser()
    parser.add_argument("release", type=Path)
    args = parser.parse_args()
    folder = args.release.resolve()
    endpoint = os.environ["R2_ENDPOINT"]
    bucket = os.environ["R2_BUCKET"]
    public = os.environ["R2_PUBLIC_BASE_URL"].rstrip("/")
    if urlparse(endpoint).scheme != "https" or urlparse(public).scheme != "https":
        raise SystemExit("R2 endpoint and custom-domain base must use HTTPS.")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="auto",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    )
    manifest = json.loads((folder / "release.json").read_text())
    for component in manifest["components"]:
        if not component["url"].startswith(public + "/"):
            raise SystemExit("Manifest URL differs from the configured public base.")
        key = component["url"][len(public) + 1 :]
        file = folder / Path(key).name
        with file.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != component["sha256"] or file.stat().st_size != component["size_bytes"]:
            raise SystemExit("Local component failed verification.")
        try:
            existing = client.head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
                raise
            existing = None
        if existing:
            if existing["Metadata"].get("sha256") != digest:
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
                CacheControl="public, max-age=31536000, immutable",
            )
        verified = client.head_object(Bucket=bucket, Key=key)
        if (
            verified["ContentLength"] != file.stat().st_size
            or verified["Metadata"].get("sha256") != digest
        ):
            raise SystemExit("R2 verification failed.")
    for component in manifest["components"]:
        digest = hashlib.sha256()
        total = 0
        with urlopen(component["url"], timeout=60) as response:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                digest.update(chunk)
        if total != component["size_bytes"] or digest.hexdigest() != component["sha256"]:
            raise SystemExit("Public custom-domain download failed integrity verification.")
    print("R2 uploads and public custom-domain downloads verified.")


if __name__ == "__main__":
    main()
