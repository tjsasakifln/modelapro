"""Create a deterministic SBOM JSON inventory from an installed environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _canonical_name(value: str) -> str:
    return "-".join(filter(None, re.split(r"[-_.]+", value.lower())))


def locked_versions(lock: Path) -> dict[str, str]:
    """Read exact name/version pins; reject constraints that are not immutable."""
    if not lock.is_file():
        raise FileNotFoundError(f"lock file does not exist: {lock}")
    versions: dict[str, str] = {}
    for number, raw in enumerate(lock.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.count("==") != 1 or any(mark in line for mark in (";", " @ ", "[", "]")):
            raise ValueError(f"lock line {number} is not an unconditional exact pin")
        name, version = line.split("==", 1)
        if not name or not version:
            raise ValueError(f"lock line {number} is incomplete")
        versions[_canonical_name(name)] = version
    return versions


def assert_environment_matches_lock(python: str, lock: Path) -> dict[str, object]:
    """Fail when an installed build environment differs from its declared lock."""
    expected = locked_versions(lock)
    installed = {
        _canonical_name(item["name"]): str(item["version"])
        for item in _pip_report(python)
        if _canonical_name(item["name"]) != "modelapro"
    }
    missing = sorted(name for name in expected if name not in installed)
    unexpected = sorted(name for name in installed if name not in expected)
    mismatched = {
        name: {"expected": expected[name], "installed": installed[name]}
        for name in sorted(expected.keys() & installed.keys())
        if expected[name] != installed[name]
    }
    result = {"matches": not (missing or unexpected or mismatched), "missing": missing,
              "unexpected": unexpected, "mismatched": mismatched}
    if not result["matches"]:
        raise RuntimeError(f"installed build environment does not match lock: {result}")
    return result


def _pip_report(python: str) -> list[dict]:
    result = subprocess.run(
        [python, "-m", "pip", "list", "--format=json"], check=True, capture_output=True, text=True
    )
    packages = json.loads(result.stdout)
    if not isinstance(packages, list):
        raise ValueError("pip list did not return a package list")
    return sorted(packages, key=lambda item: item["name"].lower())


def _metadata(python: str, name: str) -> dict:
    script = r"""
import hashlib
import importlib.metadata
import json
import pathlib
import sys

dist = importlib.metadata.distribution(sys.argv[1])
metadata = dist.metadata
license_files = []
native_files = []
font_files = []
for entry in dist.files or ():
    relative = str(entry).replace('\\', '/')
    basename = pathlib.PurePosixPath(relative).name.lower()
    located = pathlib.Path(dist.locate_file(entry))
    if not located.is_file():
        continue
    if basename.startswith(('license', 'copying', 'notice', 'authors')):
        payload = located.read_bytes()
        license_files.append({
            'path': relative,
            'sha256': hashlib.sha256(payload).hexdigest(),
            'size': len(payload),
        })
    if located.suffix.lower() in {'.dll', '.dylib', '.pyd', '.so'} or '.so.' in basename:
        payload = located.read_bytes()
        native_files.append({
            'path': relative,
            'sha256': hashlib.sha256(payload).hexdigest(),
            'size': len(payload),
        })
    if located.suffix.lower() in {'.ttf', '.otf', '.woff', '.woff2', '.pfb'}:
        payload = located.read_bytes()
        font_files.append({
            'path': relative,
            'sha256': hashlib.sha256(payload).hexdigest(),
            'size': len(payload),
        })
print(json.dumps({
    'license': metadata.get('License') or '',
    'license_expression': metadata.get('License-Expression') or '',
    'home_page': metadata.get('Home-page') or '',
    'project_urls': metadata.get_all('Project-URL') or [],
    'summary': metadata.get('Summary') or '',
    'license_files': sorted(license_files, key=lambda item: item['path']),
    'native_files': sorted(native_files, key=lambda item: item['path']),
    'font_files': sorted(font_files, key=lambda item: item['path']),
}))
"""
    result = subprocess.run([python, "-c", script, name], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def build_sbom(
    python: str = sys.executable, *, generated_at: str | None = None, lock: Path | None = None
) -> dict:
    """Inventory installed distributions, preserving unknown licences as unknown."""
    components = []
    for package in sorted(_pip_report(python), key=lambda item: item["name"].lower()):
        meta = _metadata(python, package["name"])
        license_value = meta["license_expression"] or meta["license"] or "NOASSERTION"
        components.append(
            {
                "type": "library",
                "name": package["name"],
                "version": package["version"],
                # Distribution Metadata commonly contains prose, not an SPDX id.
                # Preserve it as a name rather than claiming SPDX validation.
                "licenses": [{"license": {"name": license_value}}],
                "properties": [
                    {"name": "modelapro:home_page", "value": meta["home_page"]},
                    {"name": "modelapro:summary", "value": meta["summary"]},
                ],
                "evidence": {
                    "identity_source": "installed-distribution-metadata",
                    "project_urls": list(meta.get("project_urls") or []),
                    "license_files": list(meta.get("license_files") or []),
                    "native_files": list(meta.get("native_files") or []),
                    "font_files": list(meta.get("font_files") or []),
                },
            }
        )
    component_bytes = json.dumps(components, sort_keys=True, separators=(",", ":")).encode()
    component_hash = hashlib.sha256(component_bytes).hexdigest()
    metadata = {
        "timestamp": generated_at or datetime.now(timezone.utc).isoformat(),
        "component_hash_sha256": component_hash,
    }
    if lock is not None:
        if not lock.is_file():
            raise FileNotFoundError(f"lock file does not exist: {lock}")
        metadata["lock_path"] = str(lock)
        metadata["lock_sha256"] = hashlib.sha256(lock.read_bytes()).hexdigest()
    seed = json.dumps({"metadata": metadata, "components": components}, sort_keys=True, separators=(",", ":"))
    payload = {
        "bomFormat": "MODELA-PRO-SBOM",
        "specVersion": "MP-SBOM/1",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, seed)}",
        "version": 1,
        "metadata": metadata,
        "components": components,
        "review_queue": [
            {
                "name": component["name"],
                "version": component["version"],
                "reason": "license_metadata_missing",
            }
            for component in components
            if component["licenses"][0]["license"]["name"] == "NOASSERTION"
        ],
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lock", type=Path, help="exact constraints/lock file used to create the environment")
    parser.add_argument("--generated-at", help="RFC3339 timestamp, required for byte-repeatable output")
    args = parser.parse_args(argv)
    if not args.generated_at:
        parser.error("--generated-at is required for reproducible release evidence")
    payload = build_sbom(args.python, generated_at=args.generated_at, lock=args.lock)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
