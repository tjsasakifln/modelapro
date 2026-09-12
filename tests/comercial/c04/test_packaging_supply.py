"""C04 release tooling tests: no Windows toolchain is needed here."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

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


TEST_SOURCE_SHA = "a" * 40
TEST_TREE_SHA = "b" * 40
TEST_RESULT_FINGERPRINT = "c" * 64
TEST_REPORT_FINGERPRINT = "d" * 64


def _write_test_bundle_inventory(installed: Path, inventory: Path) -> dict:
    identity = {
        "schema_version": "MP-COM-BUILD-IDENTITY/1",
        "source_sha": TEST_SOURCE_SHA,
        "tree_sha": TEST_TREE_SHA,
    }
    (installed / build_windows.BUILD_IDENTITY_FILENAME).write_text(
        json.dumps(identity), encoding="utf-8"
    )
    return build_windows._write_bundle_inventory(
        installed,
        inventory,
        source_sha=TEST_SOURCE_SHA,
        tree_sha=TEST_TREE_SHA,
    )


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
            identity = Path(_kwargs["env"]["MODELA_BUILD_SOURCE_IDENTITY_FILE"])
            (bundle / build_windows.BUILD_IDENTITY_FILENAME).write_bytes(
                identity.read_bytes()
            )
        elif str(command[0]).lower().endswith("iscc.exe"):
            (output / "MODELA-PRO-1.0-win64.exe").write_bytes(b"synthetic-installer")
        result = Result()
        if "rev-parse" in command:
            result.stdout = TEST_SOURCE_SHA + "\n"
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
    assert manifest["source_sha"] == TEST_SOURCE_SHA
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
        build_windows.BUILD_IDENTITY_FILENAME,
        "pip-audit.json",
    }
    assert bundle_inventory["source_sha"] == TEST_SOURCE_SHA
    assert bundle_inventory["tree_sha"] == TEST_SOURCE_SHA


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
    assert workflow.count("--bundle-inventory") == 3
    assert "C06_PRIOR_BUNDLE_INVENTORY" in workflow
    assert "qualification-evidence/bundle-file-inventory.json" in workflow
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
        bundle_inventory=tmp_path / "bundle-file-inventory.json",
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


def test_installed_bundle_verifier_matches_bytes_and_allows_only_inno_files(
    tmp_path: Path,
) -> None:
    installed = tmp_path / "installed"
    (installed / "nested").mkdir(parents=True)
    (installed / "MODELA-PRO.exe").write_bytes(b"exe")
    (installed / "nested" / "runtime.dll").write_bytes(b"dll")
    inventory = tmp_path / "bundle-file-inventory.json"
    _write_test_bundle_inventory(installed, inventory)
    (installed / "unins000.exe").write_bytes(b"inno-exe")
    (installed / "unins000.dat").write_bytes(b"inno-dat")
    evidence = tmp_path / "installed-bundle.json"

    result = verify_windows_install._verify_installed_bundle(
        installed, inventory, evidence
    )

    assert result["status"] == "PASSED"
    assert result["declared_file_count"] == 3
    assert result["source_sha"] == TEST_SOURCE_SHA
    assert result["tree_sha"] == TEST_TREE_SHA
    assert [item["path"] for item in result["allowed_inno_runtime_files"]] == [
        "unins000.dat",
        "unins000.exe",
    ]
    assert all(item["sha256"] for item in result["allowed_inno_runtime_files"])
    assert json.loads(evidence.read_text(encoding="utf-8"))["status"] == "PASSED"


def test_windows_host_identity_records_exact_non_identifying_build(monkeypatch) -> None:
    monkeypatch.setattr(verify_windows_install.os, "name", "nt")
    monkeypatch.setattr(
        verify_windows_install.platform,
        "win32_ver",
        lambda: ("11", "10.0.26200", "", "Multiprocessor Free"),
    )
    monkeypatch.setattr(
        verify_windows_install.platform, "win32_edition", lambda: "Professional"
    )
    monkeypatch.setattr(
        verify_windows_install.sys,
        "getwindowsversion",
        lambda: SimpleNamespace(build=26200, platform_version=(10, 0, 26200)),
        raising=False,
    )

    identity = verify_windows_install._host_identity()

    assert identity["windows_release"] == "11"
    assert identity["windows_edition"] == "Professional"
    assert identity["windows_build"] == 26200
    assert identity["windows_platform_version"] == (10, 0, 26200)


@pytest.mark.parametrize("failure", ["missing", "mismatch", "unexpected"])
def test_installed_bundle_verifier_rejects_tree_differences(
    tmp_path: Path, failure: str
) -> None:
    installed = tmp_path / "installed"
    installed.mkdir()
    target = installed / "MODELA-PRO.exe"
    target.write_bytes(b"expected")
    inventory = tmp_path / "bundle-file-inventory.json"
    _write_test_bundle_inventory(installed, inventory)
    if failure == "missing":
        target.unlink()
    elif failure == "mismatch":
        target.write_bytes(b"modified")
    else:
        (installed / "undeclared.dll").write_bytes(b"unexpected")
    evidence = tmp_path / "installed-bundle.json"

    with pytest.raises(
        verify_windows_install.VerificationError,
        match="installed bundle differs from inventory",
    ):
        verify_windows_install._verify_installed_bundle(installed, inventory, evidence)

    result = json.loads(evidence.read_text(encoding="utf-8"))
    assert result["status"] == "FAILED"
    assert result[failure if failure != "mismatch" else "mismatched"]


@pytest.mark.parametrize(
    "unsafe_path",
    ["../outside", "..\\outside", "C:\\outside", "MODELA-PRO.exe:stream"],
)
def test_installed_bundle_verifier_rejects_windows_path_escape_forms(
    tmp_path: Path, unsafe_path: str
) -> None:
    installed = tmp_path / "installed"
    installed.mkdir()
    (installed / "MODELA-PRO.exe").write_bytes(b"expected")
    inventory = tmp_path / "bundle-file-inventory.json"
    payload = _write_test_bundle_inventory(installed, inventory)
    payload["files"][0]["path"] = unsafe_path
    payload["inventory_sha256"] = hashlib.sha256(
        json.dumps(
            payload["files"], sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    inventory.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(verify_windows_install.VerificationError, match="path is unsafe"):
        verify_windows_install._verify_installed_bundle(
            installed, inventory, tmp_path / "installed-bundle.json"
        )


def test_installed_bundle_verifier_rejects_casefold_collision(tmp_path: Path) -> None:
    installed = tmp_path / "installed"
    installed.mkdir()
    (installed / "FILE.dll").write_bytes(b"upper")
    (installed / "file.dll").write_bytes(b"lower")
    inventory = tmp_path / "bundle-file-inventory.json"
    _write_test_bundle_inventory(installed, inventory)

    with pytest.raises(
        verify_windows_install.VerificationError,
        match="case-insensitively unique",
    ):
        verify_windows_install._verify_installed_bundle(
            installed, inventory, tmp_path / "installed-bundle.json"
        )


def test_installed_bundle_verifier_rejects_symlink_escaping_root(tmp_path: Path) -> None:
    installed = tmp_path / "installed"
    installed.mkdir()
    outside = tmp_path / "outside.dll"
    outside.write_bytes(b"outside")
    (installed / "runtime.dll").symlink_to(outside)
    inventory = tmp_path / "bundle-file-inventory.json"
    _write_test_bundle_inventory(installed, inventory)

    with pytest.raises(verify_windows_install.VerificationError, match="escapes its root"):
        verify_windows_install._verify_installed_bundle(
            installed, inventory, tmp_path / "installed-bundle.json"
        )


def test_windows_job_verifier_explicitly_generates_documents_with_job_token(
    tmp_path: Path, monkeypatch
) -> None:
    document_calls = []
    result_reads = []
    snapshot = {
        "job_id": "job-test",
        "code_sha": TEST_SOURCE_SHA,
        "provenance": {
            "qualification_context": {
                "profile": {"id": verify_windows_install.PROFILE["id"]},
                "result_fingerprint": TEST_RESULT_FINGERPRINT,
            }
        },
        "value": {"point": 123.0},
    }

    def request(url: str, **kwargs) -> bytes:
        if url.endswith("/jobs"):
            return json.dumps(
                {
                    "job_id": "job-test",
                    "access_token": "job-secret",
                    "idempotent_replay": False,
                }
            ).encode()
        name = url.rsplit("/", 1)[-1]
        if name == "frozen_project.json":
            return json.dumps(
                {"provenance": {"code_sha": TEST_SOURCE_SHA}}
            ).encode()
        if name == "report.pdf":
            return b"%PDF-test"
        if name in {"report.docx", "evidence_bundle.zip"}:
            return b"PK-test"
        raise AssertionError((url, kwargs))

    def json_request(url: str, **kwargs) -> dict:
        if url.endswith("/documents"):
            document_calls.append(kwargs)
            artifacts = {
                "report.pdf": b"%PDF-test",
                "report.docx": b"PK-test",
                "evidence_bundle.zip": b"PK-test",
            }
            return {
                "job_id": "job-test",
                "result_fingerprint": TEST_RESULT_FINGERPRINT,
                "report_content_fingerprint": TEST_REPORT_FINGERPRINT,
                "document_state": {
                    "result_fingerprint": TEST_RESULT_FINGERPRINT,
                    "report_content_fingerprint": TEST_REPORT_FINGERPRINT,
                },
                "artifacts": {
                    name: {
                        "size": len(value),
                        "sha256": hashlib.sha256(value).hexdigest(),
                    }
                    for name, value in artifacts.items()
                },
            }
        if url.endswith("/result"):
            result_reads.append(url)
            return snapshot
        if url.endswith("/jobs/job-test"):
            return {"state": "succeeded"}
        if url.endswith("/revisions"):
            return {"revision_id": "revision-test"}
        if url.endswith("/projects/TESTE-C06-PROJETO"):
            return {"revision": {"revision_id": "revision-test"}}
        raise AssertionError((url, kwargs))

    monkeypatch.setattr(verify_windows_install, "_request", request)
    monkeypatch.setattr(verify_windows_install, "_json_request", json_request)

    verify_windows_install._run_job(
        "http://127.0.0.1:1", tmp_path, 0, "initial", TEST_SOURCE_SHA
    )

    assert len(document_calls) == 1
    assert document_calls[0]["method"] == "POST"
    assert document_calls[0]["job_token"] == "job-secret"
    assert document_calls[0]["timeout"] == 240
    assert document_calls[0]["payload"]["report_context"]["synthetic_test_only"] is True
    assert len(result_reads) == 2
    assert (tmp_path / "initial-job-0-documents.json").is_file()


def test_windows_job_verifier_recovers_token_for_authenticated_idempotent_replay(
    tmp_path: Path, monkeypatch
) -> None:
    recovered_calls = []
    document_calls = []
    snapshot = {
        "job_id": "job-replayed",
        "code_sha": TEST_SOURCE_SHA,
        "provenance": {
            "qualification_context": {
                "profile": {"id": verify_windows_install.PROFILE["id"]},
                "result_fingerprint": TEST_RESULT_FINGERPRINT,
            }
        },
        "value": {"point": 123.0},
    }

    def request(url: str, **kwargs) -> bytes:
        if url.endswith("/jobs"):
            return json.dumps(
                {"job_id": "job-replayed", "idempotent_replay": True}
            ).encode()
        name = url.rsplit("/", 1)[-1]
        if name == "frozen_project.json":
            return json.dumps(
                {"provenance": {"code_sha": TEST_SOURCE_SHA}}
            ).encode()
        if name == "report.pdf":
            return b"%PDF-test"
        if name in {"report.docx", "evidence_bundle.zip"}:
            return b"PK-test"
        raise AssertionError((url, kwargs))

    def json_request(url: str, **kwargs) -> dict:
        if url.endswith("/access-token"):
            recovered_calls.append(kwargs)
            return {"access_token": "recovered-secret"}
        if url.endswith("/documents"):
            document_calls.append(kwargs)
            artifacts = {
                "report.pdf": b"%PDF-test",
                "report.docx": b"PK-test",
                "evidence_bundle.zip": b"PK-test",
            }
            return {
                "job_id": "job-replayed",
                "result_fingerprint": TEST_RESULT_FINGERPRINT,
                "report_content_fingerprint": TEST_REPORT_FINGERPRINT,
                "document_state": {
                    "result_fingerprint": TEST_RESULT_FINGERPRINT,
                    "report_content_fingerprint": TEST_REPORT_FINGERPRINT,
                },
                "artifacts": {
                    name: {
                        "size": len(value),
                        "sha256": hashlib.sha256(value).hexdigest(),
                    }
                    for name, value in artifacts.items()
                },
            }
        if url.endswith("/result"):
            return snapshot
        if url.endswith("/jobs/job-replayed"):
            return {"state": "succeeded"}
        if url.endswith("/revisions"):
            return {"revision_id": "revision-test"}
        if url.endswith("/projects/TESTE-C06-PROJETO"):
            return {"revision": {"revision_id": "revision-test"}}
        raise AssertionError((url, kwargs))

    monkeypatch.setattr(verify_windows_install, "_request", request)
    monkeypatch.setattr(verify_windows_install, "_json_request", json_request)

    verify_windows_install._run_job(
        "http://127.0.0.1:1",
        tmp_path,
        0,
        "initial",
        TEST_SOURCE_SHA,
        allow_idempotent_replay=True,
    )

    assert recovered_calls == [{"method": "POST", "payload": {}}]
    assert document_calls[0]["job_token"] == "recovered-secret"


def test_windows_job_verifier_rejects_replay_as_recalculation(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        verify_windows_install,
        "_request",
        lambda *_args, **_kwargs: json.dumps(
            {"job_id": "old-job", "idempotent_replay": True}
        ).encode(),
    )

    with pytest.raises(
        verify_windows_install.VerificationError,
        match="recalculation was not exercised",
    ):
        verify_windows_install._run_job(
            "http://127.0.0.1:1", tmp_path, 0, "upgrade", TEST_SOURCE_SHA
        )


@pytest.mark.parametrize("invalid_replay", [0, 1, None, "false"])
def test_windows_job_verifier_requires_boolean_replay_state(
    tmp_path: Path, monkeypatch, invalid_replay
) -> None:
    monkeypatch.setattr(
        verify_windows_install,
        "_request",
        lambda *_args, **_kwargs: json.dumps(
            {
                "job_id": "job-test",
                "access_token": "job-secret",
                "idempotent_replay": invalid_replay,
            }
        ).encode(),
    )

    with pytest.raises(
        verify_windows_install.VerificationError,
        match="idempotent_replay state",
    ):
        verify_windows_install._run_job(
            "http://127.0.0.1:1", tmp_path, 0, "upgrade", TEST_SOURCE_SHA
        )


def test_document_binding_rejects_null_artifact_metadata() -> None:
    generated = {
        "job_id": "job-test",
        "result_fingerprint": TEST_RESULT_FINGERPRINT,
        "report_content_fingerprint": TEST_REPORT_FINGERPRINT,
        "document_state": {
            "result_fingerprint": TEST_RESULT_FINGERPRINT,
            "report_content_fingerprint": TEST_REPORT_FINGERPRINT,
        },
        "artifacts": {
            "report.pdf": None,
            "report.docx": None,
            "evidence_bundle.zip": None,
        },
    }
    snapshot = {
        "provenance": {
            "qualification_context": {
                "result_fingerprint": TEST_RESULT_FINGERPRINT,
            }
        }
    }

    with pytest.raises(
        verify_windows_install.VerificationError,
        match="invalid hash/size",
    ):
        verify_windows_install._validated_document_artifacts(generated)


def test_windows_product_shutdown_kills_complete_process_tree(
    monkeypatch,
) -> None:
    class Process:
        pid = 4242
        returncode = None
        terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True

        def wait(self, *, timeout):
            assert timeout == 20
            self.returncode = 1
            return self.returncode

    monkeypatch.setattr(verify_windows_install.os, "name", "nt")
    monkeypatch.setattr(
        verify_windows_install, "_windows_descendant_pids", lambda _pid: [5001, 5002]
    )
    monkeypatch.setattr(
        verify_windows_install,
        "_windows_open_process_handles",
        lambda _pids: [(5001, 101), (5002, 102)],
    )
    monkeypatch.setattr(
        verify_windows_install,
        "_wait_for_windows_children_stopped",
        lambda _pids: [],
    )
    monkeypatch.setattr(
        verify_windows_install, "_windows_close_process_handles", lambda _items: []
    )
    monkeypatch.setattr(
        verify_windows_install, "_wait_for_product_ports_closed", lambda: []
    )
    process = Process()

    result = verify_windows_install._stop(process, None)

    assert process.terminated is True
    assert result == {
        "status": "PASSED",
        "parent_pid": 4242,
        "method": "parent_termination_with_job_containment",
        "parent_returncode": 1,
        "observed_child_pids": [5001, 5002],
        "observed_child_handle_count": 2,
        "child_processes_exited": True,
        "remaining_child_pids_before_fallback": [],
        "service_ports_closed": True,
        "child_observation_error": None,
        "child_handle_close_failures": [],
    }


def test_windows_product_shutdown_fails_before_using_cleanup_fallback(
    monkeypatch,
) -> None:
    process = SimpleNamespace(
        pid=4242,
        returncode=None,
        poll=lambda: None,
        terminate=lambda: None,
        wait=lambda *, timeout: 1,
    )
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(verify_windows_install.os, "name", "nt")
    monkeypatch.setattr(
        verify_windows_install, "_windows_descendant_pids", lambda _pid: [5001]
    )
    monkeypatch.setattr(
        verify_windows_install,
        "_windows_open_process_handles",
        lambda _pids: [(5001, 101)],
    )
    monkeypatch.setattr(
        verify_windows_install,
        "_wait_for_windows_children_stopped",
        lambda _pids: [5001],
    )
    monkeypatch.setattr(
        verify_windows_install, "_windows_close_process_handles", lambda _items: []
    )
    monkeypatch.setenv("SystemRoot", r"C:\WINDOWS")
    monkeypatch.setattr(
        verify_windows_install,
        "_wait_for_product_ports_closed",
        lambda: [],
    )
    monkeypatch.setattr(verify_windows_install.subprocess, "run", run)

    result = verify_windows_install._stop(process, None)

    assert calls[0][0] == [
        r"C:\WINDOWS\System32\taskkill.exe",
        "/IM",
        "MODELA-PRO.exe",
        "/T",
        "/F",
    ]
    assert result["status"] == "FAILED"
    assert result["child_processes_exited"] is False
    assert result["remaining_child_pids_before_fallback"] == [5001]
    assert result["service_ports_closed"] is True
    assert result["fallback_taskkill_exit_code"] == 0
    assert "child processes" in result["error"]["detail"]


def test_windows_product_shutdown_fails_closed_when_child_observation_is_unavailable(
    monkeypatch,
) -> None:
    process = SimpleNamespace(
        pid=4242,
        returncode=None,
        poll=lambda: None,
        terminate=lambda: None,
        wait=lambda *, timeout: 1,
    )
    monkeypatch.setattr(verify_windows_install.os, "name", "nt")
    monkeypatch.setattr(
        verify_windows_install,
        "_windows_descendant_pids",
        lambda _pid: (_ for _ in ()).throw(PermissionError("access denied")),
    )
    monkeypatch.setattr(
        verify_windows_install, "_wait_for_product_ports_closed", lambda: []
    )
    monkeypatch.setattr(
        verify_windows_install, "_windows_close_process_handles", lambda _items: []
    )
    monkeypatch.setattr(
        verify_windows_install.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
    )

    result = verify_windows_install._stop(process, None)

    assert result["status"] == "FAILED"
    assert "PermissionError: access denied" in result["child_observation_error"]
    assert result["fallback_taskkill_exit_code"] == 0


def test_windows_transition_scope_separates_bootstrap_from_distinct_recalculation():
    assert (
        verify_windows_install._transition_scope(
            TEST_SOURCE_SHA, TEST_TREE_SHA, TEST_SOURCE_SHA, TEST_TREE_SHA
        )
        == "OPERATIONAL_SAME_TREE_ONLY"
    )
    assert (
        verify_windows_install._transition_scope(
            TEST_SOURCE_SHA, TEST_TREE_SHA, "c" * 40, "d" * 40
        )
        == "DISTINCT_SOURCE_RECALCULATION"
    )
    with pytest.raises(
        verify_windows_install.VerificationError,
        match="partially distinct",
    ):
        verify_windows_install._transition_scope(
            TEST_SOURCE_SHA, TEST_TREE_SHA, "c" * 40, TEST_TREE_SHA
        )


def test_windows_update_semantic_comparison_ignores_only_execution_identity(tmp_path: Path) -> None:
    first = {
        "job_id": "job-a",
        "generated_at": "2026-09-12T00:00:00Z",
        "code_sha": "a" * 40,
        "value": {"point": 123.0, "mean_ci80": [120.0, 126.0]},
        "policy": {"mode": "exact", "generated_at": "material-policy-date"},
        "search": {
            "audit": {
                "profile": {
                    "elapsed_s": 1.0,
                    "rss_bytes_before": 100,
                    "rss_bytes_after": 200,
                    "host": "this_process_only",
                }
            }
        },
        "provenance": {
            "qualification_context": {
                "result_fingerprint": "1" * 64,
                "report_content_fingerprint": "2" * 64,
                "rule_results": [{"rule_id": "rule-a", "status": "passed"}],
            }
        },
    }
    second = json.loads(json.dumps(first))
    second.update({"job_id": "job-b", "generated_at": "later", "code_sha": "b" * 40})
    second["provenance"]["qualification_context"].update(
        {
            "result_fingerprint": "3" * 64,
            "report_content_fingerprint": "4" * 64,
        }
    )
    second["search"]["audit"]["profile"].update(
        {"elapsed_s": 2.0, "rss_bytes_before": 300, "rss_bytes_after": 400}
    )
    first_hash = verify_windows_install._semantic_result_evidence(first, tmp_path / "first.json")
    second_hash = verify_windows_install._semantic_result_evidence(second, tmp_path / "second.json")
    assert first_hash == second_hash
    second["value"] = {"point": 123.0, "mean_ci80": [119.0, 127.0]}
    changed_hash = verify_windows_install._semantic_result_evidence(second, tmp_path / "changed.json")
    assert changed_hash != first_hash
    second = json.loads(json.dumps(first))
    second["policy"]["generated_at"] = "changed-material-policy-date"
    nested_change_hash = verify_windows_install._semantic_result_evidence(
        second, tmp_path / "nested-change.json"
    )
    assert nested_change_hash != first_hash


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
    assert 'collect_submodules("streamlit")' in spec
    assert 'collect_submodules("pyhanko_certvalidator")' in spec
    assert 'collect_submodules("pypdf")' in spec
    assert '[str(root / "scripts" / "c15_local" / "launcher.py")]' in spec
    assert 'Analysis(\n    ["scripts/c15_local/launcher.py"]' not in spec
    assert 'pathex=[str(root)]' in spec
    assert "exclude_binaries=True" in spec
    assert "COLLECT(" in spec
    assert 'copy_metadata("streamlit", recursive=True)' in spec
    assert 'collect_data_files("streamlit")' in spec
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
