"""C04 release tooling tests: no Windows toolchain is needed here."""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.c15_local.packaging_meta import commercial_build_specs, requirement_name
from scripts.comercial.operacao import audit, build_windows, sbom
from scripts.comercial.operacao.operational_harness import run_harness


def test_commercial_build_tools_are_release_only() -> None:
    names = {requirement_name(item) for item in commercial_build_specs()}
    assert names == {"pyinstaller", "pip-audit"}


def test_sbom_is_sorted_and_uses_noassertion_for_absent_license(monkeypatch) -> None:
    monkeypatch.setattr(sbom, "_pip_report", lambda _python: [{"name": "zeta", "version": "1"}, {"name": "Alpha", "version": "2"}])
    monkeypatch.setattr(
        sbom,
        "_metadata",
        lambda _python, name: {"license": "" if name == "zeta" else "MIT", "license_expression": "", "home_page": "", "summary": ""},
    )
    first = sbom.build_sbom("python-test", generated_at="2026-09-12T00:00:00Z")
    second = sbom.build_sbom("python-test", generated_at="2026-09-12T00:00:00Z")
    assert [item["name"] for item in first["components"]] == ["Alpha", "zeta"]
    assert first["components"][1]["licenses"][0]["license"]["name"] == "NOASSERTION"
    assert first["metadata"]["component_hash_sha256"] == second["metadata"]["component_hash_sha256"]


def test_sbom_cli_requires_fixed_timestamp(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        sbom.main(["--output", str(tmp_path / "sbom.json")])
    assert exc.value.code == 2


def test_audit_preserves_nonzero_exit_as_release_blocker(monkeypatch, tmp_path: Path) -> None:
    class Result:
        returncode = 7

    monkeypatch.setattr(audit.subprocess, "run", lambda *args, **kwargs: Result())
    assert audit.audit("python-test", tmp_path / "audit.json") == 7


def test_windows_build_refuses_non_windows_host(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(build_windows.platform, "system", lambda: "Linux")
    monkeypatch.setattr(build_windows.platform, "machine", lambda: "x86_64")
    with pytest.raises(RuntimeError, match="Windows x64"):
        build_windows.build(tmp_path, tmp_path / "dist", "1.0")


def test_reuse_manifest_is_explicit_about_unresolved_rights() -> None:
    root = Path(__file__).resolve().parents[3]
    payload = json.loads((root / "third_party" / "reuse_manifest.json").read_text(encoding="utf-8"))
    assert payload["status"] == "IMPLEMENTED_PARTIAL"
    assert payload["blocked"]


def test_operational_harness_marks_unexecuted_checks_not_run() -> None:
    root = Path(__file__).resolve().parents[3]
    evidence = run_harness(root / "docs" / "comercial" / "c04" / "performance_budget.json")
    assert {result["status"] for result in evidence["checks"].values()} == {"NOT_RUN"}
    assert evidence["resource"]["exit_code"] == 0


def test_wheel_contains_runtime_components_but_not_release_tooling(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-build-isolation", "--no-deps", "--wheel-dir", str(tmp_path), str(root)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(tmp_path.glob("modelapro-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    assert any(name.startswith("modules/operacao_local/") for name in names)
    assert any(name.startswith("modules/commercial_license/") for name in names)
    assert not any(name.startswith("scripts/comercial/") for name in names)
    assert not any(name.startswith("packaging/comercial/") for name in names)
    assert not any(name.startswith("tests/") or name.lower().endswith((".pdf", ".ttf", ".otf")) for name in names)
