"""Load the entitlement verification key pinned into this exact artifact."""

from __future__ import annotations

import base64
import json
import os
import sys
from importlib.resources import files
from pathlib import Path


ANCHOR_SCHEMA = "MP-COM-TRUSTED-VENDOR/1"
ANCHOR_RESOURCE = "trusted_vendor_anchor.json"


def _decode_public_key(value: object) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("trusted vendor public key is absent")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise ValueError("trusted vendor public key is not base64url") from exc
    if len(decoded) != 32:
        raise ValueError("trusted vendor Ed25519 public key must be 32 bytes")
    return decoded


def _source_test_override() -> bytes | None:
    """Retain legacy test fixtures without creating an installed-product override."""
    if os.environ.get("MODELA_TEST_CONTEXT") != "1" or getattr(sys, "frozen", False):
        return None
    root = Path(__file__).resolve().parents[2]
    if not (root / "tests").is_dir() or not (root / "pyproject.toml").is_file():
        return None
    value = os.environ.get("MODELA_LICENSE_PUBLIC_KEY")
    return _decode_public_key(value) if value else None


def _anchor_payload() -> dict:
    resource = files("modules.commercial_license").joinpath(ANCHOR_RESOURCE)
    try:
        payload = json.loads(resource.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("trusted vendor anchor resource is absent or invalid") from exc
    if not isinstance(payload, dict) or payload.get("schema") != ANCHOR_SCHEMA:
        raise ValueError("trusted vendor anchor resource has an unsupported schema")
    if payload.get("algorithm") != "Ed25519":
        raise ValueError("trusted vendor anchor has the wrong algorithm")
    if payload.get("purpose") != "buyer_entitlement":
        raise ValueError("trusted vendor anchor has the wrong purpose")
    if payload.get("environment") not in {"production", "synthetic_test"}:
        raise ValueError("trusted vendor anchor has an unknown environment")
    return payload


def trust_anchor_metadata() -> dict:
    """Expose non-key anchor identity and the mandatory buyer-facing label."""
    payload = _anchor_payload()
    return {
        key: payload.get(key)
        for key in (
            "schema",
            "state",
            "environment",
            "key_id",
            "algorithm",
            "purpose",
            "display_label",
        )
    }


def trusted_anchor_metadata() -> dict:
    """Compatibility alias for early C06 consumers."""
    return trust_anchor_metadata()


def trusted_vendor_public_key() -> bytes:
    """Return an artifact-pinned Ed25519 key or fail closed when unconfigured."""
    override = _source_test_override()
    if override is not None:
        return override
    payload = _anchor_payload()
    if payload.get("state") != "CONFIGURED":
        raise ValueError("trusted vendor public key is not configured in this artifact")
    if not payload.get("key_id"):
        raise ValueError("trusted vendor anchor key_id is absent")
    return _decode_public_key(payload.get("public_key_base64url"))
