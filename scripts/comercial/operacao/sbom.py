"""Create a deterministic SBOM JSON inventory from an installed environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _pip_report(python: str) -> list[dict]:
    result = subprocess.run(
        [python, "-m", "pip", "list", "--format=json"], check=True, capture_output=True, text=True
    )
    packages = json.loads(result.stdout)
    if not isinstance(packages, list):
        raise ValueError("pip list did not return a package list")
    return sorted(packages, key=lambda item: item["name"].lower())


def _metadata(python: str, name: str) -> dict:
    script = (
        "import importlib.metadata,json,sys; "
        "d=importlib.metadata.metadata(sys.argv[1]); "
        "print(json.dumps({'license':d.get('License') or '',"
        "'license_expression':d.get('License-Expression') or '',"
        "'home_page':d.get('Home-page') or '', 'summary':d.get('Summary') or ''}))"
    )
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
