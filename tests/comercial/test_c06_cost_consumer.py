"""Actual C02 cost order contract; all inputs here are explicitly synthetic."""
import copy
import json

import pytest

from frontend.components.cost import build_cost_order
from modules.qualification_profile import resolve_profile


def synthetic_cost_order():
    bom = {
        "schema_version": "MP-COST-BOM/1", "reference_location": "TESTE",
        "reference_date": "2026-09-12", "currency": "BRL",
        "direct_cost": {"mode": "synthetic_budget", "source": {
            "reference": "orçamento TESTE", "reference_date": "2026-09-12",
            "location": "TESTE", "synthetic_test_only": True}},
        "items": [{"item_id": "estrutura", "description": "Estrutura TESTE", "category": "building_component",
                   "quantity": 10, "unit": "m2", "unit_cost": 100, "currency": "BRL",
                   "reference_date": "2026-09-12", "source": "item TESTE"}],
        "bdi": {"mode": "calculated", "rate": 0.15, "components": {"administracao": 0.1, "risco": 0.05},
                "formula": "additive", "source": "memória BDI TESTE"},
        "depreciation": {"mode": "technical_method", "rate": 0.2, "method": "método TESTE", "age": 10,
                         "useful_life": 50, "condition": "regular", "source": "vistoria TESTE"},
    }
    return build_cost_order(
        bom=bom, applicant="Solicitante TESTE", rights="Direitos TESTE", inspection_date="2026-09-12",
        inspection={"responsible": "Profissional TESTE"}, identity={"name": "Profissional TESTE"},
        evidence={"profile_evidence": {}, "professional_findings": {}}, minimum_grade=1, synthetic_test_only=True,
    )


def test_cost_ui_serializes_real_catalog_without_market_sample_or_attested_grade():
    spec = synthetic_cost_order()
    assert spec["target_col"] == ""
    assert spec["candidate_cols"] == []
    assert spec["roles"] == {}
    assert resolve_profile(spec["qualification_profile"])["resolved"] is True
    assert spec["synthetic_test_only"] is True
    assert spec["declared_documentary"]["item1_grade"] is None
    assert spec["declared_documentary"]["item3_grade"] is None
    assert "grade" not in spec["cost_bom"]["direct_cost"]
    assert spec["cost_bom"]["depreciation"]["rate"] == 0.2


def test_cost_input_changes_remain_in_reproducible_request():
    original = synthetic_cost_order()
    changed = copy.deepcopy(original)
    changed["cost_bom"]["items"][0]["unit_cost"] = 100.01
    assert json.dumps(original, sort_keys=True) != json.dumps(changed, sort_keys=True)


def test_cost_ui_refuses_unresolved_catalog(monkeypatch):
    import frontend.components.cost as consumer
    monkeypatch.setattr(consumer, "select_qualification_profile", lambda _: {"resolved": False})
    with pytest.raises(ValueError, match="não resolvido"):
        synthetic_cost_order()
