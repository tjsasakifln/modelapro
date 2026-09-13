"""Build Windows x64 artifacts; fails before creating a misleading release."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.comercial.operacao import audit, sbom


BUILD_IDENTITY_FILENAME = "build-source-identity.json"
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_bundle_inventory(
    bundle: Path,
    destination: Path,
    *,
    source_sha: str,
    tree_sha: str,
) -> dict:
    """Hash every file that Inno Setup will consume from the onedir bundle."""
    if not _GIT_SHA_RE.fullmatch(source_sha or "") or not _GIT_SHA_RE.fullmatch(
        tree_sha or ""
    ):
        raise RuntimeError("bundle inventory requires verified source and tree identities")
    entries = [
        {
            "path": path.relative_to(bundle).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in sorted(
            bundle.rglob("*"), key=lambda item: item.relative_to(bundle).as_posix()
        )
        if path.is_file()
    ]
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    payload = {
        "schema_version": "MP-COM-WINDOWS-BUNDLE-INVENTORY/1",
        "scope": "complete-pyinstaller-onedir-consumed-by-inno-setup",
        "source_sha": source_sha,
        "tree_sha": tree_sha,
        "file_count": len(entries),
        "total_size": sum(entry["size"] for entry in entries),
        "inventory_sha256": hashlib.sha256(encoded).hexdigest(),
        "files": entries,
    }
    _write_status(destination, payload)
    return payload


def _source_identity(root: Path) -> str:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if status.returncode != 0 or status.stdout.strip():
        raise RuntimeError("release build requires a clean, committed source checkout")
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("release build source commit could not be resolved")
    return result.stdout.strip()


def _git_identity(root: Path, ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", ref],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"release build git identity could not resolve {ref!r}")
    return result.stdout.strip()


def _write_status(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _validate_native_runtime(native_root: Path) -> tuple[Path, dict]:
    manifest = native_root / "native-runtime.json"
    if not manifest.is_file():
        raise FileNotFoundError(
            "MODELA_WINDOWS_NATIVE_DIR/native-runtime.json is required for the Windows PDF runtime"
        )
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Windows native runtime manifest is not valid JSON") from exc
    if payload.get("schema_version") != "MP-COM-WINDOWS-NATIVE/1":
        raise RuntimeError("Windows native runtime manifest has an unsupported schema")
    if payload.get("platform") != "windows-x64-ucrt":
        raise RuntimeError("Windows native runtime manifest has the wrong platform")

    def verify(relative: str, expected_size: object, expected_sha256: object) -> None:
        candidate = (native_root / relative).resolve()
        try:
            candidate.relative_to(native_root.resolve())
        except ValueError as exc:
            raise RuntimeError("Windows native runtime manifest contains path traversal") from exc
        if not candidate.is_file():
            raise RuntimeError(f"Windows native runtime file is absent: {relative}")
        if candidate.stat().st_size != expected_size or sha256(candidate) != expected_sha256:
            raise RuntimeError(f"Windows native runtime file does not match its manifest: {relative}")

    dll_entries = payload.get("dlls")
    if not isinstance(dll_entries, list) or not dll_entries:
        raise RuntimeError("Windows native runtime manifest contains no DLL closure")
    declared_dlls = set()
    for entry in dll_entries:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or Path(name).name != name or not name.lower().endswith(".dll"):
            raise RuntimeError("Windows native runtime manifest contains an invalid DLL name")
        declared_dlls.add(name.lower())
        verify(f"dlls/{name}", entry.get("size"), entry.get("sha256"))
    actual_dlls = {path.name.lower() for path in (native_root / "dlls").glob("*.dll")}
    if actual_dlls != declared_dlls:
        raise RuntimeError("Windows native runtime DLL directory differs from its manifest")

    fontconfig = payload.get("fontconfig")
    if not isinstance(fontconfig, dict):
        raise RuntimeError("Windows native runtime manifest contains no fontconfig evidence")
    verify(str(fontconfig.get("path")), fontconfig.get("size"), fontconfig.get("sha256"))
    for package in payload.get("packages") or []:
        for entry in package.get("license_files") or []:
            verify(str(entry.get("path")), entry.get("size"), entry.get("sha256"))
    return manifest, payload


def _validate_build_anchor(root: Path) -> tuple[Path, dict]:
    value = os.environ.get("MODELA_BUILD_TRUSTED_ANCHOR", "").strip()
    anchor = (
        Path(value)
        if value
        else root / "modules" / "commercial_license" / "trusted_vendor_anchor.json"
    )
    try:
        payload = json.loads(anchor.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("trusted vendor build anchor is absent or invalid") from exc
    if payload.get("schema") != "MP-COM-TRUSTED-VENDOR/1":
        raise RuntimeError("trusted vendor build anchor has an unsupported schema")
    if payload.get("algorithm") != "Ed25519" or payload.get("purpose") != "buyer_entitlement":
        raise RuntimeError("trusted vendor build anchor has the wrong algorithm or purpose")
    if payload.get("environment") not in {"production", "synthetic_test"}:
        raise RuntimeError("trusted vendor build anchor has an unknown environment")
    if payload.get("state") == "CONFIGURED":
        try:
            public = base64.urlsafe_b64decode(
                str(payload["public_key_base64url"])
                + "=" * (-len(str(payload["public_key_base64url"])) % 4)
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise RuntimeError("trusted vendor build anchor key is not base64url") from exc
        if len(public) != 32 or not payload.get("key_id"):
            raise RuntimeError("trusted vendor build anchor is incomplete")
    elif payload.get("state") != "UNCONFIGURED":
        raise RuntimeError("trusted vendor build anchor has an unknown state")
    return anchor, payload


def build(
    root: Path,
    output: Path,
    version: str,
    *,
    generated_at: str | None = None,
    lock: Path | None = None,
) -> Path:
    if platform.system() != "Windows" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("Windows x64 build must run on Windows x64; no cross-build claim is made")
    spec = root / "packaging" / "comercial" / "modelapro.spec"
    iss = root / "packaging" / "comercial" / "modelapro.iss"
    if not spec.is_file() or not iss.is_file():
        raise FileNotFoundError("commercial build specifications are missing")
    native_root_value = os.environ.get("MODELA_WINDOWS_NATIVE_DIR", "").strip()
    native_root = Path(native_root_value) if native_root_value else None
    if native_root is None:
        raise FileNotFoundError(
            "MODELA_WINDOWS_NATIVE_DIR/native-runtime.json is required for the Windows PDF runtime"
        )
    native_manifest, native_payload = _validate_native_runtime(native_root)
    trusted_anchor, anchor_payload = _validate_build_anchor(root)
    source_sha = _source_identity(root)
    lock = lock or root / "constraints" / "windows-py312-x64.txt"
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("output must be a new or empty staging directory; refusing stale artifacts")
    output.mkdir(parents=True, exist_ok=True)
    evidence = output / "qualification-evidence"
    evidence.mkdir()
    status_path = evidence / "build-status.json"
    status = {
        "schema_version": "MP-COM-WINDOWS-BUILD/1",
        "version": version,
        "source_sha": source_sha,
        "tree_sha": _git_identity(root, "HEAD^{tree}"),
        "platform": "windows-x64",
        "status": "RUNNING",
        "commercial_release_ready": False,
        "stages": {},
    }

    def stage(name: str, value: str, detail: str | None = None) -> None:
        status["stages"][name] = {"status": value}
        if detail:
            status["stages"][name]["detail"] = detail
        _write_status(status_path, status)

    current_stage = "environment_lock"
    try:
        stage(current_stage, "RUNNING")
        sbom.assert_environment_matches_lock(sys.executable, lock)
        stage(current_stage, "PASSED")
        current_stage = "vulnerability_audit"
        stage(current_stage, "RUNNING")
        audit_path = evidence / "pip-audit.json"
        audit_exit = audit.audit(sys.executable, audit_path)
        if audit_exit != 0:
            raise RuntimeError(
                f"pip-audit blocked the Windows build (exit {audit_exit}); "
                "review the preserved report before rebuilding"
            )
        stage(current_stage, "PASSED")
        current_stage = "sbom"
        stage(current_stage, "RUNNING")
        timestamp = generated_at or datetime.now(timezone.utc).isoformat()
        sbom_payload = sbom.build_sbom(
            sys.executable,
            generated_at=timestamp,
            lock=lock,
            root_distribution="modelapro",
        )
        sbom_path = evidence / "SBOM.modelapro.json"
        sbom_path.write_text(
            json.dumps(sbom_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        stage(current_stage, "PASSED")
        current_stage = "pyinstaller"
        stage(current_stage, "RUNNING")
        build_identity = evidence / BUILD_IDENTITY_FILENAME
        _write_status(
            build_identity,
            {
                "schema_version": "MP-COM-BUILD-IDENTITY/1",
                "source_sha": source_sha,
                "tree_sha": status["tree_sha"],
            },
        )
        pyinstaller_env = os.environ.copy()
        pyinstaller_env["MODELA_BUILD_SOURCE_IDENTITY_FILE"] = str(build_identity)
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(output), str(spec)],
            cwd=root,
            env=pyinstaller_env,
            check=True,
        )
        bundle = output / "MODELA-PRO"
        if not bundle.is_dir() or not (bundle / "MODELA-PRO.exe").is_file():
            raise RuntimeError("PyInstaller did not produce the expected Windows onedir bundle")
        shutil.copy2(sbom_path, bundle / sbom_path.name)
        shutil.copy2(audit_path, bundle / audit_path.name)
        shutil.copy2(native_manifest, evidence / native_manifest.name)
        shutil.copy2(trusted_anchor, evidence / "artifact-trusted-vendor-anchor.json")
        _write_bundle_inventory(
            bundle,
            evidence / "bundle-file-inventory.json",
            source_sha=source_sha,
            tree_sha=status["tree_sha"],
        )
        stage(current_stage, "PASSED")
        current_stage = "installer"
        stage(current_stage, "RUNNING")
        iscc = "iscc.exe"
        subprocess.run(
            [iscc, f"/O{output}", f"/DAppVersion={version}", f"/DBundleDir={bundle}", str(iss)],
            cwd=root,
            check=True,
        )
        installer = output / f"MODELA-PRO-{version}-win64.exe"
        if not installer.is_file():
            raise RuntimeError(f"Inno Setup did not produce expected installer: {installer.name}")
        stage(current_stage, "PASSED")
    except BaseException as exc:
        stage(current_stage, "FAILED", f"{type(exc).__name__}: {exc}")
        status["status"] = "FAILED"
        _write_status(status_path, status)
        raise
    status["status"] = "BUILT_NOT_VERIFIED"
    _write_status(status_path, status)
    files = sorted(path for path in output.rglob("*") if path.is_file())
    python_review_queue = list(sbom_payload.get("review_queue") or [])
    native_review_queue = list(native_payload.get("review_queue") or [])
    blocking_reasons = [
        "product ownership authority and buyer terms decision not recorded with the candidate",
        "installed lifecycle verification belongs to the Windows workflow "
        "and is not complete in this build-only manifest",
    ]
    if python_review_queue:
        blocking_reasons.append(
            f"{len(python_review_queue)} Python distributions require licence metadata review"
        )
    if native_review_queue:
        blocking_reasons.append(
            f"{len(native_review_queue)} native packages require licence file/metadata review"
        )
    if anchor_payload.get("state") != "CONFIGURED":
        blocking_reasons.append("trusted vendor entitlement anchor is not configured")
    elif anchor_payload.get("environment") == "synthetic_test":
        blocking_reasons.append("artifact uses a synthetic TEST-only entitlement anchor")
    manifest = {
        "schema_version": "MP-COM-RELEASE/1",
        "version": version,
        "source_sha": source_sha,
        "tree_sha": status["tree_sha"],
        "platform": "windows-x64",
        "generated_at": timestamp,
        "signing_status": "UNSIGNED",
        "signing_requirement": "OPTIONAL_UNLESS_APPROVED_OFFER_REQUIRES_CODE_SIGNING",
        "commercial_release_ready": False,
        "blocking_reasons": blocking_reasons,
        "review_queue_summary": {
            "python_distributions": len(python_review_queue),
            "native_packages": len(native_review_queue),
        },
        "trusted_entitlement_anchor": {
            "state": anchor_payload.get("state"),
            "key_id": anchor_payload.get("key_id"),
            "environment": anchor_payload.get("environment"),
            "display_label": anchor_payload.get("display_label"),
            "test_only": anchor_payload.get("environment") == "synthetic_test",
            "sha256": sha256(trusted_anchor),
        },
        "artifacts": [
            {"path": str(path.relative_to(output)), "sha256": sha256(path)}
            for path in files
        ],
    }
    target = output / "release-manifest.json"
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--lock",
        type=Path,
        help="exact Windows x64 environment lock (default: constraints/windows-py312-x64.txt)",
    )
    parser.add_argument(
        "--generated-at",
        help="RFC3339 build timestamp; set explicitly for reproducible evidence metadata",
    )
    args = parser.parse_args(argv)
    build(
        args.root.resolve(),
        args.output.resolve(),
        args.version,
        generated_at=args.generated_at,
        lock=args.lock.resolve() if args.lock else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
