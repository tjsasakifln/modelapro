"""Stage the exact MSYS2 UCRT64 DLL closure needed by WeasyPrint on Windows.

The output includes package/version/licence metadata and hashes for every DLL
and retained licence file. Unknown metadata remains a review item. This tool
does not assert redistribution rights and does not select a licence for MODELA
PRO itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
from pathlib import Path


REQUIRED_ROOT_DLLS = (
    "libgobject-2.0-0.dll",
    "libpango-1.0-0.dll",
    "libharfbuzz-0.dll",
    "libharfbuzz-subset-0.dll",
    "libfontconfig-1.dll",
    "libpangoft2-1.0-0.dll",
)
OPTIONAL_ROOT_DLLS = ("libharfbuzz-vector-0.dll", "libpangocairo-1.0-0.dll")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_bash(bash: Path, command: str) -> str:
    result = subprocess.run(
        [str(bash), "-lc", command],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _package_owner(bash: Path, filename: str) -> tuple[str, str]:
    output = _run_bash(bash, f"pacman -Qo /ucrt64/bin/{filename}").strip()
    match = re.search(r" is owned by (\S+) (\S+)$", output)
    if not match:
        raise RuntimeError(f"could not resolve MSYS2 package owner for {filename}: {output}")
    return match.group(1), match.group(2)


def _package_info(bash: Path, package: str) -> dict[str, str]:
    output = _run_bash(bash, f"pacman -Qi {package}")
    values: dict[str, str] = {}
    current = None
    for raw in output.splitlines():
        if raw.startswith(" ") and current:
            values[current] = values[current] + " " + raw.strip()
            continue
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        current = key.strip().lower().replace(" ", "_")
        values[current] = value.strip()
    return values


def _license_paths(msys_root: Path, bash: Path, package: str) -> list[Path]:
    output = _run_bash(bash, f"pacman -Ql {package}")
    paths = []
    for raw in output.splitlines():
        parts = raw.split(maxsplit=1)
        if len(parts) != 2 or "/share/licenses/" not in parts[1] or parts[1].endswith("/"):
            continue
        path = msys_root / Path(parts[1].lstrip("/").replace("/", "\\"))
        if path.is_file():
            paths.append(path)
    return sorted(set(paths), key=lambda item: str(item).lower())


def _imported_dlls(path: Path) -> set[str]:
    try:
        import pefile
    except ImportError as exc:
        raise RuntimeError("pefile is required to resolve the Windows DLL closure") from exc
    pe = pefile.PE(str(path), fast_load=True)
    try:
        directories = [pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]]
        delay_key = pefile.DIRECTORY_ENTRY.get("IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT")
        if delay_key is not None:
            directories.append(delay_key)
        pe.parse_data_directories(directories=directories)
        names = set()
        for attr in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
            for entry in getattr(pe, attr, ()):
                names.add(entry.dll.decode("ascii", errors="strict").lower())
        return names
    finally:
        pe.close()


def prepare(msys_root: Path, output: Path) -> Path:
    if platform.system() != "Windows":
        raise RuntimeError("Windows native runtime can only be staged on Windows")
    msys_root = msys_root.resolve()
    binary_root = msys_root / "ucrt64" / "bin"
    bash = msys_root / "usr" / "bin" / "bash.exe"
    if not binary_root.is_dir() or not bash.is_file():
        raise FileNotFoundError(f"MSYS2 UCRT64 runtime not found under {msys_root}")
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("native-runtime output must be empty")
    dll_output = output / "dlls"
    license_output = output / "licenses"
    fontconfig_output = output / "fontconfig"
    dll_output.mkdir(parents=True, exist_ok=True)
    license_output.mkdir()
    fontconfig_output.mkdir()

    fontconfig_source = msys_root / "ucrt64" / "etc" / "fonts" / "fonts.conf"
    if not fontconfig_source.is_file():
        raise FileNotFoundError("MSYS2 fontconfig configuration is absent")
    fontconfig_text = fontconfig_source.read_text(encoding="utf-8")
    if "WINDOWSFONTDIR" not in fontconfig_text:
        raise RuntimeError("fontconfig configuration does not declare the Windows font directory")
    if str(msys_root).replace("\\", "/").lower() in fontconfig_text.replace("\\", "/").lower():
        raise RuntimeError("fontconfig configuration embeds the build-host MSYS2 path")
    fontconfig_target = fontconfig_output / "fonts.conf"
    shutil.copy2(fontconfig_source, fontconfig_target)

    available = {path.name.lower(): path for path in binary_root.glob("*.dll")}
    missing = [name for name in REQUIRED_ROOT_DLLS if name.lower() not in available]
    if missing:
        raise FileNotFoundError(f"required WeasyPrint UCRT64 DLLs are missing: {missing}")
    queue = [name.lower() for name in (*REQUIRED_ROOT_DLLS, *OPTIONAL_ROOT_DLLS) if name.lower() in available]
    selected: set[str] = set()
    system_dependencies: set[str] = set()
    while queue:
        name = queue.pop(0)
        if name in selected:
            continue
        selected.add(name)
        for dependency in sorted(_imported_dlls(available[name])):
            if dependency in available and dependency not in selected:
                queue.append(dependency)
            elif dependency not in available:
                system_dependencies.add(dependency)

    owners: dict[str, dict] = {}
    dll_entries = []
    for name in sorted(selected):
        source = available[name]
        target = dll_output / source.name
        shutil.copy2(source, target)
        package, owner_version = _package_owner(bash, source.name)
        dll_entries.append(
            {
                "name": source.name,
                "package": package,
                "package_owner_version": owner_version,
                "size": target.stat().st_size,
                "sha256": _sha256(target),
            }
        )
        owners.setdefault(package, {"owner_version": owner_version, "dlls": []})["dlls"].append(source.name)

    packages = []
    review_queue = []
    for package, owner in sorted(owners.items()):
        info = _package_info(bash, package)
        retained = []
        for source in _license_paths(msys_root, bash, package):
            package_dir = license_output / package
            package_dir.mkdir(parents=True, exist_ok=True)
            target = package_dir / source.name
            if target.exists() and _sha256(target) != _sha256(source):
                target = package_dir / f"{_sha256(source)[:12]}-{source.name}"
            if not target.exists():
                shutil.copy2(source, target)
            retained.append(
                {
                    "path": str(target.relative_to(output)).replace("\\", "/"),
                    "size": target.stat().st_size,
                    "sha256": _sha256(target),
                }
            )
        license_value = info.get("licenses") or "NOASSERTION"
        entry = {
            "name": package,
            "version": info.get("version") or owner["owner_version"],
            "licenses_metadata": license_value,
            "description": info.get("description") or "",
            "url": info.get("url") or "",
            "dlls": sorted(owner["dlls"], key=str.lower),
            "license_files": retained,
        }
        packages.append(entry)
        if license_value == "NOASSERTION" or not retained:
            reason = (
                "missing_license_metadata"
                if license_value == "NOASSERTION"
                else "license_file_not_retained"
            )
            review_queue.append(
                {
                    "name": package,
                    "version": entry["version"],
                    "reason": reason,
                }
            )

    payload = {
        "schema_version": "MP-COM-WINDOWS-NATIVE/1",
        "platform": "windows-x64-ucrt",
        "source": "MSYS2 UCRT64 installed package database",
        "redistribution_rights_asserted": False,
        "required_roots": list(REQUIRED_ROOT_DLLS),
        "optional_roots_present": [name for name in OPTIONAL_ROOT_DLLS if name.lower() in selected],
        "dlls": dll_entries,
        "packages": packages,
        "system_dependencies_not_copied": sorted(system_dependencies),
        "fontconfig": {
            "path": str(fontconfig_target.relative_to(output)).replace("\\", "/"),
            "size": fontconfig_target.stat().st_size,
            "sha256": _sha256(fontconfig_target),
            "uses_windows_system_fonts": True,
        },
        "review_queue": review_queue,
    }
    manifest = output / "native-runtime.json"
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--msys-root", type=Path, default=Path(r"C:\msys64"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    prepare(args.msys_root, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
