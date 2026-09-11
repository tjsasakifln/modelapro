"""P02-A05/A02 presenter: intervalos, workflow_context, PDF vs cálculo, next_actions."""

from frontend.components.layout import (
    present_artifacts,
    present_job_status,
    present_snapshot,
    snapshot_contains_forbidden_norma_banner,
)
from frontend.components.workflow import (
    alternatives_comparable,
    group_issues,
    next_actions_or_navigation_fallback,
    present_batch_items,
    present_delivery_state,
    present_subject_presence,
    viewport_flags,
)
from tests.c09_frontend.fixtures import SNAPSHOT_CLASSIFIED, SNAPSHOT_NOT_COMPUTED


def test_intervals_keep_distinct_labels_and_arbitration_is_not_confidence():
    view = present_snapshot(SNAPSHOT_CLASSIFIED, viewport_width=1366)
    labels = {item["key"]: item["label"] for item in view["intervals"]}
    assert labels["mean_ci80"] == "Intervalo de confiança da média (80%)"
    assert labels["prediction_interval"] == "Intervalo de predição"
    assert labels["arbitration_interval"] == "Intervalo de arbitragem"
    arb = next(item for item in view["intervals"] if item["key"] == "arbitration_interval")
    assert arb["not_confidence"] is True
    assert "confiança" not in (arb.get("note") or "").replace("não é intervalo de confiança", "")
    assert "confiança" in labels["mean_ci80"]
    assert "confiança" not in labels["arbitration_interval"]
    first_keys = {item["key"] for item in view["first_contact_intervals"]}
    assert first_keys == {"mean_ci80", "prediction_interval"}


def test_workflow_context_absent_is_not_imovel_ausente():
    view = present_snapshot(SNAPSHOT_CLASSIFIED)
    presence = view["subject_presence"]
    assert presence["extension_available"] is False
    assert presence["imovel_ausente"] is False
    assert presence["false_absent_alert"] is False
    assert view["false_imovel_ausente"] is False
    assert "não prova" in presence["label"].lower() or "nao prova" in presence["label"].lower()


def test_workflow_context_confirming_subject_does_not_raise_absent_alert():
    snap = dict(SNAPSHOT_CLASSIFIED)
    snap["provenance"] = {
        "workflow_context": {
            "schema_version": "MP-PRO/1",
            "subject_raw": {"area": "73,5", "bairro": "Centro"},
            "requested_minimum_grade": 2,
            "grade_requirement_status": "met",
            "selection_scope": "subject_specific",
            "selection_conditioned_on_subject": True,
            "limitation_codes": ["exploratory"],
        }
    }
    view = present_snapshot(snap)
    presence = present_subject_presence(snap)
    assert presence["extension_available"] is True
    assert presence["subject_confirmed"] is True
    assert presence["imovel_ausente"] is False
    assert presence["false_absent_alert"] is False
    assert view["false_imovel_ausente"] is False
    assert "confirmado" in presence["label"].lower()


def test_next_actions_preferred_over_navigation_fallback():
    view = present_snapshot(SNAPSHOT_NOT_COMPUTED)
    assert view["next_actions"]
    assert view["next_actions_source"] == "next_actions"
    empty = next_actions_or_navigation_fallback(None, has_preview=False, has_subject=False, has_unit=False, has_reference_date=False)
    assert empty["fallback"] is True
    assert any(item["code"] == "nav_preview" for item in empty["actions"])


def test_grouped_issues_preserve_severity_affected_and_origin():
    issues = [
        {"code": "x", "severity": "warning", "origin": "c10", "message": "repetido", "affected_ids": ["a"]},
        {"code": "x", "severity": "warning", "origin": "c10", "message": "repetido", "affected_ids": ["b"]},
        {"code": "y", "severity": "error", "origin": "c01", "message": "outro", "affected_ids": ["c"]},
    ]
    grouped = group_issues(issues)
    repeated = next(item for item in grouped if item["code"] == "x")
    assert repeated["count"] == 2
    assert repeated["severity"] == "warning"
    assert repeated["origin"] == "c10"
    assert set(repeated["affected_ids"]) == {"a", "b"}
    view = present_snapshot({**SNAPSHOT_CLASSIFIED, "issues": issues})
    assert view["grouped_issues"][0]["count"] == 2


def test_pdf_failed_keeps_calculation_and_is_not_concluido():
    artifacts = present_artifacts({
        "report.pdf": {"state": "failed", "error": {"message": "PDF falhou"}},
        "frozen_project.json": {"state": "ready"},
    })
    job = present_job_status({"job_id": "job-1", "state": "succeeded", "result_available": True})
    delivery = present_delivery_state(job, artifacts)
    assert artifacts["pdf_failed"] is True
    assert artifacts["offer_calculation_download"] is True
    assert delivery["calculation_ready"] is True
    assert delivery["pdf_failed"] is True
    assert delivery["labeled_concluido"] is False
    assert "concluído" not in delivery["headline"].lower()
    assert "cálculo" in delivery["headline"].lower() or "calculo" in delivery["headline"].lower()
    assert job["state_label"] != "concluído"
    assert "Confiança" not in job["state_label"]


def test_alternatives_require_compatible_unit_date_estimand_and_are_read_only():
    current = {
        "target": {"unit": "BRL", "estimand": "valor de mercado"},
        "reference_date": "2024-01-15",
        "sample": {"used": 8},
    }
    ok = alternatives_comparable(current, {"target": {"unit": "BRL", "estimand": "valor de mercado"}, "reference_date": "2024-01-15", "sample": {"used": 8}})
    assert ok["comparable"] is True
    assert ok["may_adopt_in_frontend"] is False
    assert ok["may_average_models"] is False
    bad = alternatives_comparable(current, {"unit": "BRL-m2", "estimand": "valor de mercado", "reference_date": "2024-01-15"})
    assert bad["comparable"] is False
    assert "unidade" in bad["reasons"][0]


def test_viewports_keep_value_readable():
    wide = present_snapshot(SNAPSHOT_CLASSIFIED, viewport_width=1366)
    narrow = present_snapshot(SNAPSHOT_CLASSIFIED, viewport_width=360)
    assert wide["compact"] is False
    assert narrow["compact"] is True
    assert wide["value_block"]["point"] == narrow["value_block"]["point"]
    assert narrow["warnings_visible"] is True
    assert viewport_flags(1366)["desktop_technical"] is True
    assert viewport_flags(480)["narrow_consult"] is True
    assert snapshot_contains_forbidden_norma_banner(wide) is False


def test_batch_items_map_to_valido_nao_suportado_pendente():
    rows = present_batch_items({
        "items": [
            {"subject_id": "s1", "status": "succeeded", "value": {"point": 100.0}},
            {"subject_id": "s2", "status": "unsupported", "model_eligibility": {"status": "unsupported"}},
            {"subject_id": "s3", "status": "pending"},
        ]
    })
    by_id = {row["subject_id"]: row["ui_status"] for row in rows}
    assert by_id["s1"] == "valido"
    assert by_id["s2"] == "nao_suportado"
    assert by_id["s3"] == "pendente"
    assert all(row["recomputed_in_browser"] is False for row in rows)
