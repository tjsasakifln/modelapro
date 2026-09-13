"""P03-A03: formula/diagnostics/series presented without false pendência; scale and shift checks."""

from __future__ import annotations

from modules.report_presenter.formula import compose_model_equation
from modules.report_presenter.series import assess_chart_series
from modules.results_generator import (
    _attach_charts,
    build_report_view,
    compose_report_html,
    format_snapshot_number,
    render_report,
)
from tests.c08_report.fixtures import (
    known_context,
    known_snapshot,
    long_table_context,
    long_table_snapshot,
)
from tests.c08_report.pdf_text import extract_pdf_text, parse_frozen_lines
from tests.pro_workflow.p03.fixtures import (
    SYNTHETIC_LABEL,
    aligned_series_context,
    length_mismatch_series_context,
    missing_series_context,
    shifted_series_context,
    snapshot_log_scale,
    snapshot_without_formula,
)


def test_p03_a03_present_formula_has_no_false_pendencia():
    snap = snapshot_without_formula()
    ctx = known_context()
    html = compose_report_html(snap, ctx)
    pdf = render_report(snap, ctx)
    text = extract_pdf_text(pdf)
    combined = html + "\n" + text
    assert "Pendência: fórmula não informada" not in combined
    assert compose_model_equation(snap["model"], target_col="preco")["present"] is True


def test_p03_a03_absent_formula_and_series_are_not_invented():
    snap = known_snapshot()
    snap = dict(snap)
    snap["model"] = dict(snap["model"])
    snap["model"]["formula"] = ""
    snap["model"]["coefficients"] = {}
    ctx = missing_series_context()
    view = build_report_view(snap, ctx)
    html = compose_report_html(snap, ctx, view=view)
    assert view["formula_present"] is False
    assert "exp(const" not in html.lower()
    assert "exp(10.5" not in html.lower()
    assert view["chart_available"] is False
    assert "não foram fornecidas" in (view["chart_absence_reason"] + html)
    assert "exp(const" not in html.lower()
    assert ctx["synthetic"] is True
    assert SYNTHETIC_LABEL in ctx["synthetic_label"]


def test_p03_a03_log_scale_distinct_from_monetary_mean():
    snap = snapshot_log_scale()
    equation = compose_model_equation(snap["model"], target_col="preco")
    assert equation["log_scale"] is True
    assert equation["fitting_scale"] == "logarítmica"
    assert equation["prints_exp_as_mean"] is False
    assert "ln(preco)" in equation["formula"]
    html = compose_report_html(snap, known_context())
    pdf = render_report(snap, known_context())
    text = extract_pdf_text(pdf)
    combined = html + "\n" + text
    assert "escala logarítmica" in combined.lower() or "logarítmica" in combined
    assert "não imprime exp" in combined.lower() or "nao imprime exp" in combined.lower() or "exp(ajuste)" in combined
    assert "IC da média" in combined
    assert "Intervalo preditivo" in combined


def test_p03_a03_mean_ci_and_prediction_remain_distinct():
    html = compose_report_html(known_snapshot(), known_context())
    assert "IC da média (80%) — não é intervalo preditivo nem mediana" in html
    assert "Intervalo preditivo — distinto do IC da média" in html
    assert "Campo de arbítrio" in html
    assert "Intervalo de valores admissíveis" in html


def test_p03_a03_aligned_series_plot_shifted_series_rejected():
    aligned = assess_chart_series(aligned_series_context(), used_row_ids=[f"used-{i:04d}" for i in range(1, 31)])
    assert aligned["plot"] is True
    assert aligned["warning"] is None
    view = build_report_view(known_snapshot(), aligned_series_context())
    view = _attach_charts(view, aligned_series_context())
    view_charts = render_report(known_snapshot(), aligned_series_context())
    assert view_charts.startswith(b"%PDF")
    assert view["chart_available"] is True
    assert view["charts"]

    shifted = assess_chart_series(
        shifted_series_context(),
        used_row_ids=[f"used-{i:04d}" for i in range(1, 31)],
    )
    assert shifted["plot"] is False
    assert shifted["warning"]
    assert shifted["warning"]["code"] in {"REPORT_CHARTS_SHIFTED", "REPORT_CHARTS_ID_MISMATCH"}

    mismatch = assess_chart_series(
        length_mismatch_series_context(),
        used_row_ids=[f"used-{i:04d}" for i in range(1, 31)],
    )
    assert mismatch["plot"] is False
    assert mismatch["warning"]["code"] == "REPORT_CHARTS_LENGTH_MISMATCH"

    pdf = render_report(known_snapshot(), shifted_series_context())
    text = extract_pdf_text(pdf)
    html = compose_report_html(known_snapshot(), shifted_series_context())
    combined = html + "\n" + text
    assert "desalinh" in combined.lower() or "Aviso de gráfico" in combined or "não foram plotadas" in combined
    frozen = [line for line in text.splitlines() if line.startswith("MP1_POINT")]
    assert frozen and "350000" in frozen[0]


def test_p03_a03_series_length_not_n_used_without_row_ids_is_refused():
    """210 used ids + 30 fitted/residuals and no series_row_ids must not plot."""
    snap = long_table_snapshot()
    ctx = long_table_context()
    used_ids = snap["sample"]["used_row_ids"]
    assert ctx.get("series_row_ids") is None
    assert "series_row_ids" not in ctx
    assert len(ctx["fitted_values"]) == len(ctx["residuals"]) == 30
    assert len(used_ids) == 210
    assert len(ctx["fitted_values"]) != len(used_ids)

    assessed = assess_chart_series(ctx, used_row_ids=used_ids)
    assert assessed["plot"] is False
    assert assessed["warning"]["code"] == "REPORT_CHARTS_LENGTH_MISMATCH"

    view = build_report_view(snap, ctx)
    view = _attach_charts(view, ctx)
    assert view["chart_available"] is False
    assert view["charts"] == {}
    assert (view.get("chart_warning") or {}).get("code") == "REPORT_CHARTS_LENGTH_MISMATCH"

    html = compose_report_html(snap, ctx, view=view)
    assert "data:image/png;base64" not in html
    assert "não foram plotadas" in html.lower() or "aviso de gráfico" in html.lower()

    pdf = render_report(snap, ctx)
    assert pdf.startswith(b"%PDF")
    text = extract_pdf_text(pdf)
    frozen = parse_frozen_lines(text)
    assert frozen["MP1_POINT"] == format_snapshot_number(snap["value"]["point"])
    assert frozen["MP1_POINT"] == "3500"
    combined = html + "\n" + text
    assert "não foram plotadas" in combined.lower() or "aviso de gráfico" in combined.lower()
    assert used_ids[200] in text
