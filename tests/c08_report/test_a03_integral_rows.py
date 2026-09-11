"""C08-A03: >200 rows are delivered in full; n matches row_ids."""

from __future__ import annotations

from modules.results_generator import compose_report_html, format_snapshot_number

from tests.c08_report.fixtures import (
    N_EXCLUDED,
    N_OBSERVED,
    N_PREPARED,
    N_RECEIVED,
    N_USED,
    excluded_row_ids,
    long_table_context,
    long_table_snapshot,
    used_row_ids,
)
from tests.c08_report.pdf_text import extract_pdf_text, parse_frozen_lines


def test_more_than_200_rows_are_integral_and_n_matches_ids(long_table_pdf):
    snapshot = long_table_snapshot()
    context = long_table_context()
    html = compose_report_html(snapshot, context)
    pdf = long_table_pdf
    assert pdf.startswith(b"%PDF")
    text = extract_pdf_text(pdf)
    frozen = parse_frozen_lines(text)
    combined = html + "\n" + text

    ids = used_row_ids(N_USED)
    excl = excluded_row_ids(N_EXCLUDED)
    first_id, last_id = ids[0], ids[-1]
    assert first_id in text
    assert last_id in text
    assert excl[0] in text
    assert excl[-1] in text
    # A mid-range id beyond the legacy 200 cap must also appear.
    assert ids[200] in text
    assert "used-0201" in text

    assert frozen["MP1_N_RECEIVED"] == format_snapshot_number(N_RECEIVED)
    assert frozen["MP1_N_OBSERVED"] == format_snapshot_number(N_OBSERVED)
    assert frozen["MP1_N_PREPARED"] == format_snapshot_number(N_PREPARED)
    assert frozen["MP1_N_USED"] == format_snapshot_number(N_USED)
    assert frozen["MP1_N_EXCLUDED"] == format_snapshot_number(N_EXCLUDED)

    assert "Exibindo 200 de" not in combined
    assert "tabela truncada" not in combined.lower()
    assert "planilha sintética C08" in combined
    assert "Excluído por política declarada" in combined
    # The annex list is part of the same PDF bytes.
    assert "Anexo integral" in combined
