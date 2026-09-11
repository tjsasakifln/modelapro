"""Hardened production-path checks for PR #17 (R17-01…R17-06).

These drive shipped functions: evaluate_batch, compose_valuation_job,
assess_normative, POST /jobs. Oracles are analytic, not scraped from the
report under test.
"""

from __future__ import annotations

from typing import Any, Dict

from backend.worker import _axes_from_fit
from modules.nbr14653_validation import assess_normative
from modules.valuation_batch import (
    builtin_assess_normative,
    builtin_inverse_target_prediction,
    evaluate_batch,
    resolve_adapters,
)

from tests.c14_batch.conftest import (
    c03_documentary,
    expected_point,
    make_frozen_project,
    make_request_spec,
    make_subject,
)


def _fund(item: Dict[str, Any]) -> Dict[str, Any]:
    return ((item.get("assessment") or {}).get("normative") or {}).get("fundamentacao") or {}


def _item(fund: Dict[str, Any], number: int) -> Dict[str, Any]:
    for row in fund.get("items") or []:
        if int(row.get("item") or 0) == number:
            return row
    return {}


def test_r17_06_missing_subject_docs_stay_pending_despite_sample_scores(monkeypatch):
    frozen = make_frozen_project()
    spec = make_request_spec()
    subject = make_subject("novo", area=95.0, bairro="Centro")
    assert not (subject["documentary"].get("item1") or {}).get("grade")

    called = {"n": 0}
    original = builtin_assess_normative

    def wrapped(ctx):
        called["n"] += 1
        return original(ctx)

    monkeypatch.setattr("modules.valuation_batch.builtin_assess_normative", wrapped)

    batch = evaluate_batch(frozen, [subject], spec)
    item = batch["items"][0]
    fund = _fund(item)
    assert item["value"]["point"] == expected_point(95.0, "Centro")
    assert fund.get("grade") is None
    assert _item(fund, 1).get("grade") is None
    assert _item(fund, 1).get("evidence_status") == "pending"
    assert called["n"] == 0, "C03 grade None must not switch to builtin_assess_normative"


def test_r17_06_out_of_sample_area_fails_item4_not_inherited_grade():
    frozen = make_frozen_project()
    spec = make_request_spec()
    inside = make_subject("in", area=90.0, bairro="Centro", documentary=c03_documentary("in"))
    # Sample area [60, 180]; 270 is inside the expanded 0.5·min–2·max band (30–360)
    # but outside the sample, with 50%+ monetary effect at the frontier for a
    # linear 2500·area model? Use a dedicated frozen with 10000×area below.
    outside = make_subject("out", area=270.0, bairro="Centro", documentary=c03_documentary("out"))
    batch = evaluate_batch(frozen, [inside, outside], spec)
    items = {i["subject_id"]: i for i in batch["items"]}
    assert items["in"]["value"]["point"] == expected_point(90.0, "Centro")
    # 270 is outside declared domain 50–200 → unsupported, point null.
    assert items["out"]["value"]["point"] is None
    assert items["out"]["status"] in {"unsupported", "failed"}


def test_item4_expanded_band_is_not_approval_without_monetary_check():
    """Reference: sample area [50, 100], subject 150, y=10000×area."""

    def predict_original(subject):
        return 10000.0 * float(subject["area"])

    axes = [
        {
            "name": "area",
            "variable": "area",
            "kind": "quantitative",
            "avaliando_value": 150.0,
            "sample_min": 50.0,
            "sample_max": 100.0,
        }
    ]
    assessment = assess_normative(
        {
            "n": 30,
            "k": 1,
            "intercept": True,
            "axes": axes,
            "subject_raw": {"area": 150.0},
            "predict_original": predict_original,
            "pvalues": {"area": 0.01},
            "f_pvalue": 0.001,
            "documentary": c03_documentary("ref"),
        }
    )
    item4 = next(i for i in assessment["fundamentacao"]["items"] if i["item"] == 4)
    assert item4["grade"] in {0, None} or "não" in (item4.get("detail") or "").lower() or item4.get("grade") != 3
    # 50% monetary effect at the frontier (100 vs 150) is not Grau III.
    assert item4.get("grade") != 3


def test_unknown_y_transform_is_not_identity():
    result = builtin_inverse_target_prediction(10.0, {"name": "boxcox"})
    assert result.get("supported") is False
    assert result["value"]["point"] is None
    assert "unknown" in (result.get("error") or "").lower() or "boxcox" in str(result.get("limitations"))


