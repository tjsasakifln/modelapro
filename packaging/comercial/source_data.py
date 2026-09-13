"""Resolve PyInstaller package data only from an explicit source checkout."""
from __future__ import annotations

import re
import tomllib
from email.parser import Parser
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


def source_submodules(source_root: Path, package: str) -> list[str]:
    """Enumerate import names from one explicit first-party source root."""
    package_root = (source_root / package).resolve()
    if not package_root.is_dir() or not (package_root / "__init__.py").is_file():
        raise RuntimeError(f"source Python package is absent: {package}")
    names = []
    for path in sorted(package_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(source_root).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        if parts:
            names.append(".".join(parts))
    return names


def _project_identity(root: Path) -> tuple[str, str]:
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]
        name = str(project["name"])
        version = str(project["version"])
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError("source project name/version is absent or invalid") from exc
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+!-]*", version)
    ):
        raise RuntimeError("source project name/version is absent or invalid")
    return name, version


def write_runtime_metadata(root: Path, staging_root: Path) -> Path:
    """Stage only source-declared name/version for importlib.metadata at runtime."""
    name, version = _project_identity(root)
    if staging_root.exists() and any(staging_root.iterdir()):
        raise RuntimeError("runtime metadata staging directory must be empty")
    staging_root.mkdir(parents=True, exist_ok=True)
    normalized_name = re.sub(r"[-_.]+", "_", name)
    metadata_dir = staging_root / f"{normalized_name}-{version}.dist-info"
    metadata_dir.mkdir()
    (metadata_dir / "METADATA").write_text(
        f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
        newline="\n",
    )
    return metadata_dir


def validate_runtime_metadata(root: Path, metadata_dir: Path) -> tuple[str, str]:
    """Reject stale or expanded metadata before it enters the frozen bundle."""
    expected = _project_identity(root)
    if not metadata_dir.is_dir() or sorted(p.name for p in metadata_dir.iterdir()) != [
        "METADATA"
    ]:
        raise RuntimeError("runtime metadata must contain only METADATA")
    try:
        parsed = Parser().parsestr(
            (metadata_dir / "METADATA").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("runtime metadata is absent or invalid") from exc
    observed = (str(parsed.get("Name") or ""), str(parsed.get("Version") or ""))
    if observed != expected:
        raise RuntimeError("runtime metadata differs from source project identity")
    return observed
