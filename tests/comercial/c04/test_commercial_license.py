import base64
from datetime import date

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from modules.commercial_license import (
    LicenseError,
    install_license,
    load_license,
    make_signed_envelope,
    trust_anchor_metadata,
    trusted_vendor_public_key,
    verify_license,
)


def _key_bytes(key):
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def test_valid_license_grants_calculation_and_evidence_access():
    key = Ed25519PrivateKey.generate()
    envelope = make_signed_envelope({"license_id": "LIC-1", "expires_on": "2030-01-01",
                                     "rights": ["calculate", "read", "export"]}, key)
    decision = verify_license(envelope, _key_bytes(key), today=date(2029, 1, 1))
    assert decision.valid_signature and decision.permits("calculate")
    assert decision.permits("export", evidence_exists=True)


def test_expiry_never_locks_existing_evidence():
    key = Ed25519PrivateKey.generate()
    envelope = make_signed_envelope({"license_id": "LIC-1", "expires_on": "2020-01-01", "rights": ["calculate"]}, key)
    decision = verify_license(envelope, _key_bytes(key), today=date(2026, 1, 1))
    assert decision.valid_signature and decision.expired
    assert not decision.permits("calculate")
    assert decision.permits("read", evidence_exists=True)
    assert decision.permits("export", evidence_exists=True)


def test_tampered_entitlement_fails_closed():
    key = Ed25519PrivateKey.generate()
    envelope = make_signed_envelope({"license_id": "LIC-1", "expires_on": "2030-01-01", "rights": ["calculate"]}, key)
    envelope["signature"] = envelope["signature"][:-2] + "aa"
    decision = verify_license(envelope, _key_bytes(key))
    assert not decision.valid_signature
    assert not decision.permits("calculate")


def test_offline_install_is_atomic_and_reverified(tmp_path):
    key = Ed25519PrivateKey.generate()
    public = _key_bytes(key)
    envelope = make_signed_envelope(
        {
            "license_id": "LIC-OFFLINE-1",
            "expires_on": "2030-01-01",
            "rights": ["calculate", "read", "export"],
        },
        key,
    )
    destination = tmp_path / "private-profile" / "license.json"
    decision = install_license(envelope, public, destination, today=date(2029, 1, 1))
    assert decision.permits("calculate")
    assert destination.is_file()
    assert load_license(destination, public, today=date(2031, 1, 1)).permits(
        "export", evidence_exists=True
    )

    payload = __import__("json").loads(destination.read_text(encoding="utf-8"))
    payload["signature"] = payload["signature"][:-2] + "aa"
    destination.write_text(__import__("json").dumps(payload), encoding="utf-8")
    assert not load_license(destination, public).valid_signature


def test_offline_install_refuses_invalid_file(tmp_path):
    key = Ed25519PrivateKey.generate()
    with pytest.raises(LicenseError):
        install_license(
            {"schema": "MP-COM-LICENSE/1", "payload": "bad", "signature": "bad"},
            _key_bytes(key),
            tmp_path / "license.json",
        )


def test_runtime_environment_cannot_replace_unconfigured_vendor_anchor(monkeypatch):
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv(
        "MODELA_LICENSE_PUBLIC_KEY",
        base64.urlsafe_b64encode(_key_bytes(key)).decode(),
    )
    monkeypatch.delenv("MODELA_TEST_CONTEXT", raising=False)
    with pytest.raises(ValueError, match="not configured"):
        trusted_vendor_public_key()


def test_unconfigured_anchor_exposes_only_buyer_facing_identity():
    metadata = trust_anchor_metadata()
    assert metadata == {
        "schema": "MP-COM-TRUSTED-VENDOR/1",
        "state": "UNCONFIGURED",
        "environment": "production",
        "key_id": None,
        "algorithm": "Ed25519",
        "purpose": "buyer_entitlement",
        "display_label": "CHAVE DO TITULAR NÃO CONFIGURADA",
    }
    assert "public_key_base64url" not in metadata


def test_source_test_context_can_supply_legacy_fixture_anchor(monkeypatch):
    key = Ed25519PrivateKey.generate()
    encoded = base64.urlsafe_b64encode(_key_bytes(key)).decode().rstrip("=")
    monkeypatch.setenv("MODELA_TEST_CONTEXT", "1")
    monkeypatch.setenv("MODELA_LICENSE_PUBLIC_KEY", encoded)
    assert trusted_vendor_public_key() == _key_bytes(key)


def test_frozen_runtime_never_accepts_test_environment_override(monkeypatch):
    key = Ed25519PrivateKey.generate()
    encoded = base64.urlsafe_b64encode(_key_bytes(key)).decode().rstrip("=")
    monkeypatch.setenv("MODELA_TEST_CONTEXT", "1")
    monkeypatch.setenv("MODELA_LICENSE_PUBLIC_KEY", encoded)
    monkeypatch.setattr(__import__("sys"), "frozen", True, raising=False)
    with pytest.raises(ValueError, match="not configured"):
        trusted_vendor_public_key()
