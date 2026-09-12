from __future__ import annotations

import base64
import hashlib
from copy import deepcopy

import numpy as np

from modules.decision_support import recommend_next_actions
from modules.report_presenter.qualification import (
    assess_document_state,
    report_content_fingerprint,
)
from modules.report_presenter.verifier import (
    extract_pdf_text,
    verify_report_consistency,
)
from modules.results_generator import build_report_view, render_report

from .fixtures import qualified_case


def test_a01_final_requires_qualified_state_and_real_review_event():
    snapshot, context = qualified_case()
    state = assess_document_state(snapshot, context)
    assert state["is_final"] is True
    pdf = render_report(snapshot, context)
    text = extract_pdf_text(pdf)
    assert "Laudo final" in text
    assert "professional-test-001" in text
    assert "TEST-RULE-01" in text
    assert verify_report_consistency(pdf, snapshot, context)["ok"] is True
    assert "REPORT_REQUIRED_CONTENT_MISSING" not in str(
        recommend_next_actions(snapshot)
    )

    pending = deepcopy(snapshot)
    pending["provenance"]["qualification_context"]["rule_results"][0]["status"] = (
        "unverified"
    )
    pending_state = assess_document_state(pending, context)
    assert pending_state["is_final"] is False
    pending_text = extract_pdf_text(render_report(pending, context))
    assert "emissão profissional bloqueada" in pending_text
    assert "QUALIFICATION_RULE_BLOCKING" in pending_text


def test_a01_review_is_bound_to_result_and_full_report_content():
    snapshot, context = qualified_case()
    event = snapshot["provenance"]["qualification_context"]["review_events"][0]
    event["decision"] = "signed"
    state = assess_document_state(snapshot, context)
    assert state["is_final"] is False
    assert any(
        item["code"] == "PROFESSIONAL_REVIEW_NOT_EVIDENCED"
        for item in state["blockers"]
    )

    snapshot, context = qualified_case()
    snapshot["provenance"]["qualification_context"]["review_events"][0].pop("version")
    state = assess_document_state(snapshot, context)
    assert state["is_final"] is False
    assert any(
        item["code"] == "PROFESSIONAL_REVIEW_NOT_EVIDENCED"
        for item in state["blockers"]
    )

    snapshot, context = qualified_case()
    snapshot["provenance"]["qualification_context"]["calculation_status"] = (
        "valid_not_released"
    )
    state = assess_document_state(snapshot, context)
    assert state["is_final"] is False
    assert any(
        item["code"] == "CALCULATION_NOT_RELEASEABLE" for item in state["blockers"]
    )

    snapshot, context = qualified_case()
    snapshot["provenance"]["qualification_context"].pop("result_fingerprint")
    state = assess_document_state(snapshot, context)
    assert state["is_final"] is False
    assert any(
        item["code"] == "RESULT_FINGERPRINT_MISSING" for item in state["blockers"]
    )

    snapshot, context = qualified_case()
    context["asset_identification"]["matricula"] = "MUTATED-AFTER-REVIEW"
    state = assess_document_state(snapshot, context)
    assert state["is_final"] is False
    assert any(
        item["code"] == "PROFESSIONAL_REVIEW_NOT_EVIDENCED"
        for item in state["blockers"]
    )


def test_a03_missing_or_placeholder_sample_rows_block_final_emission():
    snapshot, context = qualified_case()
    context.pop("used_rows")
    state = assess_document_state(snapshot, context)
    assert state["is_final"] is False
    assert any(
        item["code"] == "SAMPLE_ROW_MAP_INCOMPLETE" for item in state["blockers"]
    )

    snapshot, context = qualified_case()
    context["used_rows"][0]["source"] = ""
    state = assess_document_state(snapshot, context)
    assert state["is_final"] is False
    assert any(
        item["code"] == "SAMPLE_ROW_EVIDENCE_INCOMPLETE" for item in state["blockers"]
    )

    snapshot, context = qualified_case()
    context["excluded_rows"][0]["justification"] = ""
    snapshot["provenance"]["qualification_context"]["review_events"][0][
        "report_content_fingerprint"
    ] = report_content_fingerprint(snapshot, context)
    state = assess_document_state(snapshot, context)
    assert state["is_final"] is False
    assert any(
        item["code"] == "SAMPLE_ROW_EVIDENCE_INCOMPLETE" for item in state["blockers"]
    )


