"""Local storage boundaries. Never follow links/reparse points below managed roots."""

from __future__ import annotations

import os
import stat
from pathlib import Path


class UnsafePathError(ValueError):
    pass


def is_link(path: Path) -> bool:
    if path.is_symlink() or path.is_junction():
        return True
    try:
        return bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (FileNotFoundError, AttributeError):
        return False


def contained_path(root: Path, *parts: str | Path) -> Path:
    root = Path(os.path.abspath(root))
    path = root.joinpath(*parts)
    # Compare lexical paths before resolve: resolving first would hide a linked root.
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise UnsafePathError("The storage path leaves its managed folder.") from exc
    if any(part in {"..", "."} for part in relative.parts):
        raise UnsafePathError("The storage path is not canonical.")
    current = root
    for part in (None, *relative.parts):
        if part is not None:
            current = current / part
        if is_link(current):
            raise UnsafePathError("Linked folders and files are not managed project storage.")
    if not path.resolve().is_relative_to(root.resolve()):
        raise UnsafePathError("The storage path leaves its managed folder.")
    return path
