"""Offline commercial entitlement verification (MP-COM-LICENSE/1).

This verifies a vendor-signed entitlement only.  It is not a report signature
and does not decide technical or professional qualification.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping


class LicenseError(ValueError):
    pass


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _ed25519_public(key: bytes):
    # Lazy import keeps analytical installs usable until license verification.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    return Ed25519PublicKey.from_public_bytes(key)


@dataclass(frozen=True)
class LicenseDecision:
    valid_signature: bool
    expired: bool
    license_id: str | None
    rights: frozenset[str]
    reason: str | None = None

    def permits(self, right: str, *, evidence_exists: bool = False) -> bool:
        if right in {"read", "export"} and evidence_exists and self.valid_signature:
            return True
        return right in self.rights


def verify_license(envelope: Mapping[str, Any], public_key: bytes, *, today: date | None = None) -> LicenseDecision:
    """Verify an Ed25519 envelope and calculate current rights.

    Expected envelope: ``{'schema':'MP-COM-LICENSE/1','payload':'base64url JSON',
    'signature':'base64url'}``. Expiration only removes ``calculate``; evidence
    remains readable/exportable for a previously valid license.
    """
    try:
        if envelope.get("schema") != "MP-COM-LICENSE/1":
            raise LicenseError("unsupported license schema")
        payload = json.loads(_b64decode(str(envelope["payload"])).decode("utf-8"))
        if not isinstance(payload, dict):
            raise LicenseError("license payload must be an object")
        _ed25519_public(public_key).verify(_b64decode(str(envelope["signature"])), _canonical(payload))
        expires = date.fromisoformat(str(payload["expires_on"]))
        if not payload.get("license_id"):
            raise LicenseError("license_id is required")
        expired = expires < (today or date.today())
        granted = {str(x) for x in payload.get("rights", []) if str(x) in {"calculate", "read", "export"}}
        if expired:
            granted.discard("calculate")
        return LicenseDecision(True, expired, str(payload["license_id"]), frozenset(granted))
    except Exception as exc:
        # Cryptography's InvalidSignature intentionally has no import at module load.
        return LicenseDecision(False, False, None, frozenset(), f"license verification failed: {type(exc).__name__}")


def make_signed_envelope(payload: Mapping[str, Any], private_key: Any) -> dict[str, str]:
    """Test/release tooling helper; caller owns the legitimate signing key."""
    encoded = _canonical(payload)
    return {"schema": "MP-COM-LICENSE/1", "payload": base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("="),
            "signature": base64.urlsafe_b64encode(private_key.sign(encoded)).decode("ascii").rstrip("=")}


def install_license(
    envelope: Mapping[str, Any],
    public_key: bytes,
    destination: str | os.PathLike,
    *,
    today: date | None = None,
) -> LicenseDecision:
    """Verify and atomically install a small offline entitlement file.

    The vendor private key never enters the product. A valid but expired file
    may be retained because it still proves entitlement history and permits
    access to existing evidence; it does not permit a new calculation.
    """
    decision = verify_license(envelope, public_key, today=today)
    if not decision.valid_signature:
        raise LicenseError(decision.reason or "license signature is invalid")
    target = Path(destination).expanduser()
    if target.is_symlink():
        raise LicenseError("license destination must not be a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dict(envelope), sort_keys=True, separators=(",", ":"))
    if len(payload.encode("utf-8")) > 64 * 1024:
        raise LicenseError("license envelope exceeds 64 KiB")
    fd, temporary = tempfile.mkstemp(prefix=".modelapro-license-", dir=str(target.parent))
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        os.replace(temp_path, target)
    except Exception:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise
    return decision


def load_license(
    source: str | os.PathLike,
    public_key: bytes,
    *,
    today: date | None = None,
) -> LicenseDecision:
    """Load a bounded regular JSON file and verify it every time it is used."""
    path = Path(source).expanduser()
    if path.is_symlink() or not path.is_file():
        raise LicenseError("license source must be a regular file")
    if path.stat().st_size > 64 * 1024:
        raise LicenseError("license envelope exceeds 64 KiB")
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LicenseError("license source is not valid UTF-8 JSON") from exc
    if not isinstance(envelope, Mapping):
        raise LicenseError("license envelope must be an object")
    return verify_license(envelope, public_key, today=today)