def test_a01_numpy_chart_series_are_fingerprinted_without_breaking_minuta():
    snapshot, context = qualified_case()
    context["fitted_values"] = np.asarray(context["fitted_values"])
    context["residuals"] = np.asarray(context["residuals"])
    state = assess_document_state(snapshot, context)
    assert state["is_final"] is True
    assert render_report(snapshot, context).startswith(b"%PDF")


def test_a02_numbers_profile_rules_and_each_interval_are_frozen():
    snapshot, context = qualified_case()
    pdf = render_report(snapshot, context)
    text = extract_pdf_text(pdf)
    for marker in (
        "MP1_POINT=350000",
        "MP1_MEAN_CI80_LOWER=320000",
        "MP1_PRED_LOWER=280000",
        "MP1_ARB_LOWER=297500",
        "MP1_ADM_LOWER=320000",
        "MPQUAL_PROFILE_ID=urban-market-regression",
        "MPQUAL_VALUE_BASIS=market_value",
        "MPQUAL_RELEASE_STATUS=ready_for_professional_signoff",
    ):
        assert marker in text
    mutated = text.replace("MP1_MEAN_CI80_LOWER=320000", "MP1_MEAN_CI80_LOWER=1")
    result = verify_report_consistency(pdf, snapshot, context, extracted_text=mutated)
    assert any(item["code"] == "MUTATED_INTERVAL" for item in result["findings"])

    coefficient_mutation = text.replace("1234.56789012345", "9999")
    result = verify_report_consistency(
        pdf, snapshot, context, extracted_text=coefficient_mutation
    )
    assert any(item["code"] == "INCOHERENT_EQUATION" for item in result["findings"])

    date_mutation = text.replace(
        "MP1_REFERENCE_DATE=2024-03-15", "MP1_REFERENCE_DATE=2099-12-31"
    )
    result = verify_report_consistency(
        pdf, snapshot, context, extracted_text=date_mutation
    )
    assert any(item["code"] == "MUTATED_DATE" for item in result["findings"])

    row_mutation = text.replace("200100", "999999")
    result = verify_report_consistency(
        pdf, snapshot, context, extracted_text=row_mutation
    )
    assert any(item["code"] == "MUTATED_SAMPLE_ROW" for item in result["findings"])


def test_a03_more_than_200_rows_are_integral_in_downloaded_pdf():
    snapshot, context = qualified_case(long=True)
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    context["documentary_files"] = [
        {
            "filename": "fachada-sintetica-autorizada.png",
            "type": "image/png",
            "bytes": image,
            "authorized_for_report": True,
        }
    ]
    assert len(snapshot["sample"]["used_row_ids"]) > 200
    view = build_report_view(snapshot, context)
    assert view["documentary_attachments"][0]["status"] == "embedded"
    pdf = render_report(snapshot, context)
    text = extract_pdf_text(pdf)
    ids = snapshot["sample"]["used_row_ids"] + snapshot["sample"]["excluded_row_ids"]
    assert all(str(row_id) in text for row_id in ids)
    for row in context["used_rows"] + context["excluded_rows"]:
        assert str(row["row_id"]) in text
        assert str(row.get("source") or "") in text
    assert "fachada-sintetica-autorizada.png" in text
    assert hashlib.sha256(image).hexdigest() in text
    changed_context = deepcopy(context)
    changed_context["used_rows"][0]["values"]["preco_brl"] = 1
    result = verify_report_consistency(pdf, snapshot, changed_context)
    assert any(item["code"] == "MUTATED_SAMPLE_ROW" for item in result["findings"])
