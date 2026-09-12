"""Read canonical packaging metadata from pyproject.toml."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

_REQ_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._\-]*)")

REQUIRED_RUNTIME_IMPORTS = frozenset(
    {
        "streamlit",
        "httpx",
        "fastapi",
        "uvicorn",
        "pandas",
        "numpy",
        "scipy",
        "statsmodels",
        "matplotlib",
        "seaborn",
        "python-multipart",
        "jinja2",
        "weasyprint",
        "python-dotenv",
        "websockets",
        "psutil",
        "requests",
        "openpyxl",
        "xlrd",
        "cryptography",
        "pyhanko",
    }
)
ANNOUNCED_FORMAT_ENGINES = {
    "csv": "pandas",
    "xlsx": "openpyxl",
    "xls": "xlrd",
    "pdf": "weasyprint",
}
DEV_ONLY = frozenset(
    {
        "pytest",
        "black",
        "flake8",
        "mypy",
        "build",
        "wheel",
        "setuptools",
        "pypdf",
        "playwright",
    }
)
COMMERCIAL_BUILD_ONLY = frozenset({"pyinstaller", "pip-audit"})


def requirement_name(spec: str) -> str:
    text = spec.strip()
    if text.startswith("-"):
        return ""
    match = _REQ_NAME.match(text)
    if not match:
        return ""
    return match.group(1).replace("_", "-").lower()


def normalize_names(specs: Iterable[str]) -> set[str]:
    return {requirement_name(spec) for spec in specs if requirement_name(spec)}


def source_root(start: Path | None = None) -> Path:
    here = start or Path(__file__).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").is_file() and (candidate / "setup.py").is_file():
            return candidate
    raise FileNotFoundError("Could not locate repository root with pyproject.toml")


def load_pyproject(root: Path | None = None) -> dict:
    path = (root or source_root()) / "pyproject.toml"
    with path.open("rb") as handle:
        return tomllib.load(handle)


def runtime_dependency_specs(root: Path | None = None) -> list[str]:
    project = load_pyproject(root)["project"]
    return list(project.get("dependencies") or [])


def dev_dependency_specs(root: Path | None = None) -> list[str]:
    extras = load_pyproject(root)["project"].get("optional-dependencies") or {}
    return list(extras.get("dev") or [])


def redis_extra_specs(root: Path | None = None) -> list[str]:
    extras = load_pyproject(root)["project"].get("optional-dependencies") or {}
    return list(extras.get("redis") or [])


def commercial_build_specs(root: Path | None = None) -> list[str]:
    """Release-only tools; never include these in the buyer runtime."""
    extras = load_pyproject(root)["project"].get("optional-dependencies") or {}
    return list(extras.get("commercial-build") or [])


def packaged_packages(root: Path | None = None) -> list[str]:
    tool = load_pyproject(root).get("tool") or {}
    setuptools = tool.get("setuptools") or {}
    return list(setuptools.get("packages") or [])
