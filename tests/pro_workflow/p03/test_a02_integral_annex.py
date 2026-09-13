"""P03-A02: 210+ rows deliver IDs and provided values/sources/justificativas."""

from __future__ import annotations

from modules.results_generator import compose_report_html, render_report
from tests.c08_report.fixtures import excluded_row_ids, used_row_ids
from tests.c08_report.pdf_text import extract_pdf_text, pdf_page_count
from tests.pro_workflow.p03.fixtures import long_rows_with_values


def test_p03_a02_integral_ids_and_values_beyond_200():
    snapshot, context = long_rows_with_values()
    html = compose_report_html(snapshot, context)
    pdf = render_report(snapshot, context)
    assert pdf.startswith(b"%PDF")
    text = extract_pdf_text(pdf)
    combined = html + "\n" + text
    ids = used_row_ids(210)
    excl = excluded_row_ids(12)
    assert ids[0] in text
    assert ids[-1] in text
    assert ids[200] in text
    assert "used-0201" in text
    assert excl[0] in text
    assert excl[-1] in text
    assert "planilha sintética C08" in combined
    assert "Excluído por política declarada" in combined
    assert "200100" in combined or "200100.0" in combined or "200100,0" in combined
    assert "Exibindo 200 de" not in combined
    assert "tabela truncada" not in combined.lower()
    assert pdf_page_count(pdf) >= 2
    assert ">nº</th>" in html or "seq" in html or "nº" in html
    assert "thead { display: table-header-group; }" in html
    assert "José da Silva" in combined
    assert context.get("synthetic") is True
