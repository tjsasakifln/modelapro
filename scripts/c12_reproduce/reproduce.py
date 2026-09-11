#!/usr/bin/env python3
"""Local verification and numeric reproduction for a C12 evidence bundle.

Usage:
    python scripts/c12_reproduce/reproduce.py --bundle PATH
    python scripts/c12_reproduce/reproduce.py --bundle PATH --verify-only

Exit codes:
    0  integrity ok and supported quantities reconstructed within tolerance
    1  usage / I/O error
    2  integrity failure (including one-byte tamper)
    3  reproduction failure or insufficient material (never returns a memorized value)
    4  incompatible schema/bundle version

This command never pickle.loads, eval, exec, or imports files from the bundle.
It only reads JSON/CSV as data. Determinism: two runs on an unchanged package
emit identical primary numbers (no RNG, no clock in the report).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="c12_reproduce",
        description="Verify integrity and reconstruct the original-unit prediction from a C12 evidence bundle.",
    )
    parser.add_argument("--bundle", required=True, help="Path to the local evidence package directory")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Check hashes/versions only; do not attempt numeric reconstruction",
    )
    args = parser.parse_args(argv)

    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    bundle = Path(args.bundle)
    if not bundle.exists():
        _emit({"ok": False, "errors": [f"bundle path does not exist: {bundle}"]})
        return 1

    try:
        from modules.evidence_bundle import reproduce_from_bundle, verify_bundle
        from modules.provenance import SCHEMA_VERSION_MP
    except Exception as exc:
        _emit({"ok": False, "errors": [f"failed to import shipped modules: {exc}"]})
        return 1

    try:
        integrity = verify_bundle(bundle)
    except Exception as exc:
        _emit({"ok": False, "stage": "verify", "errors": [str(exc)]})
        return 2

    versions = integrity.get("versions") or {}
    if not versions.get("compatible", False):
        report = {
            "ok": False,
            "stage": "versions",
            "integrity": _public_integrity(integrity),
            "versions": versions,
            "expected_schema_version": SCHEMA_VERSION_MP,
        }
        _emit(report)
        return 4

    if args.verify_only:
        report = {
            "ok": bool(integrity.get("ok")),
            "stage": "verify",
            "integrity": _public_integrity(integrity),
            "versions": versions,
            "determinism": "pure function of packaged file bytes; no RNG",
        }
        _emit(report)
        return 0 if integrity.get("ok") else 2

    try:
        reproduction = reproduce_from_bundle(bundle)
    except Exception as exc:
        _emit({"ok": False, "stage": "reproduce", "errors": [str(exc)], "integrity": _public_integrity(integrity)})
        return 3

    report = {
        "ok": bool(reproduction.get("ok")),
        "stage": "reproduce",
        "integrity": _public_integrity(reproduction.get("integrity") or integrity),
        "versions": reproduction.get("versions") or versions,
        "promised": reproduction.get("promised"),
        "point": reproduction.get("point"),
        "mean_ci80": reproduction.get("mean_ci80"),
        "prediction_interval": reproduction.get("prediction_interval"),
        "tolerance": reproduction.get("tolerance"),
        "comparison": reproduction.get("comparison"),
        "limitations": reproduction.get("limitations") or [],
        "completeness_missing": reproduction.get("completeness_missing") or [],
        "method": reproduction.get("method"),
        "determinism": reproduction.get("determinism"),
    }
    _emit(report)
    if not (reproduction.get("integrity") or {}).get("ok", False):
        return 2
    if not reproduction.get("ok"):
        return 3
    return 0


def _public_integrity(integrity: dict) -> dict:
    return {
        "ok": bool(integrity.get("ok")),
        "errors": list(integrity.get("errors") or []),
        "files_checked": integrity.get("files_checked"),
        "manifest_has_self_hash": bool(integrity.get("manifest_has_self_hash")),
    }


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    sys.stdout.write("\n")


if __name__ == "__main__":
    sys.exit(main())
