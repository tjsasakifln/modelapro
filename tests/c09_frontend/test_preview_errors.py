"""Frontend surfaces HTTP status, error, issue codes, messages and next action."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading

import pytest
from streamlit.testing.v1 import AppTest

from frontend.components.forms import (
    ApiResponseError,
    JobClient,
    format_preview_error,
    recommended_preview_action,
)


def _payload_400():
    return {
        "schema_version": "MP/1",
        "error": "target_col must be a non-empty string",
        "issues": [
            {
                "code": "MISSING_FIELD",
                "severity": "error",
                "message": "target_col must be a non-empty string",
            }
        ],
    }


def _payload_422():
    return {
        "schema_version": "MP/1",
        "error": "preview failed",
        "issues": [
            {
                "code": "excel_parse_error",
                "severity": "error",
                "message": "Falha ao interpretar Excel: broken zip",
            }
        ],
    }


def _payload_503():
    return {
        "schema_version": "MP/1",
        "error": "ingest_market unavailable",
        "issues": [
            {
                "code": "PEER_UNAVAILABLE",
                "severity": "error",
                "message": "preview requires modules.data_loader.ingest_market",
                "evidence": {"missing": ["ingest_market"], "integration": "INTEGRATION_PENDING"},
            }
        ],
        "integration": "INTEGRATION_PENDING",
    }


@pytest.mark.parametrize(
    "status,payload,needle",
    [
        (400, _payload_400(), "MISSING_FIELD"),
        (422, _payload_422(), "excel_parse_error"),
        (503, _payload_503(), "PEER_UNAVAILABLE"),
    ],
)
def test_format_preview_error_includes_status_error_codes_and_action(status, payload, needle):
    text = format_preview_error(status, payload)
    assert f"HTTP {status}" in text
    assert f"error: {payload['error']}" in text
    assert needle in text
    assert payload["issues"][0]["message"] in text
    assert "Próxima ação:" in text
    action = recommended_preview_action(status, payload)
    assert action
    assert action in text


def test_format_unwraps_fastapi_detail_envelope():
    text = format_preview_error(400, {"detail": _payload_400()})
    assert "HTTP 400" in text
    assert "MISSING_FIELD" in text
    assert "target_col must be a non-empty string" in text


class _PreviewErrorStub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        code, payload = self.server.preview_error
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _start(status, payload):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _PreviewErrorStub)
    server.preview_error = (status, payload)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


@pytest.mark.parametrize(
    "status,payload,needle",
    [
        (400, _payload_400(), "MISSING_FIELD"),
        (422, _payload_422(), "excel_parse_error"),
        (503, _payload_503(), "PEER_UNAVAILABLE"),
    ],
)
def test_job_client_preview_raises_formatted_400_422_503(status, payload, needle):
    server, url = _start(status, payload)
    try:
        client = JobClient(base_url=url, timeout=2)
        with pytest.raises(ApiResponseError) as exc:
            client.preview(b"col\n1", "a.csv", {"schema_version": "MP/1", "target_col": ""})
        assert exc.value.status_code == status
        message = str(exc.value)
        assert f"HTTP {status}" in message
        assert payload["error"] in message
        assert needle in message
        assert "Próxima ação:" in message
    finally:
        server.shutdown()


def test_apptest_renders_formatted_preview_errors(tmp_path):
    script = tmp_path / "preview_error_app.py"
    script.write_text(
        "\n".join(
            [
                "import streamlit as st",
                "from frontend.components.forms import format_preview_error",
                f"st.error(format_preview_error(400, {json.dumps(_payload_400())}))",
                f"st.error(format_preview_error(422, {json.dumps(_payload_422())}))",
                f"st.error(format_preview_error(503, {json.dumps(_payload_503())}))",
            ]
        ),
        encoding="utf-8",
    )
    at = AppTest.from_file(str(script), default_timeout=20)
    at.run()
    if at.exception:
        raise AssertionError(at.exception)
    texts = [str(el.value) for el in at.error]
    joined = "\n".join(texts)
    assert "HTTP 400" in joined and "MISSING_FIELD" in joined
    assert "HTTP 422" in joined and "excel_parse_error" in joined
    assert "HTTP 503" in joined and "PEER_UNAVAILABLE" in joined
    assert "Próxima ação:" in joined
    assert Path(script).exists()
