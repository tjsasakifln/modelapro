"""Process logging: rotating files, metadata only, no client payloads."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

from .config_manager import config

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(process)d - %(message)s"
CLIENT_DATA_RECORD_KEYS = frozenset(
    {
        "request_body",
        "request_payload",
        "file_content",
        "file_bytes",
        "client_data",
        "spreadsheet",
        "avaliando",
        "uploaded_file",
        "raw_frame",
        "payload",
        "csv_content",
    }
)
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 7


class DropClientDataFilter(logging.Filter):
    """Strip extras that would persist client/spreadsheet payloads to disk."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key in CLIENT_DATA_RECORD_KEYS:
            if hasattr(record, key):
                delattr(record, key)
        return True


def setup_logging(
    name: str,
    *,
    log_dir: Optional[str] = None,
    level: Optional[str] = None,
) -> logging.Logger:
    """
    Configure a named logger with stdout + rotating file handlers.

    The formatter records time, logger, level, pid and message. It has no
    request-body / client-PII field. Callers must not put spreadsheet bytes
    or client identifiers into the message.
    """
    logger = logging.getLogger(name)
    resolved_level = getattr(logging, (level or config.LOG_LEVEL).upper(), logging.INFO)
    logger.setLevel(resolved_level)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(LOG_FORMAT)
    client_filter = DropClientDataFilter()

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    stream.addFilter(client_filter)
    logger.addHandler(stream)

    directory = log_dir if log_dir is not None else config.LOG_DIR
    if directory:
        try:
            os.makedirs(directory, exist_ok=True)
            file_handler = RotatingFileHandler(
                os.path.join(directory, "modelapro.log"),
                maxBytes=_MAX_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler.addFilter(client_filter)
            logger.addHandler(file_handler)
        except OSError as exc:
            logger.warning("Rotating file log disabled (%s); stdout only", exc)

    logger.propagate = False
    return logger


logger = setup_logging("modelapro")
