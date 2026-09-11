"""Canonical dependency list must not diverge across pyproject / setup / requirements."""

from __future__ import annotations

import ast
from pathlib import Path

from c15_local.packaging_meta import (
    ANNOUNCED_FORMAT_ENGINES,
    DEV_ONLY,
    REQUIRED_RUNTIME_IMPORTS,
    load_pyproject,
    normalize_names,
    redis_extra_specs,
    requirement_name,
    runtime_dependency_specs,
    source_root,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_setup_py_is_shim_without_install_requires():
    source = (REPO_ROOT / "setup.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "setup"
    ]
    assert calls, "setup() must still be invoked for compatibility"
    for call in calls:
        keys = {kw.arg for kw in call.keywords}
        assert "install_requires" not in keys
        assert "extras_require" not in keys
        assert "entry_points" not in keys


def test_requirements_files_do_not_duplicate_package_lists():
    runtime = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    dev = (REPO_ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
    runtime_pkgs = [
        line
        for line in runtime
        if line.strip() and not line.strip().startswith("#") and not line.strip().startswith("-")
    ]
    dev_pkgs = [
        line
        for line in dev
        if line.strip() and not line.strip().startswith("#") and not line.strip().startswith("-")
    ]
    assert runtime_pkgs == ["."]
    assert dev_pkgs == [".[dev]"]
    assert any(line.startswith("-c constraints/") for line in runtime)
    assert any(line.startswith("-c constraints/") for line in dev)


def test_pyproject_declares_every_direct_runtime_import():
    names = normalize_names(runtime_dependency_specs(REPO_ROOT))
    missing = REQUIRED_RUNTIME_IMPORTS - names
    assert not missing, f"direct runtime imports missing from pyproject: {sorted(missing)}"
    leaked_dev = names & DEV_ONLY
    assert not leaked_dev, f"dev tools must not be runtime deps: {sorted(leaked_dev)}"


def test_announced_format_engines_are_direct_deps():
    names = normalize_names(runtime_dependency_specs(REPO_ROOT))
    for fmt, engine in ANNOUNCED_FORMAT_ENGINES.items():
        assert engine in names, f"{fmt} engine {engine} must be a direct dependency"


def test_pytest_is_dev_extra_not_runtime():
    runtime = normalize_names(runtime_dependency_specs(REPO_ROOT))
    extras = load_pyproject(REPO_ROOT)["project"]["optional-dependencies"]
    dev = normalize_names(extras["dev"])
    assert "pytest" not in runtime
    assert "pytest" in dev
    assert "httpx" in dev


def test_redis_is_optional_extra():
    runtime = normalize_names(runtime_dependency_specs(REPO_ROOT))
    assert "redis" not in runtime
    assert "redis" in normalize_names(redis_extra_specs(REPO_ROOT))


def test_constraints_pin_every_direct_runtime_dep():
    lock = REPO_ROOT / "constraints" / "linux-py3.txt"
    assert lock.is_file(), "constraints/linux-py3.txt must be generated (python -m c15_local.update_constraints)"
    pinned = {
        requirement_name(line)
        for line in lock.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    missing = REQUIRED_RUNTIME_IMPORTS - pinned
    assert not missing, f"lock file missing direct deps {sorted(missing)}"


def test_source_root_helper_matches_checkout():
    assert source_root(Path(__file__)) == REPO_ROOT
