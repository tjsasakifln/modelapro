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

from packaging.requirements import Requirement


DEFAULT_LICENSE_REVIEWS = (
    Path(__file__).resolve().parents[3] / "third_party" / "python_license_reviews.json"
)


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


def _runtime_dependency_graph(python: str, root_distribution: str) -> dict[str, list[str]]:
    """Resolve installed runtime requirements and propagate requested extras."""
    script = r"""
import importlib.metadata
import json
import sys

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

root_requirement = Requirement(sys.argv[1])
root = canonicalize_name(root_requirement.name)
queue = [root]
graph = {}
requested_extras = {root: set(root_requirement.extras)}
environment = default_environment()
while queue:
    name = queue.pop(0)
    dist = importlib.metadata.distribution(name)
    canonical = canonicalize_name(dist.metadata['Name'])
    dependencies = []
    active_extras = requested_extras.get(canonical, set())
    marker_extras = [''] + sorted(active_extras)
    for raw in dist.requires or ():
        requirement = Requirement(raw)
        if requirement.marker is not None and not any(
            requirement.marker.evaluate({**environment, 'extra': extra})
            for extra in marker_extras
        ):
            continue
        dependency = canonicalize_name(requirement.name)
        dependencies.append(dependency)
        previous_extras = requested_extras.setdefault(dependency, set())
        new_extras = set(requirement.extras) - previous_extras
        if new_extras:
            previous_extras.update(new_extras)
        if dependency not in graph or new_extras:
            queue.append(dependency)
    graph[canonical] = sorted(set(dependencies))
print(json.dumps(graph, sort_keys=True))
"""
    result = subprocess.run(
        [python, "-c", script, root_distribution],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    root_name = _canonical_name(Requirement(root_distribution).name)
    if not isinstance(payload, dict) or root_name not in payload:
        raise ValueError("runtime dependency resolver returned an invalid graph")
    return {
        _canonical_name(name): sorted(_canonical_name(item) for item in dependencies)
        for name, dependencies in payload.items()
    }


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


def _license_reviews(path: Path) -> dict[tuple[str, str], dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "MP-COM-PYTHON-LICENSE-REVIEWS/1":
        raise ValueError("Python licence review registry has an unsupported schema")
    reviews: dict[tuple[str, str], dict] = {}
    for item in payload.get("reviews") or ():
        key = (_canonical_name(str(item.get("name") or "")), str(item.get("version") or ""))
        expression = str(item.get("license_expression") or "")
        hashes = item.get("license_file_sha256")
        if not key[0] or not key[1] or not expression or not isinstance(hashes, list) or not hashes:
            raise ValueError("Python licence review registry contains an incomplete review")
        if key in reviews:
            raise ValueError(f"duplicate Python licence review: {key[0]}=={key[1]}")
        if any(not re.fullmatch(r"[0-9a-f]{64}", str(value)) for value in hashes):
            raise ValueError(f"Python licence review contains an invalid hash: {key[0]}=={key[1]}")
        reviews[key] = {
            "license_expression": expression,
            "license_file_sha256": sorted(str(value) for value in hashes),
        }
    return reviews


def _resolved_license(
    name: str,
    version: str,
    metadata: dict,
    reviews: dict[tuple[str, str], dict],
) -> tuple[str, str, dict | None]:
    declared = metadata["license_expression"] or metadata["license"]
    if declared:
        return declared, "installed-distribution-metadata", None
    review = reviews.get((_canonical_name(name), version))
    if review is None:
        return "NOASSERTION", "unresolved", None
    actual_hashes = sorted(
        str(item.get("sha256")) for item in metadata.get("license_files") or ()
    )
    evidence = {
        "status": "MATCHED" if actual_hashes == review["license_file_sha256"] else "MISMATCH",
        "expected_license_file_sha256": review["license_file_sha256"],
        "actual_license_file_sha256": actual_hashes,
    }
    if evidence["status"] == "MISMATCH":
        return "NOASSERTION", "review-evidence-mismatch", evidence
    return review["license_expression"], "version-and-license-file-review", evidence


def build_sbom(
    python: str = sys.executable,
    *,
    generated_at: str | None = None,
    lock: Path | None = None,
    root_distribution: str | None = None,
    license_reviews: Path | None = DEFAULT_LICENSE_REVIEWS,
) -> dict:
    """Inventory installed distributions, preserving unknown licences as unknown."""
    graph = (
        _runtime_dependency_graph(python, root_distribution)
        if root_distribution
        else None
    )
    installed = {
        _canonical_name(item["name"]): item
        for item in _pip_report(python)
    }
    if graph is not None:
        missing = sorted(set(graph) - installed.keys())
        if missing:
            raise RuntimeError(f"runtime dependency closure is not installed: {missing}")
    reviews = _license_reviews(license_reviews) if license_reviews is not None else {}
    components = []
    packages = list(installed.values())
    for package in sorted(packages, key=lambda item: item["name"].lower()):
        meta = _metadata(python, package["name"])
        canonical = _canonical_name(package["name"])
        license_value, license_source, license_review = _resolved_license(
            package["name"], str(package["version"]), meta, reviews
        )
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
                    "license_source": license_source,
                    "license_review": license_review,
                    "declared_runtime_dependency": canonical in (graph or {}),
                    "runtime_dependencies": list((graph or {}).get(canonical) or []),
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
        "inventory_scope": (
            "installed-build-environment" if root_distribution else "installed-environment"
        ),
    }
    if root_distribution:
        metadata["root_distribution"] = _canonical_name(root_distribution)
        metadata["declared_runtime_dependency_closure"] = sorted(graph or {})
    if license_reviews is not None:
        metadata["license_reviews_path"] = str(license_reviews)
        metadata["license_reviews_sha256"] = hashlib.sha256(
            license_reviews.read_bytes()
        ).hexdigest()
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
                "reason": (
                    "license_review_evidence_mismatch"
                    if component["evidence"]["license_source"] == "review-evidence-mismatch"
                    else "license_metadata_missing"
                ),
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
