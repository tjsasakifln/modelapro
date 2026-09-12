"""Actual C02 cost order contract; all inputs here are explicitly synthetic."""
import copy
import json

import pytest

from frontend.components.cost import build_cost_order
from modules.qualification_profile import resolve_profile
from tests.comercial.test_c06_security_routes import installation

pytestmark = pytest.mark.raw_local_auth


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


def test_http_cost_without_market_upload_and_saved_revision_match(installation):
    import time
    client, headers, _ = installation
    spec = synthetic_cost_order()
    response = client.post("/jobs", data={"request_json": json.dumps(spec)}, headers=headers)
    assert response.status_code == 202, response.text
    jid = response.json()["job_id"]
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        status = client.get(f"/jobs/{jid}", headers=headers).json()
        if status.get("state") in {"succeeded", "failed", "cancelled", "interrupted"}:
            break
        time.sleep(0.05)
    assert status["state"] == "succeeded", status
    result = client.get(f"/jobs/{jid}/result", headers=headers)
    assert result.status_code == 200, result.text
    snapshot = result.json()
    assert snapshot["value"]["point"] == pytest.approx(920)
    assert snapshot["provenance"]["cost_result"]["computable"] is True
    saved = client.post("/projects/COST-TEST/revisions", headers=headers, json={"job_id": jid})
    assert saved.status_code == 201, saved.text
    restored = client.get("/projects/COST-TEST", headers=headers)
    assert restored.status_code == 200, restored.text
    revision = restored.json()["revision"]
    assert revision["request_spec"]["cost_bom"] == spec["cost_bom"]
    assert revision["value"]["point"] == snapshot["value"]["point"]
    assert revision["request_spec"]["target_col"] == ""
    assert revision["request_spec"]["candidate_cols"] == []


def test_http_market_still_requires_sample_and_cost_rejects_disguised_sample(installation):
    from tests.c17_integration.helpers import request_spec
    client, headers, _ = installation
    missing = client.post("/jobs", headers=headers, data={"request_json": json.dumps(request_spec())})
    assert missing.status_code == 400, missing.text
    disguised = client.post("/jobs", headers=headers, data={"request_json": json.dumps(synthetic_cost_order())},
                             files={"file": ("fake-market.csv", b"area,value\n1,1\n")})
    assert disguised.status_code == 400, disguised.text
