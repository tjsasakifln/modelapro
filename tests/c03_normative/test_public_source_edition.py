"""The public grant belongs to the personal source edition, never to a request."""
import sys

from modules.operacao_local.runtime import license_decision


def test_public_calculation_keeps_issuer_and_signature_independent(monkeypatch, tmp_path):
    monkeypatch.setenv("MODELA_LICENSE_PATH", str(tmp_path / "absent.json"))
    monkeypatch.setenv("MODELA_EDITION", "public")
    assert license_decision().permits("calculate")
    assert license_decision().permits("export")
    assert not license_decision().valid_signature
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert not license_decision().permits("calculate")
    monkeypatch.setattr(sys, "frozen", False)
    monkeypatch.delenv("MODELA_EDITION")
    assert not license_decision().permits("calculate")
