"""Create a small customer ZIP around a launcher compiled with the release pin."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import plistlib
import shutil
import subprocess
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    args = parser.parse_args()
    release = args.release.resolve()
    manifest = release / "release.json"
    pin = hashlib.sha256(manifest.read_bytes()).hexdigest()
    # A pinned build must contain the exact compiled-in root for this manifest.
    if pin.encode() not in args.binary.read_bytes():
        raise SystemExit("Build the launcher with P2R_MANIFEST_SHA256 matching this manifest.")
    target = json.loads(manifest.read_text())["platform"]
    staging = release / "launcher"
    staging.mkdir(exist_ok=False)
    if target == "windows-x86_64" and platform.system() == "Windows":
        shutil.copy2(args.binary, staging / "Photo Relief Studio.exe")
        shutil.copy2(manifest, staging / "release.json")
    elif target == "macos-aarch64" and platform.system() == "Darwin":
        bundle = staging / "Photo Relief Studio.app/Contents"
        executable = bundle / "MacOS"
        executable.mkdir(parents=True)
        shutil.copy2(args.binary, executable / "Photo Relief Studio")
        (executable / "Photo Relief Studio").chmod(0o755)
        shutil.copy2(manifest, executable / "release.json")
        (bundle / "Info.plist").write_bytes(
            plistlib.dumps(
                {
                    "CFBundleExecutable": "Photo Relief Studio",
                    "CFBundleIdentifier": "com.photorelief.studio",
                    "CFBundleName": "Photo Relief Studio",
                    "CFBundlePackageType": "APPL",
                    "CFBundleShortVersionString": "1.1.1",
                    "LSMinimumSystemVersion": "15.0",
                    "LSUIElement": True,
                }
            )
        )
    else:
        raise SystemExit("Build native launchers only on the matching supported architecture.")
    repository = Path(__file__).resolve().parents[2]
    metadata = json.loads(
        subprocess.check_output(
            [
                "cargo",
                "metadata",
                "--format-version",
                "1",
                "--locked",
                "--manifest-path",
                str(repository / "bootstrapper/Cargo.toml"),
            ],
            cwd=repository,
        )
    )
    notices = ["Photo Relief Studio native launcher dependency notices\n"]
    for package in sorted(metadata["packages"], key=lambda item: item["name"]):
        notices.append(f"\n{package['name']} {package['version']} ({package.get('license')})\n")
        if package.get("repository"):
            notices.append(package["repository"] + "\n")
        folder = Path(package["manifest_path"]).parent
        license_files = (
            set(folder.glob("LICENSE*"))
            | set(folder.glob("NOTICE*"))
            | set(folder.glob("COPYRIGHT*"))
        )
        if package.get("license_file"):
            license_files.add(folder / package["license_file"])
        for file in sorted(license_files):
            if file.is_file():
                notices.append(file.read_text(encoding="utf-8", errors="replace") + "\n")
    (staging / "DEPENDENCY-NOTICES.txt").write_text("".join(notices), encoding="utf-8")
    guide = Path(__file__).resolve().parents[2] / "docs/m5/CUSTOMER-GUIDE.md"
    shutil.copy2(guide, staging / "Start here.txt")
    archive = release / f"Photo-Relief-Studio-{target}-TEST.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(staging.rglob("*")):
            z.write(path, path.relative_to(staging).as_posix())
    size = archive.stat().st_size
    if size >= 19_000_000:
        raise SystemExit(f"Launcher exceeds internal 19 MB budget ({size} bytes).")
    result = {
        "file": archive.name,
        "bytes": size,
        "sha256": hashlib.file_digest(archive.open("rb"), "sha256").hexdigest(),
        "manifest_sha256": pin,
        "signing": "unsigned test candidate",
    }
    (release / "launcher-checksums.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
