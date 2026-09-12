"""C02-A08: AppTest of the real frontend/app.py twice; professional path headings."""

import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

os.environ.setdefault("MODELA_API_TIMEOUT", "2")
os.environ.setdefault("MODELA_DISABLE_WS", "1")

from frontend.components.layout import FIXTURE_SCREEN_NOTICE, WORK_FLOW_HEADINGS

APP = str(Path(__file__).resolve().parents[3] / "frontend" / "app.py")


def _collect_text(at: AppTest) -> str:
    chunks = []
    for attr in ("title", "header", "subheader", "markdown", "caption", "info", "warning", "error", "text"):
        block = getattr(at, attr, None)
        if not block:
            continue
        for el in block:
            value = getattr(el, "value", None)
            chunks.append(str(value if value is not None else el))
    return "\n".join(chunks)


def _run_once() -> str:
    at = AppTest.from_file(APP, default_timeout=40)
    at.run()
    if at.exception:
        raise AssertionError(at.exception)
    text = _collect_text(at)
    joined = " ".join(WORK_FLOW_HEADINGS)
    assert "encomenda" in joined.lower()
    assert "amostra" in joined.lower()
    assert "vistoria" in joined.lower()
    assert "modelagem" in joined.lower()
    assert "emissão" in joined.lower() or "emissao" in joined.lower()
    blob = (text + "\n" + joined).lower()
    assert "encomenda" in blob
    assert "atende à norma" not in blob
    assert "aceito pelo banco" not in blob
    assert "aceito pela seguradora" not in blob
    assert "r² ajustado" not in blob
    return text


def test_launch_professional_path_twice():
    first = _run_once()
    second = _run_once()
    assert first
    assert second
    assert FIXTURE_SCREEN_NOTICE
