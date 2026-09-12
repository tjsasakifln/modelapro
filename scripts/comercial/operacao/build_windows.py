"""Build Windows x64 artifacts; fails before creating a misleading release."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.comercial.operacao import audit, sbom


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        )
        sbom_path = evidence / "SBOM.modelapro.json"
        sbom_path.write_text(
            json.dumps(sbom_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        stage(current_stage, "PASSED")
        current_stage = "pyinstaller"
        stage(current_stage, "RUNNING")
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(output), str(spec)],
            cwd=root,
            check=True,
        )
        bundle = output / "MODELA-PRO"
        if not bundle.is_dir() or not (bundle / "MODELA-PRO.exe").is_file():
            raise RuntimeError("PyInstaller did not produce the expected Windows onedir bundle")
        shutil.copy2(sbom_path, bundle / sbom_path.name)
        shutil.copy2(audit_path, bundle / audit_path.name)
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
    manifest = {
        "schema_version": "MP-COM-RELEASE/1",
        "version": version,
        "source_sha": source_sha,
        "tree_sha": status["tree_sha"],
        "platform": "windows-x64",
        "generated_at": timestamp,
        "signing_status": "UNSIGNED",
        "commercial_release_ready": False,
        "blocking_reasons": [
            "repository/title licence decision not attached",
            "installer code signature not attached",
            "clean-machine install/upgrade/rollback evidence not attached",
        ],
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
