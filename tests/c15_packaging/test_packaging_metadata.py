"""Wheel metadata includes packages, templates, CSS, and the Streamlit launcher."""

from __future__ import annotations

import zipfile
from pathlib import Path

from c15_local.packaging_meta import load_pyproject, packaged_packages

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_pyproject_packages_and_package_data():
    packages = packaged_packages(REPO_ROOT)
    for name in ("backend", "modules", "frontend", "frontend.components", "c15_local"):
        assert name in packages
    data = load_pyproject(REPO_ROOT)["tool"]["setuptools"]["package-data"]
    assert "templates/*.html" in data["modules"]
    assert "assets/*.css" in data["frontend"]
    scripts = load_pyproject(REPO_ROOT)["project"]["scripts"]
    assert scripts["modelapro"] == "c15_local.launcher:main"
    assert "frontend.app:main" not in scripts.values()


def test_init_markers_exist():
    for rel in (
        "backend/__init__.py",
        "modules/__init__.py",
        "frontend/__init__.py",
        "frontend/components/__init__.py",
        "scripts/c15_local/__init__.py",
    ):
        assert (REPO_ROOT / rel).is_file()


def test_source_resources_exist_and_nonempty():
    template = REPO_ROOT / "modules" / "templates" / "report.html"
    css = REPO_ROOT / "frontend" / "assets" / "styles.css"
    assert template.is_file() and template.stat().st_size > 0
    assert css.is_file() and css.stat().st_size > 0


def test_wheel_contains_packages_templates_css_and_entrypoint(tmp_path: Path):
    import subprocess
    import sys

    dist = tmp_path / "dist"
    dist.mkdir()
    built = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(dist)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    wheels = list(dist.glob("modelapro-*.whl"))
    assert wheels, built.stdout
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
        for required in (
            "backend/__init__.py",
            "backend/api.py",
            "modules/__init__.py",
            "modules/templates/report.html",
            "frontend/__init__.py",
            "frontend/app.py",
            "frontend/assets/styles.css",
            "frontend/components/__init__.py",
            "c15_local/launcher.py",
        ):
            assert required in names, required
        assert archive.read("modules/templates/report.html")
        assert archive.read("frontend/assets/styles.css")
        dist_info = [name for name in names if name.endswith("entry_points.txt")]
        assert dist_info
        entry = archive.read(dist_info[0]).decode("utf-8")
        assert "c15_local.launcher:main" in entry
        assert "frontend.app:main" not in entry


def test_sdist_contains_templates_and_css(tmp_path: Path):
    import subprocess
    import sys
    import tarfile

    dist = tmp_path / "dist"
    dist.mkdir()
    built = subprocess.run(
        [sys.executable, "-m", "build", "--sdist", "--outdir", str(dist)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if built.returncode != 0 and "No module named build" in (built.stderr + built.stdout):
        import pytest

        pytest.skip("python -m build is a dev extra")
    assert built.returncode == 0, built.stderr
    sdists = list(dist.glob("modelapro-*.tar.gz"))
    assert sdists
    with tarfile.open(sdists[0], "r:gz") as archive:
        names = archive.getnames()
    joined = "\n".join(names)
    assert "modules/templates/report.html" in joined
    assert "frontend/assets/styles.css" in joined
    assert "scripts/c15_local/launcher.py" in joined
