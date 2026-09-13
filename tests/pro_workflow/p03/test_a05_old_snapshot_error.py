"""P03-A05: old MP/1 snapshot still renders honestly; renderer failure is structured."""

from __future__ import annotations

import pytest

from modules.results_generator import ReportRenderError, build_report_view, render_report
from tests.c08_report.fixtures import known_context
from tests.c08_report.pdf_text import extract_pdf_text, parse_frozen_lines
from tests.pro_workflow.p03.fixtures import old_mp1_snapshot


def test_p03_a05_old_snapshot_renders_unchanged_point_and_grades():
    snap = old_mp1_snapshot()
    assert "workflow_context" not in snap.get("provenance", {})
    pdf = render_report(snap, known_context())
    assert pdf.startswith(b"%PDF")
    text = extract_pdf_text(pdf)
    frozen = parse_frozen_lines(text)
    assert frozen["MP1_POINT"] == "350000"
    view = build_report_view(snap, known_context())
    assert view["point"] == 350000.0
    assert view["grau_fundamentacao_label"] == "Grau II"
    assert "Grau II" in text


def test_p03_a05_deliberate_engine_failure_is_structured_not_empty_success(monkeypatch):
    class BoomHTML:
        def __init__(self, *args, **kwargs):
            pass

        def write_pdf(self, *args, **kwargs):
            raise RuntimeError("engine down")

    import weasyprint

    monkeypatch.setattr(weasyprint, "HTML", BoomHTML)
    with pytest.raises(ReportRenderError) as caught:
        result = render_report(old_mp1_snapshot(), known_context())
        assert result not in (None, b"", b"%PDF")
    err = caught.value
    assert err.code == "C08_PDF_ENGINE_FAILED"
    assert err.origin == "C08"
    assert "engine down" in err.message
    issue = err.to_issue()
    assert issue["severity"] == "error"
