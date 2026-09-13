"""Entrada real frontend/app.py — duas execuções in-process."""

import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

os.environ.setdefault("MODELA_API_TIMEOUT", "2")
os.environ.setdefault("MODELA_DISABLE_WS", "1")

from frontend.components.layout import FIXTURE_SCREEN_NOTICE

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
    at = AppTest.from_file(APP, default_timeout=40)
    at.run()
    if at.exception:
        raise AssertionError(at.exception)
    text = _collect_text(at)
    blob = text.lower()
    assert "encomenda" in blob
    assert "amostra" in blob
    assert "vistoria" in blob
    assert "modelagem" in blob
    assert "emissão" in blob or "emissao" in blob
    assert "modela pro" in blob or "avaliação" in blob
    assert "r² ajustado" not in blob
    assert "aceito pelo banco" not in blob
    return text


def test_launch_frontend_app_twice():
    first = _run_once()
    second = _run_once()
    assert first
    assert second
    assert FIXTURE_SCREEN_NOTICE
