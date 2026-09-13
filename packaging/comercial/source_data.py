"""Resolve PyInstaller package data only from an explicit source checkout."""
from __future__ import annotations

from pathlib import Path


def source_data_files(
    root: Path,
    package: str,
    *,
    excluded_names: frozenset[str] = frozenset(),
) -> list[tuple[str, str]]:
    package_root = (root / package).resolve()
    if not package_root.is_dir():
        raise RuntimeError(f"source data package is absent: {package}")
    return [
        (str(path), path.parent.relative_to(root).as_posix())
        for path in sorted(package_root.rglob("*"))
        if path.is_file()
        and path.name not in excluded_names
        and path.suffix.lower() not in {".py", ".pyc"}
        and "__pycache__" not in path.parts
    ]
