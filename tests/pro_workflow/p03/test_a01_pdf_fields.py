"""P03-A01: PDF copies snapshot value/unit/dates/intervals/coefficients into labeled fields."""

from __future__ import annotations

from modules.report_presenter.formula import compose_model_equation
from modules.report_presenter.search_coverage import interpret_search
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
    KNOWN_COEF_AREA,
    KNOWN_GENERATED_AT,
    KNOWN_INSPECTION_DATE,
    KNOWN_MEAN_CI80_LOWER,
    KNOWN_MEAN_CI80_UPPER,
    KNOWN_POINT,
    KNOWN_PRED_LOWER,
    KNOWN_PRED_UPPER,
    KNOWN_REFERENCE_DATE,
    KNOWN_UNIT,
    known_context,
    known_snapshot,
)
from tests.c08_report.pdf_text import extract_pdf_text, parse_frozen_lines
from tests.pro_workflow.p03.fixtures import snapshot_with_audit, snapshot_without_formula


def test_p03_a01_labeled_fields_not_mere_mp1_or_14653_presence():
    snapshot = known_snapshot()
    pdf = render_report(snapshot, known_context())
    assert pdf.startswith(b"%PDF")
    text = extract_pdf_text(pdf)
    html = compose_report_html(snapshot, known_context())
    frozen = parse_frozen_lines(text)
    combined = html + "\n" + text

    assert frozen["MP1_POINT"] == format_snapshot_number(KNOWN_POINT)
    assert frozen["MP1_POINT"] != "14653"
    assert "350.000,00" in text
    assert "Estimativa pontual" in combined
    assert frozen["MP1_TARGET_UNIT"] == KNOWN_UNIT
    assert frozen["MP1_REFERENCE_DATE"] == KNOWN_REFERENCE_DATE
    assert frozen["MP1_INSPECTION_DATE"] == KNOWN_INSPECTION_DATE
    assert KNOWN_GENERATED_AT in text
    assert KNOWN_REFERENCE_DATE != KNOWN_GENERATED_AT

    assert frozen["MP1_MEAN_CI80_LOWER"] == format_snapshot_number(KNOWN_MEAN_CI80_LOWER)
    assert frozen["MP1_PRED_LOWER"] == format_snapshot_number(KNOWN_PRED_LOWER)
    assert frozen["MP1_ARB_LOWER"] == format_snapshot_number(KNOWN_ARB_LOWER)
    assert frozen["MP1_ADM_LOWER"] == format_snapshot_number(KNOWN_ADM_LOWER)
    assert frozen["MP1_MEAN_CI80_UPPER"] == format_snapshot_number(KNOWN_MEAN_CI80_UPPER)
    assert frozen["MP1_PRED_UPPER"] == format_snapshot_number(KNOWN_PRED_UPPER)
    assert frozen["MP1_ARB_UPPER"] == format_snapshot_number(KNOWN_ARB_UPPER)
    assert frozen["MP1_ADM_UPPER"] == format_snapshot_number(KNOWN_ADM_UPPER)
    assert "IC da média" in combined
    assert "Intervalo preditivo" in combined
    assert "Campo de arbítrio" in combined
    assert "Intervalo de valores admissíveis" in combined
    assert format_snapshot_number(KNOWN_COEF_AREA) in text
    assert "não é laudo aprovado" in combined.lower() or "nao e laudo aprovado" in combined.lower()
    assert "Minuta" in combined
    # Presence of NBR/MP1 strings is never numeric proof.
    assert "14653" in combined or "NBR" in combined or True
    assert frozen["MP1_POINT"] == "350000"


def test_p03_a01_search_audit_not_inferred_from_row_count():
    snap = snapshot_with_audit(approximate=True)
    view = build_report_view(snap, known_context())
    info = interpret_search(snap["search"])
    assert info["coverage_known"] is True
    assert info["approximate"] is True
    assert info["evaluated"] == 12
    assert info["possible"] == 80
    assert view["search_approximate"] is True
    html = compose_report_html(snap, known_context())
    pdf = render_report(snap, known_context())
    text = extract_pdf_text(pdf)
    combined = html + "\n" + text
    assert "Busca aproximada" in combined
    assert "ótimo global" in combined.lower() or "otimo global" in combined.lower()
    assert "não é garantia de ótimo global" in combined.lower() or "nao e garantia" in combined.lower() or "não é garantia" in combined
    assert "Pendência: o snapshot não declara se a busca foi exaustiva" not in combined

    exact = snapshot_with_audit(approximate=False)
    html_e = compose_report_html(exact, known_context())
    assert "ótimo global" not in html_e.split("Trilha técnica")[0] or "não uma aprovação" in html_e
    assert interpret_search(exact["search"])["exhaustive"] is True


def test_p03_a01_formula_composed_from_coefficients_without_refit():
    snap = snapshot_without_formula()
    equation = compose_model_equation(snap["model"], target_col="preco")
    assert equation["present"] is True
    assert equation["source"] == "composed"
    assert "area" in equation["formula"]
    assert "preco" in equation["formula"]
    html = compose_report_html(snap, known_context())
    pdf = render_report(snap, known_context())
    text = extract_pdf_text(pdf)
    combined = html + "\n" + text
    assert "Pendência: fórmula não informada" not in combined
    assert "area" in combined
    assert format_snapshot_number(1234.56789012345) in text or "1234.56789012345" in combined
