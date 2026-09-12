"""Build Windows x64 artifacts; fails before creating a misleading release."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(root: Path, output: Path, version: str) -> Path:
    if platform.system() != "Windows" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("Windows x64 build must run on Windows x64; no cross-build claim is made")
    spec = root / "packaging" / "comercial" / "modelapro.spec"
    iss = root / "packaging" / "comercial" / "modelapro.iss"
    if not spec.is_file() or not iss.is_file():
        raise FileNotFoundError("commercial build specifications are missing")
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("output must be a new or empty staging directory; refusing stale artifacts")
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(output), str(spec)], cwd=root, check=True)
    iscc = "iscc.exe"
    subprocess.run(
        [iscc, f"/O{output}", f"/DAppVersion={version}", f"/DBundleDir={output / 'MODELA-PRO'}", str(iss)],
        cwd=root,
        check=True,
    )
    files = sorted(path for path in output.rglob("*") if path.is_file())
    manifest = {"version": version, "platform": "windows-x64", "artifacts": [{"path": str(p.relative_to(output)), "sha256": sha256(p)} for p in files]}
    target = output / "release-manifest.json"
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    build(args.root.resolve(), args.output.resolve(), args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
