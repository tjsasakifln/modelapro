"""P01-A03: historical grade aliases, conflict, pending is not met."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.api import app, request_spec_from_upload_form
from frontend.components.forms import build_request_spec
from modules.nbr14653_validation import assess_normative
from modules.optimal_combination import classify_admissibility
from modules.pro_workflow.grade_policy import CANONICAL_GRADE_KEY, classify_grade_requirement_status
from modules.pro_workflow.workflow_context import build_workflow_context
from modules.result_contract import RequestSpecError, validate_request_spec
from tests.pro_workflow.p01.conftest import documented_request_spec


def _base_spec():
    return documented_request_spec()


def test_p01_a03_equivalent_spellings_same_canonical_and_ranking():
    variants = []
    # canonical
    a = _base_spec()
    a["search_policy"][CANONICAL_GRADE_KEY] = 2
    variants.append(("canonical", a))
    # search_policy.target_degree (legacy / C10 fixture)
    b = _base_spec()
    b["search_policy"].pop(CANONICAL_GRADE_KEY, None)
    b["search_policy"]["target_degree"] = 2
    variants.append(("target_degree", b))
    # min_fundamentacao_grade on evaluation_policy (ranking adapter)
    c = _base_spec()
    c["search_policy"].pop(CANONICAL_GRADE_KEY, None)
    c["evaluation_policy"]["min_fundamentacao_grade"] = 2
    variants.append(("min_fundamentacao_grade", c))
    # UI-assembled payload
    ui = build_request_spec(
        target_col="preco",
        candidate_cols=["area", "bairro"],
        roles={"preco": "target", "area": "predictor", "bairro": "predictor", "id": "identifier"},
        units={"area": "m2", "preco": "BRL"},
        import_options={"locale": "en-US", "delimiter": ";", "encoding": "utf-8"},
        reference_date="2024-06-01",
        inspection_date="2024-06-15",
        target_unit="BRL",
        applicant="SYNTHETIC P01",
        purpose="alias",
        minimum_fundamentacao_grade=2,
    )
    variants.append(("ui_builder", ui))
    # legacy upload adapter
    legacy = request_spec_from_upload_form(
        degree=2,
        target_col="preco",
        candidate_cols=["area", "bairro"],
        solicitante="SYNTHETIC P01",
        finalidade="alias",
        grau_item1=2,
        grau_item3=2,
    )
    variants.append(("legacy_adapter", legacy))

    canonical_values = []
    ranking_labels = []
    for _name, spec in variants:
        validated = validate_request_spec(spec)
        grade = validated["search_policy"][CANONICAL_GRADE_KEY]
        canonical_values.append(grade)
        record = {
            "status": "fitted",
            "metrics": {"original_rmse": 1.0, "grau_fundamentacao": 2},
            "coefficients": {"const": 1.0, "area": 1.0},
        }
        adm = classify_admissibility(record, validated["evaluation_policy"])
        ranking_labels.append(adm["label"])
    assert set(canonical_values) == {2}
    assert set(ranking_labels) == {"admissible"}


def test_p01_a03_conflicting_aliases_are_structured_conflict():
    spec = _base_spec()
    spec["search_policy"][CANONICAL_GRADE_KEY] = 2
    spec["search_policy"]["target_degree"] = 3
    with pytest.raises(RequestSpecError) as exc:
        validate_request_spec(spec)
    codes = [i.get("code") for i in exc.value.issues]
    assert "GRADE_ALIAS_CONFLICT" in codes


def test_p01_a03_http_conflict_is_4xx(isolated_p01_runtime):
    spec = _base_spec()
    spec["search_policy"][CANONICAL_GRADE_KEY] = 1
    spec["search_policy"]["target_degree"] = 3
    client = TestClient(app)
    files = {"file": ("m.csv", b"id;area;preco\n1;10;100\n", "text/csv")}
    data = {"request_json": json.dumps(spec)}
    resp = client.post("/jobs", files=files, data=data)
    assert resp.status_code == 400, resp.text
    body = resp.json()
    detail = body.get("detail") or body
    issues = detail.get("issues") or body.get("issues") or []
    codes = [i.get("code") for i in issues]
    assert "GRADE_ALIAS_CONFLICT" in codes


def test_p01_a03_grade_3_requested_but_documentary_pending_is_not_met():
    spec = _base_spec()
    spec["search_policy"][CANONICAL_GRADE_KEY] = 3
    validated = validate_request_spec(spec)
    # C03: pending items → grade None. Producer must not call this met.
    context = {
        "n": 36,
        "k": 2,
        "intercept": True,
        "axes": [],
        "documentary": {"item1_grade": None, "item3_grade": None, "status": "pending"},
        "pvalues": {"area": 0.01},
        "f_pvalue": 0.001,
        "value": {"point": 100.0, "mean_ci80": {"lower": 90.0, "upper": 110.0}},
        "central_estimate": 100.0,
        "amplitude_pct": 20.0,
        "sample": {"n": 36, "k": 2},
    }
    normative = assess_normative(context)
    fund = normative.get("fundamentacao") or {}
    status = classify_grade_requirement_status(
        requested=validated["search_policy"][CANONICAL_GRADE_KEY],
        fundamentacao=fund,
        documentary=normative.get("documentary") or context["documentary"],
        verification_status=normative.get("verification_status"),
    )
    assert status != "met"
    assert status in {"pending", "not_met"}
    wf = build_workflow_context(
        request_spec=validated,
        validation={"fundamentacao": fund, "documentary": context["documentary"]},
    )
    assert wf["requested_minimum_grade"] == 3
    assert wf["grade_requirement_status"] != "met"
    # Ranking: pending/null grade does not score as admissible.
    record = {
        "status": "fitted",
        "metrics": {"original_rmse": 1.0, "grau_fundamentacao": fund.get("grade")},
        "coefficients": {"const": 1.0},
    }
    adm = classify_admissibility(record, validated["evaluation_policy"])
    assert adm["label"] == "exploratory"
    assert "min_fundamentacao_grade_not_met" in (adm.get("reasons") or [])
