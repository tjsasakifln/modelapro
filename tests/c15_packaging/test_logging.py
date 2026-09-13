"""Rotating logs without client-payload fields."""

from __future__ import annotations

from pathlib import Path

from modules.logging_manager import (
    CLIENT_DATA_RECORD_KEYS,
    LOG_FORMAT,
    DropClientDataFilter,
    setup_logging,
)


def test_formatter_has_no_request_body_or_client_pii_field():
    assert "request_body" not in LOG_FORMAT
    assert "message" in LOG_FORMAT
    for key in CLIENT_DATA_RECORD_KEYS:
        assert key not in LOG_FORMAT


def test_setup_logging_rotates_and_strips_client_extras(tmp_path: Path):
    logger = setup_logging("c15-logging-probe", log_dir=str(tmp_path), level="INFO")
    handlers = logger.handlers
    assert any(type(handler).__name__ == "RotatingFileHandler" for handler in handlers)
    assert any(type(handler).__name__ == "StreamHandler" for handler in handlers)
    for handler in handlers:
        assert any(isinstance(item, DropClientDataFilter) for item in handler.filters)

    logger.info(
        "analysis finished",
        extra={"request_body": "CLIENT_SECRET_ROW", "client_data": "cpf-000"},
    )
    for handler in handlers:
        handler.flush()

    log_file = tmp_path / "modelapro.log"
    assert log_file.is_file()
    text = log_file.read_text(encoding="utf-8")
    assert "analysis finished" in text
    assert "CLIENT_SECRET_ROW" not in text
    assert "cpf-000" not in text
    assert "request_body" not in text
