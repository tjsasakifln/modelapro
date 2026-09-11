"""C08-A02: warnings, precision status, approximate search are distinguishable."""

from __future__ import annotations

from modules.results_generator import compose_report_html, render_report

from tests.c08_report.fixtures import known_context, warnings_snapshot
from tests.c08_report.pdf_text import extract_pdf_text, parse_frozen_lines


def test_warnings_precision_search_and_actions_are_distinguishable():
    snapshot = warnings_snapshot()
    context = known_context()
    html = compose_report_html(snapshot, context)
    pdf = render_report(snapshot, context)
    text = extract_pdf_text(pdf)
    frozen = parse_frozen_lines(text)
    combined = html + "\n" + text

    assert frozen["MP1_PRECISAO_STATUS"] == "unclassified"
    assert frozen["MP1_ISSUANCE"] == "draft"
    assert "não é laudo aprovado" in combined.lower() or "nao e laudo aprovado" in combined.lower()
    assert "Minuta" in combined or "minuta" in combined

    assert "NBR_FUND_PENDING" in combined
    assert "STAT_HETEROSCEDASTICITY" in combined
    assert "DOC_NOT_VERIFIED" in combined
    assert "SEARCH_NOT_EXHAUSTIVE" in combined
    assert "INFERENCE_TRANSFORM" in combined
    assert "Normativo" in combined
    assert "Estatístico" in combined
    assert "Documental" in combined
    assert "Busca aproximada" in combined
    assert "não classificável" in combined or "nao classificavel" in combined
    assert "issue-normative" in html
    assert "issue-statistical" in html
    assert "issue-documentary" in html
    assert "issue-search" in html
    assert "issue-inference" in html

    assert "Declarado" in combined
    assert "Presente" in combined
    assert "JUSTIFY_PRECISION" in combined
    assert "IC da média" in combined
    assert "Intervalo preditivo" in combined
    assert "Média versus mediana" in combined
    assert "avaliação superior" in combined.lower()
    assert "não é diagnóstico substantivo completo" in combined.lower()
    assert "R² maior não significa" in combined or "não significa, por si só, avaliação superior" in combined
    # No green-only success banner that hides warnings.
    assert "#2e7d32" not in html
    assert "laudo aprovado automaticamente" not in html.replace("não é laudo aprovado automaticamente", "")
