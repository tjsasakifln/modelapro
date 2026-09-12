"""C04 release tooling tests: no Windows toolchain is needed here."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from argparse import Namespace
from pathlib import Path

import pytest

from scripts.c15_local.packaging_meta import commercial_build_specs, requirement_name
from scripts.comercial.operacao import (
    audit,
    build_windows,
    prepare_test_entitlement,
    prepare_windows_native,
    sbom,
    verify_installed_ui,
    verify_windows_install,
)
from scripts.comercial.operacao.operational_harness import run_harness


def _native_fixture(tmp_path: Path, monkeypatch) -> Path:
    native = tmp_path / "windows-native"
    (native / "dlls").mkdir(parents=True)
    (native / "licenses").mkdir()
    (native / "fontconfig").mkdir()
    dll = native / "dlls" / "synthetic.dll"
    config = native / "fontconfig" / "fonts.conf"
    dll.write_bytes(b"synthetic-dll")
    config.write_bytes(b"synthetic-fontconfig")

    def evidence(path: Path) -> dict:
        payload = path.read_bytes()
        return {"size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}

    manifest = {
        "schema_version": "MP-COM-WINDOWS-NATIVE/1",
        "platform": "windows-x64-ucrt",
        "dlls": [{"name": dll.name, **evidence(dll)}],
        "fontconfig": {"path": "fontconfig/fonts.conf", **evidence(config)},
        "packages": [],
        "review_queue": [{"name": "synthetic", "reason": "test_fixture"}],
    }
    (native / "native-runtime.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("MODELA_WINDOWS_NATIVE_DIR", str(native))
    return native


def test_commercial_build_tools_are_release_only() -> None:
    names = {requirement_name(item) for item in commercial_build_specs()}
    assert names == {"pyinstaller", "pip-audit"}
    specs = set(commercial_build_specs())
    assert "pyinstaller==6.22.2" in specs
    assert "pip-audit==2.10.1" in specs
    root = Path(__file__).resolve().parents[3]
    lock = (root / "constraints" / "commercial-build.txt").read_text(encoding="utf-8")
    assert "pyinstaller==6.22.2" in lock
    assert "pip_audit==2.10.1" in lock


def test_sbom_is_sorted_and_uses_noassertion_for_absent_license(monkeypatch) -> None:
    monkeypatch.setattr(
        sbom,
        "_pip_report",
        lambda _python: [
            {"name": "zeta", "version": "1"},
            {"name": "Alpha", "version": "2"},
        ],
    )
    monkeypatch.setattr(
        sbom,
        "_metadata",
        lambda _python, name: {
            "license": "" if name == "zeta" else "MIT",
            "license_expression": "",
            "home_page": "",
            "summary": "",
            "project_urls": [],
            "license_files": [],
            "native_files": [],
            "font_files": [],
        },
    )
    first = sbom.build_sbom("python-test", generated_at="2026-09-12T00:00:00Z")
    second = sbom.build_sbom("python-test", generated_at="2026-09-12T00:00:00Z")
    assert [item["name"] for item in first["components"]] == ["Alpha", "zeta"]
    assert first["components"][1]["licenses"][0]["license"]["name"] == "NOASSERTION"
    assert first["review_queue"] == [
        {"name": "zeta", "version": "1", "reason": "license_metadata_missing"}
    ]
    assert first["metadata"]["component_hash_sha256"] == second["metadata"]["component_hash_sha256"]


def test_sbom_preserves_hashed_license_and_native_binary_evidence(monkeypatch) -> None:
    monkeypatch.setattr(sbom, "_pip_report", lambda _python: [{"name": "binary-lib", "version": "4.2"}])
    monkeypatch.setattr(
        sbom,
        "_metadata",
        lambda _python, _name: {
            "license": "BSD-3-Clause",
            "license_expression": "BSD-3-Clause",
            "home_page": "https://example.invalid/binary-lib",
            "project_urls": ["Source, https://example.invalid/binary-lib/source"],
            "summary": "fixture",
            "license_files": [{"path": "dist-info/LICENSE", "sha256": "a" * 64, "size": 123}],
            "native_files": [{"path": "binary_lib/core.pyd", "sha256": "b" * 64, "size": 456}],
            "font_files": [{"path": "binary_lib/ui.ttf", "sha256": "c" * 64, "size": 789}],
        },
    )
    component = sbom.build_sbom("python-test", generated_at="2026-09-12T00:00:00Z")["components"][0]
    assert component["version"] == "4.2"
    assert component["evidence"]["license_files"][0]["sha256"] == "a" * 64
    assert component["evidence"]["native_files"][0]["sha256"] == "b" * 64
    assert component["evidence"]["font_files"][0]["sha256"] == "c" * 64


def test_sbom_accepts_only_versioned_license_review_with_matching_file_hash(
    tmp_path: Path, monkeypatch
) -> None:
    registry = tmp_path / "reviews.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": "MP-COM-PYTHON-LICENSE-REVIEWS/1",
                "reviews": [
                    {
                        "name": "reviewed-lib",
                        "version": "1.2.3",
                        "license_expression": "BSD-3-Clause",
                        "license_file_sha256": ["a" * 64],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sbom, "_pip_report", lambda _python: [{"name": "reviewed-lib", "version": "1.2.3"}]
    )
    metadata = {
        "license": "",
        "license_expression": "",
        "home_page": "",
        "summary": "",
        "project_urls": [],
        "license_files": [{"path": "LICENSE", "sha256": "a" * 64, "size": 1}],
        "native_files": [],
        "font_files": [],
    }
    monkeypatch.setattr(sbom, "_metadata", lambda _python, _name: metadata)

    matched = sbom.build_sbom(
        "python-test", generated_at="2026-09-12T00:00:00Z", license_reviews=registry
    )
    assert matched["components"][0]["licenses"] == [
        {"license": {"name": "BSD-3-Clause"}}
    ]
    assert matched["components"][0]["evidence"]["license_source"] == (
        "version-and-license-file-review"
    )
    assert matched["review_queue"] == []

    metadata["license_files"][0]["sha256"] = "b" * 64
    mismatched = sbom.build_sbom(
        "python-test", generated_at="2026-09-12T00:00:00Z", license_reviews=registry
    )
    assert mismatched["components"][0]["licenses"] == [
        {"license": {"name": "NOASSERTION"}}
    ]
    assert mismatched["review_queue"][0]["reason"] == "license_review_evidence_mismatch"


def test_release_sbom_keeps_build_environment_and_labels_runtime_closure(monkeypatch) -> None:
    monkeypatch.setattr(
        sbom,
        "_pip_report",
        lambda _python: [
            {"name": "modelapro", "version": "0.1.0"},
            {"name": "runtime-lib", "version": "2.0"},
            {"name": "pyinstaller", "version": "6.22.2"},
        ],
    )
    monkeypatch.setattr(
        sbom,
        "_runtime_dependency_graph",
        lambda _python, _root: {
            "modelapro": ["runtime-lib"],
            "runtime-lib": [],
        },
    )
    monkeypatch.setattr(
        sbom,
        "_metadata",
        lambda _python, _name: {
            "license": "MIT",
            "license_expression": "MIT",
            "home_page": "",
            "summary": "",
            "project_urls": [],
            "license_files": [],
            "native_files": [],
            "font_files": [],
        },
    )
    payload = sbom.build_sbom(
        "python-test",
        generated_at="2026-09-12T00:00:00Z",
        root_distribution="modelapro",
    )
    # The build environment is a conservative superset of what PyInstaller can
    # collect.  Runtime reachability is recorded separately instead of deleting
    # build-environment components before bundle provenance is available.
    assert [item["name"] for item in payload["components"]] == [
        "modelapro",
        "pyinstaller",
        "runtime-lib",
    ]
    assert payload["metadata"]["inventory_scope"] == "installed-build-environment"
    assert payload["metadata"]["root_distribution"] == "modelapro"
    assert payload["metadata"]["declared_runtime_dependency_closure"] == [
        "modelapro",
        "runtime-lib",
    ]
    assert payload["components"][0]["evidence"]["runtime_dependencies"] == [
        "runtime-lib"
    ]
    assert payload["components"][1]["evidence"]["declared_runtime_dependency"] is False


def test_runtime_dependency_graph_propagates_transitive_requested_extras(
    tmp_path: Path, monkeypatch
) -> None:
    def dist(name: str, version: str, requirements: list[str]) -> None:
        metadata = tmp_path / f"{name.replace('-', '_')}-{version}.dist-info" / "METADATA"
        metadata.parent.mkdir()
        lines = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}"]
        lines.extend(f"Requires-Dist: {requirement}" for requirement in requirements)
        metadata.write_text("\n".join(lines) + "\n", encoding="utf-8")

    dist(
        "root-dist",
        "1",
        ["child[feature]", 'root-feature-leaf; extra == "root-feature"'],
    )
    dist(
        "child",
        "1",
        [
            "base",
            'base-marker-leaf; extra != "feature"',
            'feature-leaf; extra == "feature"',
            'unused-leaf; extra == "unused"',
        ],
    )
    dist("base", "1", [])
    dist("base-marker-leaf", "1", [])
    dist("feature-leaf", "1", [])
    dist("root-feature-leaf", "1", [])
    dist("unused-leaf", "1", [])
    previous = __import__("os").environ.get("PYTHONPATH", "")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path) + ((":" + previous) if previous else ""))

    graph = sbom._runtime_dependency_graph(sys.executable, "root-dist[root-feature]")

    assert graph == {
        "base": [],
        "base-marker-leaf": [],
        "child": ["base", "base-marker-leaf", "feature-leaf"],
        "feature-leaf": [],
        "root-dist": ["child", "root-feature-leaf"],
        "root-feature-leaf": [],
    }


def test_sbom_cli_requires_fixed_timestamp(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        sbom.main(["--output", str(tmp_path / "sbom.json")])
    assert exc.value.code == 2


def test_release_environment_must_exactly_match_lock(tmp_path: Path, monkeypatch) -> None:
    lock = tmp_path / "windows.lock"
    lock.write_text("Alpha==1\nzeta_pkg==2\n", encoding="utf-8")
    monkeypatch.setattr(
        sbom,
        "_pip_report",
        lambda _python: [
            {"name": "alpha", "version": "1"},
            {"name": "zeta-pkg", "version": "2"},
            {"name": "modelapro", "version": "0.1.0"},
        ],
    )
    assert sbom.assert_environment_matches_lock("python-test", lock)["matches"] is True
    lock.write_text("Alpha==1\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unexpected.*zeta-pkg"):
        sbom.assert_environment_matches_lock("python-test", lock)
    lock.write_text("Alpha==9\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not match"):
        sbom.assert_environment_matches_lock("python-test", lock)


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


def test_native_windows_staging_refuses_non_windows_host(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(prepare_windows_native.platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="only be staged on Windows"):
        prepare_windows_native.prepare(tmp_path / "msys64", tmp_path / "native")


def test_native_runtime_regeneration_compares_every_byte(tmp_path: Path) -> None:
    reference = tmp_path / "reference"
    regenerated = tmp_path / "regenerated"
    for root in (reference, regenerated):
        (root / "dlls").mkdir(parents=True)
        (root / "licenses" / "pkg").mkdir(parents=True)
        (root / "dlls" / "runtime.dll").write_bytes(b"runtime")
        (root / "licenses" / "pkg" / "LICENSE").write_bytes(b"terms")
    evidence = tmp_path / "comparison.json"
    prepare_windows_native.compare_regeneration(reference, regenerated, evidence)
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["status"] == "PASSED"
    assert payload["reference_file_count"] == 2
    assert payload["reference_inventory_sha256"] == payload["regenerated_inventory_sha256"]

    (regenerated / "dlls" / "runtime.dll").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="differs from reference"):
        prepare_windows_native.compare_regeneration(reference, regenerated, evidence)
    failed = json.loads(evidence.read_text(encoding="utf-8"))
    assert failed["status"] == "FAILED"
    assert failed["changed"][0]["path"] == "dlls/runtime.dll"


def test_windows_workflow_publishes_native_regeneration_evidence() -> None:
    root = Path(__file__).resolve().parents[3]
    workflow = (root / ".github" / "workflows" / "c06-windows.yml").read_text(
        encoding="utf-8"
    )
    assert "--compare-to $native" in workflow
    assert "--comparison-evidence $comparison" in workflow
    assert "windows-native-regeneration.json" in workflow


def test_test_entitlement_generator_never_persists_private_key(tmp_path: Path) -> None:
    manifest_path = prepare_test_entitlement.prepare(tmp_path / "test-entitlement")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = {path.name for path in manifest_path.parent.iterdir()}
    assert manifest["test_only"] is True
    assert manifest["private_key_persisted"] is False
    assert files == {
        "synthetic-test-entitlement.json",
        "test-entitlement-manifest.json",
        "trusted_vendor_anchor.json",
    }


def test_windows_build_refuses_tampered_native_runtime(tmp_path: Path, monkeypatch) -> None:
    root = Path(__file__).resolve().parents[3]
    monkeypatch.setattr(build_windows.platform, "system", lambda: "Windows")
    monkeypatch.setattr(build_windows.platform, "machine", lambda: "AMD64")
    native = _native_fixture(tmp_path, monkeypatch)
    (native / "dlls" / "synthetic.dll").write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="does not match its manifest"):
        build_windows.build(root, tmp_path / "dist", "1.0")


def test_windows_build_manifest_stays_unsigned_and_carries_supply_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    root = Path(__file__).resolve().parents[3]
    output = tmp_path / "dist"
    monkeypatch.setattr(build_windows.platform, "system", lambda: "Windows")
    monkeypatch.setattr(build_windows.platform, "machine", lambda: "AMD64")
    _native_fixture(tmp_path, monkeypatch)

    def fake_audit(_python, path):
        path.write_text('{"dependencies":[]}', encoding="utf-8")
        return 0

    monkeypatch.setattr(build_windows.audit, "audit", fake_audit)
    monkeypatch.setattr(
        build_windows.sbom,
        "build_sbom",
        lambda *_args, **_kwargs: {"bomFormat": "MODELA-PRO-SBOM", "components": []},
    )
    monkeypatch.setattr(
        build_windows.sbom,
        "assert_environment_matches_lock",
        lambda *_args, **_kwargs: {"matches": True},
    )

    class Result:
        returncode = 0
        stdout = ""

    def fake_run(command, **_kwargs):
        if "PyInstaller" in command:
            bundle = output / "MODELA-PRO"
            bundle.mkdir(parents=True)
            (bundle / "MODELA-PRO.exe").write_bytes(b"synthetic-exe")
        elif str(command[0]).lower().endswith("iscc.exe"):
            (output / "MODELA-PRO-1.0-win64.exe").write_bytes(b"synthetic-installer")
        result = Result()
        if "rev-parse" in command:
            result.stdout = "deadbeef\n"
        return result

    monkeypatch.setattr(build_windows.subprocess, "run", fake_run)
    manifest_path = build_windows.build(
        root,
        output,
        "1.0",
        generated_at="2026-09-12T00:00:00Z",
        lock=root / "constraints" / "commercial-build.txt",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_sha"] == "deadbeef"
    assert manifest["signing_status"] == "UNSIGNED"
    assert manifest["signing_requirement"] == "OPTIONAL_UNLESS_APPROVED_OFFER_REQUIRES_CODE_SIGNING"
    assert manifest["commercial_release_ready"] is False
    assert not any("signature" in reason.lower() for reason in manifest["blocking_reasons"])
    assert (output / "MODELA-PRO" / "SBOM.modelapro.json").is_file()
    assert (output / "MODELA-PRO" / "pip-audit.json").is_file()
    assert (output / "qualification-evidence" / "native-runtime.json").is_file()
    bundle_inventory = json.loads(
        (output / "qualification-evidence" / "bundle-file-inventory.json").read_text(
            encoding="utf-8"
        )
    )
    assert bundle_inventory["scope"] == (
        "complete-pyinstaller-onedir-consumed-by-inno-setup"
    )
    assert {item["path"] for item in bundle_inventory["files"]} == {
        "MODELA-PRO.exe",
        "SBOM.modelapro.json",
        "pip-audit.json",
    }


def test_windows_bundle_requires_native_runtime_and_hardens_distribution_evidence() -> None:
    root = Path(__file__).resolve().parents[3]
    spec = (root / "packaging" / "comercial" / "modelapro.spec").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "c06-windows.yml").read_text(encoding="utf-8")
    assert "MODELA_WINDOWS_NATIVE_DIR" in spec
    assert "windows_runtime.py" in spec
    assert "native_binaries" in spec
    assert "modelapro-build-venv" in workflow
    assert "previous candidate is not a distinct source tree" in workflow
    assert "windows_distribution_verified = ($phasesPassed -and $distinctTrees)" in workflow
    assert "installed A cannot render PDF" in workflow
    assert '"playwright==1.62.0"' in workflow
    assert "--browser-python $env:C06_BROWSER_PYTHON" in workflow
    assert "Start-Process -FilePath $env:C06_PRIOR_INSTALLER" in workflow
    assert "initial-installed-preflight.json" in workflow


def test_windows_verifier_preserves_evidence_when_installed_executable_is_absent(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        verify_windows_install,
        "_provision_ephemeral_test_controls",
        lambda _path: None,
    )
    evidence = tmp_path / "evidence"
    args = Namespace(
        executable=tmp_path / "missing" / "MODELA-PRO.exe",
        evidence=evidence,
        backup=evidence / "backup.zip",
        browser_python=tmp_path / "browser-python.exe",
        phase="initial",
    )
    with pytest.raises(
        verify_windows_install.VerificationError,
        match="installed executable is absent",
    ):
        verify_windows_install.verify(args)
    result = json.loads((evidence / "initial.json").read_text(encoding="utf-8"))
    assert result["status"] == "FAILED"
    assert result["error"]["type"] == "VerificationError"
    assert "installed executable is absent" in result["error"]["detail"]


def test_installed_ui_probe_uses_six_profiles_and_labels_only_synthetic_data() -> None:
    csv_bytes = verify_installed_ui._synthetic_csv()
    assert csv_bytes.startswith(b"id;bairro;area;preco\nUI-TESTE-")
    assert len(csv_bytes.splitlines()) == 37
    assert len(verify_installed_ui.EXPECTED_PROFILE_LABELS) == 6
    assert verify_installed_ui.TEST_BUILD_LABEL == "BUILD SINTÉTICO DE TESTE — NÃO COMERCIAL"


def test_windows_update_semantic_comparison_ignores_only_execution_identity(tmp_path: Path) -> None:
    first = {
        "job_id": "job-a",
        "generated_at": "2026-09-12T00:00:00Z",
        "code_sha": "a" * 40,
        "value": {"point": 123.0, "mean_ci80": [120.0, 126.0]},
        "policy": {"mode": "exact"},
    }
    second = {**first, "job_id": "job-b", "generated_at": "later", "code_sha": "b" * 40}
    first_hash = verify_windows_install._semantic_result_evidence(first, tmp_path / "first.json")
    second_hash = verify_windows_install._semantic_result_evidence(second, tmp_path / "second.json")
    assert first_hash == second_hash
    second["value"] = {"point": 123.0, "mean_ci80": [119.0, 127.0]}
    changed_hash = verify_windows_install._semantic_result_evidence(second, tmp_path / "changed.json")
    assert changed_hash != first_hash


def test_windows_build_preserves_failed_stage_evidence(tmp_path: Path, monkeypatch) -> None:
    root = Path(__file__).resolve().parents[3]
    output = tmp_path / "failed-dist"
    monkeypatch.setattr(build_windows.platform, "system", lambda: "Windows")
    monkeypatch.setattr(build_windows.platform, "machine", lambda: "AMD64")
    _native_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(build_windows, "_source_identity", lambda _root: "source-sha")
    monkeypatch.setattr(build_windows, "_git_identity", lambda _root, _ref: "tree-sha")
    monkeypatch.setattr(
        build_windows.sbom,
        "assert_environment_matches_lock",
        lambda *_args, **_kwargs: {"matches": True},
    )

    def failed_audit(_python, path):
        path.write_text('{"dependencies": [{"name": "synthetic-blocker"}]}', encoding="utf-8")
        return 7

    monkeypatch.setattr(build_windows.audit, "audit", failed_audit)
    with pytest.raises(RuntimeError, match="pip-audit blocked"):
        build_windows.build(
            root,
            output,
            "1.0",
            generated_at="2026-09-12T00:00:00Z",
            lock=root / "constraints" / "commercial-build.txt",
        )
    status = json.loads(
        (output / "qualification-evidence" / "build-status.json").read_text(encoding="utf-8")
    )
    assert status["status"] == "FAILED"
    assert status["stages"]["environment_lock"]["status"] == "PASSED"
    assert status["stages"]["vulnerability_audit"]["status"] == "FAILED"
    assert (output / "qualification-evidence" / "pip-audit.json").is_file()


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


def test_operational_harness_exercises_integrity_and_resource_refusal() -> None:
    root = Path(__file__).resolve().parents[3]
    evidence = run_harness(
        root / "docs" / "comercial" / "c04" / "performance_budget.json",
        exercise=True,
    )
    for name in ("queue_cancel", "backup_restore", "disk_refusal"):
        assert evidence["checks"][name]["status"] == "PASSED"
    assert evidence["checks"]["backup_restore"]["evidence_parity"] is True
    assert evidence["checks"]["technical_corpus"]["status"] == "NOT_RUN"


def test_wheel_contains_runtime_components_but_not_release_tooling(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    subprocess.run(
        [
            sys.executable, "-m", "pip", "wheel", "--no-build-isolation",
            "--no-deps", "--wheel-dir", str(tmp_path), str(root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(tmp_path.glob("modelapro-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    assert any(name.startswith("modules/operacao_local/") for name in names)
    assert any(name.startswith("modules/commercial_license/") for name in names)
    assert any(name.startswith("modules/cost_valuation/") for name in names)
    assert any(name.startswith("modules/pro_workflow/") for name in names)
    assert any(name.startswith("modules/valuation_policy/") for name in names)
    assert "modules/commercial_license/trusted_vendor_anchor.json" in names
    assert any(name.startswith("profiles/normative/") and name.endswith(".json") for name in names)
    assert any(name.startswith("profiles/institutions/") and name.endswith(".json") for name in names)
    assert not any(name.startswith("scripts/comercial/") for name in names)
    assert not any(name.startswith("packaging/comercial/") for name in names)
    assert not any(name.startswith("tests/") or name.lower().endswith((".pdf", ".ttf", ".otf")) for name in names)


def test_windows_spec_materializes_streamlit_sources_and_uses_onedir() -> None:
    root = Path(__file__).resolve().parents[3]
    spec = (root / "packaging" / "comercial" / "modelapro.spec").read_text(encoding="utf-8")
    assert 'rglob("*.py")' in spec
    assert 'collect_data_files("profiles")' in spec
    assert 'collect_submodules("pyhanko")' in spec
    assert 'collect_submodules("pyhanko_certvalidator")' in spec
    assert '[str(root / "scripts" / "c15_local" / "launcher.py")]' in spec
    assert 'Analysis(\n    ["scripts/c15_local/launcher.py"]' not in spec
    assert 'pathex=[str(root)]' in spec
    assert "exclude_binaries=True" in spec
    assert "COLLECT(" in spec
    assert 'copy_metadata("streamlit", recursive=True)' in spec
    assert 'copy_metadata("modelapro")' in spec
    for buyer_document in (
        "SECURITY.md", "operations_manual.md", "privacy.md",
        "support_and_maintenance.md", "THIRD_PARTY_NOTICES.md",
    ):
        assert buyer_document in spec


def test_windows_uninstall_preserves_whichever_profile_was_created() -> None:
    root = Path(__file__).resolve().parents[3]
    workflow = (root / ".github" / "workflows" / "c06-windows.yml").read_text(
        encoding="utf-8"
    )
    uninstall = workflow.split(
        "- name: Uninstall without deleting the separate evidence profile", 1
    )[1].split("- name: Record artifact hashes and scope limits", 1)[0]
    assert 'Join-Path $env:RUNNER_TEMP "profile-active"' in uninstall
    assert 'Join-Path $env:RUNNER_TEMP "profile-restored"' in uninstall
    assert "Test-Path -LiteralPath $preservedProfile -PathType Container" in uninstall
