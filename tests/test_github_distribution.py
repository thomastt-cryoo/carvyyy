"""Public release allowlist must exclude the application and customer data."""

import zipfile

import pytest

from tools.releases.github_release import dependency_inventory


def write_zip(path, member):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, b"licensed dependency fixture")


def dependencies(folder):
    for kind in ("runtime", "models"):
        for target in ("windows-x86_64", "macos-aarch64"):
            write_zip(folder / f"{kind}-{target}-test1.zip", kind + "/dependency.txt")


def test_publisher_accepts_only_complete_matching_dependency_set(tmp_path):
    dependencies(tmp_path)
    result = dependency_inventory(tmp_path, "test1")
    assert len(result) == 4 and all(row["bytes"] > 0 and len(row["sha256"]) == 64 for row in result)
    with pytest.raises(ValueError, match="unexpected"):
        dependency_inventory(tmp_path, "different-version")


@pytest.mark.parametrize(
    "filename,member",
    [
        ("application-windows-x86_64-test1.zip", "application/app/main.py"),
        ("runtime-windows-x86_64-test1.zip", "application/app/main.py"),
        ("models-windows-x86_64-test1.zip", "models/../customer-photo.png"),
        ("models-windows-x86_64-test1.zip", "models/da3/weights.bin"),
        ("models-windows-x86_64-test1.zip", "models/Depth-Anything-V2-Large/model.bin"),
    ],
)
def test_publisher_refuses_application_data_and_removed_models(tmp_path, filename, member):
    dependencies(tmp_path)
    write_zip(tmp_path / filename, member)
    with pytest.raises(ValueError):
        dependency_inventory(tmp_path, "test1")


def test_publisher_refuses_incomplete_platforms(tmp_path):
    write_zip(tmp_path / "runtime-windows-x86_64-test1.zip", "runtime/python.exe")
    with pytest.raises(ValueError, match="Both supported"):
        dependency_inventory(tmp_path, "test1")
