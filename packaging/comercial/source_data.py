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


def _canonical_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).strip("-").lower()


def _path_components(value: object) -> tuple[str, ...]:
    text = str(value or "").replace("\\", "/")
    return tuple(part for part in text.split("/") if part and part not in {".", ".."})


def _distribution_name_from_dist_info_dir(dirname: str) -> str | None:
    if not dirname.lower().endswith(".dist-info"):
        return None
    stem = dirname[: -len(".dist-info")]
    matched = re.fullmatch(r"(.+)-([0-9].*)", stem)
    if matched is None:
        return None
    return matched.group(1)


def _first_party_dist_info_dir(
    components: tuple[str, ...], canonical_name: str
) -> str | None:
    for part in components:
        distribution = _distribution_name_from_dist_info_dir(part)
        if distribution is None:
            continue
        if _canonical_distribution_name(distribution) == canonical_name:
            return part
    return None


def _toc_dest_src(entry: object) -> tuple[str, str]:
    if not isinstance(entry, (tuple, list)) or len(entry) < 2:
        raise RuntimeError("packaging TOC entry is not a path pair or triple")
    if len(entry) >= 3:
        return str(entry[0]), str(entry[1])
    return str(entry[1]), str(entry[0])


def first_party_dist_info_dest_names(toc: list, root: Path) -> list[str]:
    """Destination filenames inside first-party dist-info (normalized)."""
    canonical = _canonical_distribution_name(_project_identity(root)[0])
    names: list[str] = []
    for entry in toc:
        dest, src = _toc_dest_src(entry)
        dist_dir = _first_party_dist_info_dir(
            _path_components(dest), canonical
        ) or _first_party_dist_info_dir(_path_components(src), canonical)
        if dist_dir is None:
            continue
        dest_parts = _path_components(dest)
        names.append(dest_parts[-1] if dest_parts else dist_dir)
    return names


def filter_first_party_runtime_metadata(
    root: Path,
    toc: list,
    metadata_dir: Path,
) -> list:
    """Remove hook-reintroduced first-party dist-info; keep source METADATA.

    Call after Analysis and pass the result to PYZ/EXE/COLLECT.  Do not assign
    the result back onto Analysis; Analysis-00.toc stays the unfiltered
    diagnostic.  Third-party metadata entries are unchanged.
    """
    name, version = validate_runtime_metadata(root, metadata_dir)
    canonical = _canonical_distribution_name(name)
    authorized_src = metadata_dir / "METADATA"
    if not authorized_src.is_file():
        raise RuntimeError("source runtime METADATA is absent")
    if version not in metadata_dir.name:
        raise RuntimeError("runtime metadata directory does not match source version")
    authorized_dest = f"{metadata_dir.name}/METADATA"
    kept: list = []
    for entry in toc:
        dest, src = _toc_dest_src(entry)
        if _first_party_dist_info_dir(_path_components(dest), canonical):
            continue
        if _first_party_dist_info_dir(_path_components(src), canonical):
            continue
        kept.append(entry)
    kept.append((authorized_dest, str(authorized_src), "DATA"))
    return kept
