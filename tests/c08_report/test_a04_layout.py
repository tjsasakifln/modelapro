"""C08-A04: long table, unicode, mixed units, Portuguese charts, real PDF pages."""

from __future__ import annotations

from modules.results_generator import compose_report_html

from tests.c08_report.fixtures import (
    LONG_UNICODE_NAME,
    long_table_context,
    long_table_snapshot,
    used_row_ids,
)
from tests.c08_report.pdf_text import extract_pdf_text, pdf_page_count


def test_long_unicode_and_mixed_units_survive_render(long_table_pdf):
    snapshot = long_table_snapshot()
    context = long_table_context()
    html = compose_report_html(snapshot, context)
    assert "page-break-inside: avoid" in html
    assert "overflow-wrap: anywhere" in html
    assert "Resíduos versus valores ajustados" in html
    assert "Histograma dos resíduos" in html
    assert "Observado versus estimado" in html
    assert "Fitted Values" not in html
    assert "Histogram of Residuals" not in html
    assert LONG_UNICODE_NAME in html
    assert "José da Silva" in html
    assert "αβ" in html
    assert "ção" in html

    pdf = long_table_pdf
    assert pdf.startswith(b"%PDF")
    pages = pdf_page_count(pdf)
    assert pages >= 2
    text = extract_pdf_text(pdf)
    last_id = used_row_ids()[-1]
    assert last_id in text
    assert "José da Silva" in text or "Jose da Silva" in text or "José da Silva" in html
    assert "αβ" in text or "αβ" in html
    assert "BRL/m2" in text or "BRL/m²" in html
    assert "linha 1" in text or "linha 1" in html
    assert "n efetivo" in (text + html).lower()
