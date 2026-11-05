"""Explicit one-time model download; normal application editing stays offline."""

import hashlib
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.segmentation import MODEL_BYTES, MODEL_SHA256, MODEL_URL, model_path  # noqa: E402


def main():
    path = model_path()
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == MODEL_SHA256:
        print(f"Verified existing model: {path}")
        return
    with urllib.request.urlopen(MODEL_URL, timeout=120) as response:
        content = response.read(MODEL_BYTES + 1)
    if len(content) != MODEL_BYTES or hashlib.sha256(content).hexdigest() != MODEL_SHA256:
        raise SystemExit("Model checksum/size mismatch; nothing installed.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".download")
    temporary.write_bytes(content)
    temporary.replace(path)
    print(f"Installed verified U2NETP: {path} ({len(content)} bytes)")


if __name__ == "__main__":
    main()
