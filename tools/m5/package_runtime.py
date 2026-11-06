"""Build relocatable runtime, application and Small model components from locked sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def archive(source: Path, output: Path, prefix: str, version: str = "1.1.1-m5") -> dict:
    size = 0
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(source.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            size += path.stat().st_size
            z.write(path, prefix + "/" + path.relative_to(source).as_posix())
    return {
        "id": prefix,
        "version": version,
        "required": True,
        "size_bytes": output.stat().st_size,
        "unpacked_limit_bytes": size,
        "sha256": hashlib.file_digest(output.open("rb"), "sha256").hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--uv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-cache", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--version", default="1.1.1-m5")
    args = parser.parse_args()
    version = args.version
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", version):
        raise SystemExit("Use a simple immutable release version.")
    machine = platform.machine().lower()
    target = {"Windows": "windows-x86_64", "Darwin": "macos-aarch64"}.get(platform.system())
    if (
        (target == "windows-x86_64" and machine not in ("amd64", "x86_64"))
        or (target == "macos-aarch64" and machine not in ("arm64", "aarch64"))
        or target is None
    ):
        raise SystemExit("This build supports Windows x64 and macOS arm64 only.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    work = output / "build"
    work.mkdir(exist_ok=False)
    uv = str(args.uv.resolve())
    python_root = work / "interpreters"
    subprocess.run(
        [uv, "python", "install", "3.12.16", "--install-dir", str(python_root), "--no-bin"],
        check=True,
    )
    interpreter = next(python_root.glob("cpython-*"))
    runtime = work / "runtime"
    shutil.copytree(interpreter, runtime, symlinks=False)
    python = runtime / ("python.exe" if platform.system() == "Windows" else "bin/python3.12")
    requirements = work / "requirements.txt"
    subprocess.run(
        [
            uv,
            "export",
            "--frozen",
            "--extra",
            "cpu",
            "--no-dev",
            "--no-emit-project",
            "--output-file",
            str(requirements),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        check=True,
    )
    subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "--system",
            "--break-system-packages",
            "--index",
            "https://download.pytorch.org/whl/cpu",
            "--index-strategy",
            "unsafe-best-match",
            "--no-deps",
            "--require-hashes",
            "-r",
            str(requirements),
        ],
        check=True,
    )
    application = work / "application"
    application.mkdir()
    for name in ("app", "static"):
        shutil.copytree(
            ROOT / name, application / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
    shutil.copy2(ROOT / "LICENSE", application / "LICENSE")
    shutil.copy2(ROOT / "uv.lock", application / "uv.lock")
    notices = []
    for metadata in runtime.rglob("*.dist-info"):
        for entry in metadata.rglob("*"):
            if entry.is_file() and (
                "license" in entry.name.lower() or "notice" in entry.name.lower()
            ):
                notices.append(str(entry.relative_to(runtime)))
    (application / "DEPENDENCY-NOTICES.json").write_text(json.dumps(notices, indent=2))
    # Dereference HF cache symlinks so the model component works on extracted systems.
    cache = args.model_cache.resolve() / "hub/models--depth-anything--Depth-Anything-V2-Small-hf"
    model = work / "models/hub/models--depth-anything--Depth-Anything-V2-Small-hf"
    shutil.copytree(
        cache,
        model,
        symlinks=False,
        ignore=shutil.ignore_patterns(".locks", "*.incomplete", "blobs"),
    )
    shutil.copy2(ROOT / "LICENSE", work / "models/APACHE-2.0.txt")
    (work / "models/MODEL-NOTICE.txt").write_text(
        "Depth Anything V2 Small, depth-anything/Depth-Anything-V2-Small-hf.\n"
        "Source https://huggingface.co/depth-anything/Depth-Anything-V2-Small-hf\n"
        "License Apache-2.0. This archive contains only Small model weights.\n"
        "Model snapshot " + (cache / "refs/main").read_text().strip() + "\n"
    )
    components = []
    for name, folder in [
        ("runtime", runtime),
        ("application", application),
        ("models", work / "models"),
    ]:
        filename = f"{name}-{target}-{version}.zip"
        component = archive(folder, output / filename, name, version)
        component["url"] = args.base_url.rstrip("/") + "/" + filename
        components.append(component)
    manifest = {
        "schema_version": 2,
        "version": version,
        "platform": target,
        "compatibility": {"python": "3.12", "device": "cpu"},
        "components": components,
        "executable": "runtime/python.exe"
        if target.startswith("windows")
        else "runtime/bin/python3.12",
        "arguments": ["-s", "-m", "app.packaged"],
    }
    # Modules are found from the application directory supplied to the supervisor.
    data = (json.dumps(manifest, indent=2) + "\n").encode()
    (output / "release.json").write_bytes(data)
    (output / "release.sha256").write_text(hashlib.sha256(data).hexdigest() + "\n")
    print(
        json.dumps(
            {
                "platform": target,
                "manifest_sha256": hashlib.sha256(data).hexdigest(),
                "components": components,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
