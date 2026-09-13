"""C08-A01: PDF numbers match the MP/1 snapshot; no regression refit."""

from __future__ import annotations

from datetime import date

from modules.results_generator import (
    build_report_view,
    compose_report_html,
    format_snapshot_number,
    render_report,
)

from tests.c08_report.fixtures import (
    KNOWN_ADM_LOWER,
    KNOWN_ADM_UPPER,
    KNOWN_ARB_LOWER,
    KNOWN_ARB_UPPER,
    KNOWN_CODE_SHA,
    KNOWN_COEF_AREA,
    KNOWN_GENERATED_AT,
    KNOWN_INSPECTION_DATE,
    KNOWN_MEAN_CI80_LOWER,
    KNOWN_MEAN_CI80_UPPER,
    KNOWN_MODEL_ID,
    KNOWN_MODEL_REVISION,
    KNOWN_POINT,
    KNOWN_PRED_LOWER,
    KNOWN_PRED_UPPER,
    KNOWN_REFERENCE_DATE,
    KNOWN_UNIT,
    known_context,
    known_snapshot,
    pending_date_unit_snapshot,
)
from tests.c08_report.pdf_text import extract_pdf_text, parse_frozen_lines


def test_render_report_copies_snapshot_numbers_without_refitting(monkeypatch):
    import statsmodels.api as sm
    from modules.model_builder import ModelBuilder

    def _forbid_ols(*_args, **_kwargs):
        raise AssertionError("render_report must not fit OLS")

    def _forbid_build(*_args, **_kwargs):
        raise AssertionError("render_report must not call ModelBuilder.build_model")

    monkeypatch.setattr(sm, "OLS", _forbid_ols)
    monkeypatch.setattr(ModelBuilder, "build_model", _forbid_build)

    snapshot = known_snapshot()
    pdf = render_report(snapshot, known_context())
    assert pdf.startswith(b"%PDF")
    text = extract_pdf_text(pdf)
    frozen = parse_frozen_lines(text)

    assert frozen["MP1_POINT"] == format_snapshot_number(KNOWN_POINT)
    assert frozen["MP1_MEAN_CI80_LOWER"] == format_snapshot_number(KNOWN_MEAN_CI80_LOWER)
    assert frozen["MP1_MEAN_CI80_UPPER"] == format_snapshot_number(KNOWN_MEAN_CI80_UPPER)
    assert frozen["MP1_PRED_LOWER"] == format_snapshot_number(KNOWN_PRED_LOWER)
    assert frozen["MP1_PRED_UPPER"] == format_snapshot_number(KNOWN_PRED_UPPER)
    assert frozen["MP1_ARB_LOWER"] == format_snapshot_number(KNOWN_ARB_LOWER)
    assert frozen["MP1_ARB_UPPER"] == format_snapshot_number(KNOWN_ARB_UPPER)
    assert frozen["MP1_ADM_LOWER"] == format_snapshot_number(KNOWN_ADM_LOWER)
    assert frozen["MP1_ADM_UPPER"] == format_snapshot_number(KNOWN_ADM_UPPER)
    assert frozen["MP1_REFERENCE_DATE"] == KNOWN_REFERENCE_DATE
    assert frozen["MP1_INSPECTION_DATE"] == KNOWN_INSPECTION_DATE
    assert frozen["MP1_TARGET_UNIT"] == KNOWN_UNIT

    html = compose_report_html(snapshot, known_context())
    assert KNOWN_REFERENCE_DATE in text
    assert KNOWN_INSPECTION_DATE in text
    assert "BRL" in text
    assert "R$" in html
    assert "R$" in text
    assert "350.000,00" in html
    assert "350.000,00" in text
    assert KNOWN_MODEL_ID in text
    assert KNOWN_MODEL_REVISION in text
    assert KNOWN_CODE_SHA in text
    assert format_snapshot_number(KNOWN_COEF_AREA) in text
    assert "/home/" not in text
    assert KNOWN_GENERATED_AT in text
    assert "não recalcula regressão" in text.lower() or "nao recalcula regressao" in text.lower() or "não recalcula" in text


def test_missing_reference_date_and_unit_are_pending_not_invented():
    snapshot = pending_date_unit_snapshot()
    context = known_context()
    context = dict(context)
    context["inspection_date"] = None
    pdf = render_report(snapshot, context)
    text = extract_pdf_text(pdf)
    frozen = parse_frozen_lines(text)

    assert frozen["MP1_REFERENCE_DATE"] == "PENDENTE"
    assert frozen["MP1_INSPECTION_DATE"] == "PENDENTE"
    assert frozen["MP1_TARGET_UNIT"] == "PENDENTE"
    assert "data-base não informada" in text
    assert "unidade do valor-alvo não informada" in text
    today = date.today().isoformat()
    assert frozen["MP1_REFERENCE_DATE"] != today
    assert f"MP1_REFERENCE_DATE={today}" not in text
    assert "R$" not in text
    view = build_report_view(snapshot, context)
    assert view["unit_pending"] is True
    assert view["unit_is_brl"] is False
    assert view["reference_date"] is None


def test_confirmed_brl_m2_is_formatted_as_such():
    snapshot = known_snapshot()
    snapshot = dict(snapshot)
    snapshot["target"] = dict(snapshot["target"])
    snapshot["target"]["unit"] = "BRL/m2"
    snapshot["value"] = dict(snapshot["value"])
    snapshot["value"]["point"] = 3500.0
    html = compose_report_html(snapshot, known_context())
    pdf = render_report(snapshot, known_context())
    text = extract_pdf_text(pdf)
    frozen = parse_frozen_lines(text)
    assert frozen["MP1_TARGET_UNIT"] == "BRL/m2"
    assert "m²" in html or "BRL/m2" in html
    assert "R$" in html
    assert "/m²" in html
    assert "BRL/m2" in text or "m²" in text or "m2" in text
    assert "R$" in text or "3500" in text or "3.500,00" in text