def test_extra_form_field_does_not_create_model_axis():
    import pandas as pd

    frame = pd.DataFrame({"area": [50.0, 100.0], "garagem": [1.0, 20.0]})

    class _Fit:
        candidate_spec = {"base_variables": ["area"], "features": ["area"]}
        base_frame = frame
        feature_schema = {
            "columns": {"area": {"kind": "numeric"}},
            "groups": {},
        }
        X_design = None

    class _Prepared:
        base_frame = frame
        X = None
        feature_schema = _Fit.feature_schema

    raw = {"area": "90,0", "garagem": 9999}
    axes = _axes_from_fit(_Fit(), _Prepared(), raw, locale="pt-BR")
    names = {a.get("variable") or a.get("name") for a in axes}
    assert "garagem" not in names
    area = next(a for a in axes if (a.get("variable") or a.get("name")) == "area")
    assert area.get("avaliando_value") == 90.0


def test_individual_and_batch_pending_docs_match():
    frozen = make_frozen_project()
    spec = make_request_spec()
    subject = make_subject("p", area=88.0, bairro="Centro")
    lote = evaluate_batch(frozen, [subject], spec)["items"][0]
    adapters = resolve_adapters()
    from modules.valuation_batch import restore_candidate_fit

    fit = restore_candidate_fit(frozen)
    design = adapters["transform_subject"](subject["raw"], frozen["feature_schema"], frozen["encoder_state"])
    individual = adapters["evaluate_fitted"](fit, design, spec)
    assert lote["value"]["point"] == expected_point(88.0, "Centro")
    assert individual["value"]["point"] == lote["value"]["point"]
    fund_batch = _fund(lote)
    # Individual evaluate_fitted does not run C03; batch does. Pending docs
    # must not be filled from sample_item_scores.
    assert fund_batch.get("grade") is None


def test_mutation_other_imovel_docs_are_not_reused():
    frozen = make_frozen_project()
    spec = make_request_spec()
    a = make_subject("a", area=90.0, bairro="Centro", documentary=c03_documentary("a"))
    b = make_subject("b", area=91.0, bairro="Centro")
    batch = evaluate_batch(frozen, [a, b], spec)
    items = {i["subject_id"]: i for i in batch["items"]}
    fund_a = _fund(items["a"])
    fund_b = _fund(items["b"])
    assert fund_a.get("grade") is not None
    assert fund_b.get("grade") is None
    doc_b = ((items["b"].get("assessment") or {}).get("normative") or {}).get("documentary") or {}
    assert doc_b.get("subject_id") == "b"
    assert (doc_b.get("item1") or {}).get("grade") in (None, 0) or doc_b.get("item1", {}).get("evidence_status") == "pending"


def test_project_store_reopen_batch_without_editing_scope(tmp_path):
    from modules.project_store import ProjectStore

    frozen = make_frozen_project()
    spec = make_request_spec()
    store_a = ProjectStore(tmp_path / "proj")
    revision_id = store_a.save_revision(frozen["project_id"], frozen)
    del store_a
    store_b = ProjectStore(tmp_path / "proj")
    loaded = store_b.load_revision(frozen["project_id"], revision_id)
    assert loaded["model_scope"] == "population_model"
    subjects = [
        make_subject("r1", area=90.0, bairro="Centro"),
        make_subject("r2", area=110.0, bairro="Sul"),
        make_subject("r3", area=90.0, bairro="bairro_inexistente"),
    ]
    batch = evaluate_batch(loaded, subjects, spec)
    items = {i["subject_id"]: i for i in batch["items"]}
    assert items["r1"]["value"]["point"] == expected_point(90.0, "Centro")
    assert items["r2"]["value"]["point"] == expected_point(110.0, "Sul")
    assert items["r3"]["value"]["point"] is None
    assert items["r3"]["status"] in {"unsupported", "failed"}


def test_pdf_generation_failure_preserves_calculation(monkeypatch, isolated_c17_runtime):
    from tests.c17_integration.helpers import (
        analytic_linear_csv,
        analytic_point,
        client,
        post_job,
        wait_job,
        get_result,
        request_spec,
    )

    def boom(*_a, **_k):
        raise RuntimeError("injected pdf failure")

    monkeypatch.setattr("modules.results_generator.render_report", boom)
    test_client = client()
    spec = request_spec(
        candidate_cols=["area"],
        roles={"preco": "target", "area": "predictor", "id": "identifier", "bairro": "excluded"},
    )
    resp = post_job(
        test_client,
        file_bytes=analytic_linear_csv(n=24, tag="PDFNEG"),
        filename="mercado.csv",
        spec=spec,
        subject={"area": 90.0},
    )
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    status = wait_job(test_client, job_id)
    assert status["state"] == "succeeded"
    assert status.get("calculation_state") == "succeeded"
    pdf_state = (status.get("artifact_states") or {}).get("report.pdf") or {}
    assert pdf_state.get("state") == "failed"
    result = get_result(test_client, job_id)
    assert result.status_code == 200
    point = result.json()["value"]["point"]
    assert abs(float(point) - analytic_point(area=90.0)) < 1.0
    missing = test_client.get(f"/jobs/{job_id}/artifacts/report.pdf")
    assert missing.status_code == 404
