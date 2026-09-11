"""C08-A05: renderer failure is an identifiable exception, never silent None."""

from __future__ import annotations

import pytest

from modules.results_generator import ReportRenderError, render_report

from tests.c08_report.fixtures import known_context, known_snapshot


def test_render_report_raises_identifiable_error_not_none(monkeypatch):
    class BoomHTML:
        def __init__(self, *args, **kwargs):
            pass

        def write_pdf(self, *args, **kwargs):
            raise RuntimeError("engine down")

    import weasyprint

    monkeypatch.setattr(weasyprint, "HTML", BoomHTML)

    with pytest.raises(ReportRenderError) as caught:
        result = render_report(known_snapshot(), known_context())
        assert result is not None  # must not return

    err = caught.value
    assert err.code == "C08_PDF_ENGINE_FAILED"
    assert err.origin == "C08"
    assert "engine down" in err.message
    issue = err.to_issue()
    assert issue["code"] == "C08_PDF_ENGINE_FAILED"
    assert issue["severity"] == "error"
    assert issue["origin"] == "C08"


def test_invalid_snapshot_raises_not_none():
    with pytest.raises(ReportRenderError) as caught:
        render_report(None, {})  # type: ignore[arg-type]
    assert caught.value.code == "C08_INVALID_SNAPSHOT"
    assert caught.value.to_issue()["message"]
