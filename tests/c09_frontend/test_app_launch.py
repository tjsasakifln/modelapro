"""Entrada real frontend/app.py — duas execuções in-process."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from frontend.components.layout import FIXTURE_SCREEN_NOTICE, WORK_FLOW_HEADINGS

APP = str(Path(__file__).resolve().parents[2] / "frontend" / "app.py")


def _collect_text(at: AppTest) -> str:
    chunks = []
    for attr in ("title", "header", "subheader", "markdown", "caption", "info", "warning", "error", "text"):
        block = getattr(at, attr, None)
        if not block:
            continue
        for el in block:
            value = getattr(el, "value", None)
            if value is not None:
                chunks.append(str(value))
            else:
                chunks.append(str(el))
    return "\n".join(chunks)


def _run_once() -> str:
    at = AppTest.from_file(APP, default_timeout=20)
    at.run()
    if at.exception:
        raise AssertionError(at.exception)
    text = _collect_text(at)
    joined_headings = " ".join(WORK_FLOW_HEADINGS)
    assert "Importar e revisar interpretação" in joined_headings
    assert "Valor da avaliação" in joined_headings or "Revisar valor" in joined_headings
    assert "MODELA PRO" in text or "Importar" in text or "avaliação" in text.lower()
    assert "R² Ajustado" not in text
    return text


def test_launch_frontend_app_twice():
    first = _run_once()
    second = _run_once()
    assert first
    assert second
    assert FIXTURE_SCREEN_NOTICE
