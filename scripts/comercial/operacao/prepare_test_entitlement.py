"""Create a TEST-only artifact anchor and entitlement; never persist its private key."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

from modules.commercial_license import make_signed_envelope


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(output: Path) -> Path:
    if output.exists() and any(output.iterdir()):
        raise RuntimeError("TEST entitlement output must be empty")
    output.mkdir(parents=True, exist_ok=True)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    key_id = "TESTE-C06-" + hashlib.sha256(public_key).hexdigest()[:16]
    anchor = {
        "schema": "MP-COM-TRUSTED-VENDOR/1",
        "state": "CONFIGURED",
        "environment": "synthetic_test",
        "algorithm": "Ed25519",
        "purpose": "buyer_entitlement",
        "key_id": key_id,
        "public_key_base64url": _b64url(public_key),
        "display_label": "BUILD SINTÉTICO DE TESTE — NÃO COMERCIAL",
        "note": "Synthetic CI anchor without commercial validity; private key was not persisted.",
    }
    entitlement = make_signed_envelope(
        {
            "license_id": "TESTE-C06-WINDOWS-SEM-VALIDADE-COMERCIAL",
            "expires_on": "2099-12-31",
            "rights": ["calculate", "read", "export"],
            "synthetic": True,
            "trusted_anchor_key_id": key_id,
        },
        private_key,
    )
    anchor_path = output / "trusted_vendor_anchor.json"
    entitlement_path = output / "synthetic-test-entitlement.json"
    anchor_path.write_text(json.dumps(anchor, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    entitlement_path.write_text(
        json.dumps(entitlement, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "MP-COM-TEST-ENTITLEMENT/1",
        "test_only": True,
        "private_key_persisted": False,
        "key_id": key_id,
        "files": {
            anchor_path.name: _sha256(anchor_path),
            entitlement_path.name: _sha256(entitlement_path),
        },
    }
    manifest_path = output / "test-entitlement-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    prepare(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
