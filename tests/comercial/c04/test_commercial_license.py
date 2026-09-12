from datetime import date

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from modules.commercial_license import (
    LicenseError,
    install_license,
    load_license,
    make_signed_envelope,
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
