"""P02 launch: frontend/app.py twice via AppTest."""

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
    assert "Encomenda" in joined
    assert "Amostra" in joined
    assert "vistoria" in joined.lower()
    assert "Modelagem" in joined
    assert "Emissão" in joined
    assert "MODELA PRO" in text or "Encomenda" in text or "amostra" in text.lower()
    assert "R² Ajustado" not in text
    assert "atende à norma" not in text.lower()
    assert "aceito pelo banco" not in text.lower()
    return text


def test_launch_frontend_app_twice():
    first = _run_once()
    second = _run_once()
    assert first
    assert second
    assert FIXTURE_SCREEN_NOTICE
