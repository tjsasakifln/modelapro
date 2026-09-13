"""C14-A01: in-domain vs out-of-domain subjects keep independent grades."""

from __future__ import annotations

from modules.valuation_batch import (
    ELIGIBLE,
    STATUS_SUCCEEDED,
    STATUS_UNSUPPORTED,
    UNSUPPORTED,
    evaluate_batch,
)

from .conftest import c03_documentary, expected_point, make_frozen_project, make_request_spec, make_subject


def test_in_and_out_of_domain_keep_independent_classifications():
    frozen = make_frozen_project()
    spec = make_request_spec()
    inside = make_subject(
        "s-in",
        area=100.0,
        bairro="Centro",
        documentary_items=[{"id": "doc-in", "label": "matricula-A", "status": "declared"}],
        documentary=c03_documentary("s-in"),
    )
    outside = make_subject(
        "s-out",
        area=400.0,
        bairro="Centro",
        documentary_items=[{"id": "doc-out", "label": "matricula-B", "status": "declared"}],
        documentary=c03_documentary("s-out"),
    )

    result = evaluate_batch(frozen, [inside, outside], spec)
    items = {item["subject_id"]: item for item in result["items"]}

    assert set(items) == {"s-in", "s-out"}
    assert result["summary"]["total"] == 2
    assert result["summary"]["succeeded"] == 1
    assert result["summary"]["unsupported"] == 1
    assert result["summary"]["failed"] == 0

    inn = items["s-in"]
    out = items["s-out"]

    assert inn["status"] == STATUS_SUCCEEDED
    assert inn["assessment"]["model_eligibility"]["status"] == ELIGIBLE
    assert inn["value"]["point"] == expected_point(100.0, "Centro")
    assert inn["unit"] == "BRL"
    in_grade = inn["assessment"]["normative"]["fundamentacao"]["grade"]
    in_prec = inn["assessment"]["normative"]["precisao"]["grade"]
    assert in_grade is not None

    assert out["status"] == STATUS_UNSUPPORTED
    elig = out["assessment"]["model_eligibility"]
    assert elig["status"] == UNSUPPORTED
    assert "requires_individual_analysis" in elig["reasons"]
    assert "out_of_domain" in elig["reasons"]
    assert out["value"]["point"] is None
    assert out["value"]["mean_ci80"] is None
    # Forced zero is forbidden.
    assert out["value"]["point"] != 0

    out_grade = out["assessment"]["normative"]["fundamentacao"]["grade"]
    out_prec = out["assessment"]["normative"]["precisao"]["grade"]
    assert out_grade != in_grade
    # Out-of-domain item 4 is independently 0, so overall grade is not inherited.
    item4_out = [i for i in out["assessment"]["normative"]["fundamentacao"]["items"] if i["item"] == 4][0]
    item4_in = [i for i in inn["assessment"]["normative"]["fundamentacao"]["items"] if i["item"] == 4][0]
    assert item4_in["grade"] == 3
    assert item4_out["grade"] == 0
    assert out_prec != in_prec or out["assessment"]["normative"]["precisao"]["status"] == "not_computed"

    docs_in = inn["assessment"]["normative"]["documentary"]["items"]
    docs_out = out["assessment"]["normative"]["documentary"]["items"]
    assert docs_in == [{"id": "doc-in", "label": "matricula-A", "status": "declared"}]
    assert docs_out == [{"id": "doc-out", "label": "matricula-B", "status": "declared"}]
    assert docs_in != docs_out


def test_subject_specific_model_is_not_silent_population_reuse():
    frozen = make_frozen_project(
        model_scope="subject_specific",
        subject_constraints={"selection_subject_id": "s-original", "bound_variables": {"area": {"min": 90, "max": 110}}},
    )
    spec = make_request_spec()
    original = make_subject("s-original", area=100.0, bairro="Centro")
    other = make_subject("s-other", area=100.0, bairro="Centro")

    result = evaluate_batch(frozen, [original, other], spec)
    items = {item["subject_id"]: item for item in result["items"]}
    assert items["s-original"]["status"] == STATUS_SUCCEEDED
    assert items["s-other"]["status"] == STATUS_UNSUPPORTED
    reasons = items["s-other"]["assessment"]["model_eligibility"]["reasons"]
    assert "requires_individual_analysis" in reasons
    assert "subject_specific_model_not_reusable" in reasons
    assert items["s-other"]["value"]["point"] is None
    assert items["s-other"]["assessment"]["normative"]["documentary"]["subject_id"] == "s-other"


def test_eligible_is_not_issuance_authorization():
    frozen = make_frozen_project()
    spec = make_request_spec()
    subject = make_subject("s1", area=90.0, bairro="Sul")
    result = evaluate_batch(frozen, [subject], spec)
    item = result["items"][0]
    assert item["assessment"]["model_eligibility"]["status"] == ELIGIBLE
    issuance = (item.get("validation") or {}).get("issuance")
    assert issuance in (None, {}) or issuance.get("status") != "ready_for_professional_review"
    assert "laudo aprovado" not in str(item).lower()
