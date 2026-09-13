"""Shared CSV/Excel interpretation for C01 ingest.

UI preview and the API must use this reader (C09 via C10 /preview) so
delimiter, encoding, BOM and engine choices cannot diverge. This module
does not implement an upload service: file-size limits are reported as
structured issues for C10.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

SCHEMA_VERSION = "MP/1"
DEFAULT_MAX_FILE_BYTES = 50 * 1024 * 1024
CSV_EXTENSIONS = {".csv"}
EXCEL_EXTENSIONS = {".xls", ".xlsx"}
SUPPORTED_EXTENSIONS = CSV_EXTENSIONS | EXCEL_EXTENSIONS
SUPPORTED_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin1")
DELIMITER_CANDIDATES = ",;\t|"

_BOM_PREFIXES = (
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)


def make_issue(
    code: str,
    severity: str,
    message: str,
    *,
    origin: str = "C01",
    affected_ids: Optional[List[str]] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "origin": origin,
        "message": message,
        "affected_ids": list(affected_ids or []),
        "evidence": dict(evidence or {}),
    }


def extension_of(filename: str) -> str:
    base = str(filename or "").replace("\\", "/").split("/")[-1]
    if "." not in base or base.startswith("."):
        suffix = base.rsplit(".", 1)[-1] if "." in base else ""
        return f".{suffix.lower()}" if suffix else ""
    return "." + base.rsplit(".", 1)[-1].lower()


def detect_bom(file_bytes: bytes) -> Optional[str]:
    for prefix, encoding in _BOM_PREFIXES:
        if file_bytes.startswith(prefix):
            return encoding
    return None


@dataclass
class TabularRead:
    frame: pd.DataFrame
    metadata: Dict[str, Any]
    issues: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[Dict[str, Any]] = None


def read_tabular(
    file_bytes: bytes,
    filename: str,
    import_options: Optional[Dict[str, Any]] = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> TabularRead:
    """Read CSV/Excel bytes into a raw frame without cleaning names or values."""
    options = dict(import_options or {})
    issues: List[Dict[str, Any]] = []
    n_bytes = 0 if file_bytes is None else len(file_bytes)
    ext = extension_of(filename)
    metadata: Dict[str, Any] = {
        "filename": filename,
        "extension": ext,
        "encoding": None,
        "delimiter": None,
        "engine": None,
        "bom": False,
        "n_bytes": n_bytes,
        "n_rows": 0,
        "n_cols": 0,
        "sheet_name": None,
        "max_file_bytes": max_file_bytes,
    }

    if file_bytes is None:
        err = make_issue(
            "empty_file",
            "error",
            "Arquivo ausente (bytes nulos).",
            evidence={"field": "file_bytes", "filename": filename},
        )
        return TabularRead(pd.DataFrame(), metadata, [err], err)

    if n_bytes > max_file_bytes:
        err = make_issue(
            "file_size_limit",
            "error",
            (
                f"Arquivo excede o limite de {max_file_bytes} bytes "
                f"({n_bytes} bytes). Limite reportado para C10; "
                "C01 não implementa serviço de upload."
            ),
            evidence={
                "n_bytes": n_bytes,
                "limit_bytes": max_file_bytes,
                "filename": filename,
                "report_to": "C10",
            },
        )
        return TabularRead(pd.DataFrame(), metadata, [err], err)

    if ext not in SUPPORTED_EXTENSIONS:
        err = make_issue(
            "unsupported_format",
            "error",
            f"Unsupported file format: {ext or '(sem extensão)'} ({filename!r}).",
            evidence={
                "field": "filename",
                "filename": filename,
                "extension": ext,
                "supported": sorted(SUPPORTED_EXTENSIONS),
            },
        )
        return TabularRead(pd.DataFrame(), metadata, [err], err)

    if ext in CSV_EXTENSIONS:
        result = _read_csv(file_bytes, filename, options, metadata, issues)
    else:
        result = _read_excel(file_bytes, filename, options, metadata, issues)

    if result.error is None:
        frame = result.frame
        result.metadata["n_rows"] = int(len(frame))
        result.metadata["n_cols"] = int(len(frame.columns))
        if frame.empty or len(frame.columns) == 0:
            err = make_issue(
                "empty_file",
                "error",
                "Arquivo vazio: nenhuma linha de dados ou nenhuma coluna.",
                evidence={
                    "filename": filename,
                    "n_rows": result.metadata["n_rows"],
                    "n_cols": result.metadata["n_cols"],
                    "encoding": result.metadata.get("encoding"),
                    "delimiter": result.metadata.get("delimiter"),
                    "engine": result.metadata.get("engine"),
                },
            )
            result.issues.append(err)
            result.error = err
    return result


def _read_csv(
    file_bytes: bytes,
    filename: str,
    options: Dict[str, Any],
    metadata: Dict[str, Any],
    issues: List[Dict[str, Any]],
) -> TabularRead:
    requested_encoding = options.get("encoding")
    requested_delimiter = options.get("delimiter")
    bom_encoding = detect_bom(file_bytes)
    metadata["bom"] = bom_encoding is not None

    try:
        text, encoding = _decode_csv_bytes(file_bytes, requested_encoding, bom_encoding)
    except ValueError as exc:
        err = make_issue(
            "encoding_error",
            "error",
            str(exc),
            evidence={
                "field": "encoding",
                "filename": filename,
                "requested_encoding": requested_encoding,
                "bom": bom_encoding,
            },
        )
        issues.append(err)
        return TabularRead(pd.DataFrame(), metadata, issues, err)

    metadata["encoding"] = encoding
    delimiter = requested_delimiter if requested_delimiter not in (None, "") else _detect_delimiter(text)
    metadata["delimiter"] = delimiter
    metadata["engine"] = "pandas.csv"

    if not text.strip():
        err = make_issue(
            "empty_file",
            "error",
            "Arquivo vazio: nenhuma linha de dados ou nenhuma coluna.",
            evidence={
                "filename": filename,
                "encoding": encoding,
                "n_bytes": metadata.get("n_bytes"),
            },
        )
        issues.append(err)
        return TabularRead(pd.DataFrame(), metadata, issues, err)

    try:
        frame = pd.read_csv(
            io.StringIO(text),
            sep=delimiter,
            dtype=str,
            keep_default_na=False,
            index_col=False,
            engine="python",
        )
    except Exception as exc:
        empty = type(exc).__name__ == "EmptyDataError" or "No columns to parse" in str(exc)
        code = "empty_file" if empty else "csv_parse_error"
        err = make_issue(
            code,
            "error",
            "Arquivo vazio: nenhuma linha de dados ou nenhuma coluna."
            if empty
            else f"Falha ao interpretar CSV: {exc}",
            evidence={
                "filename": filename,
                "encoding": encoding,
                "delimiter": delimiter,
                "position": _extract_parse_position(exc),
                "error_type": type(exc).__name__,
            },
        )
        issues.append(err)
        return TabularRead(pd.DataFrame(), metadata, issues, err)

    issues.append(
        make_issue(
            "read_metadata",
            "info",
            (
                f"CSV lido: encoding={encoding}, delimiter={delimiter!r}, "
                f"bom={metadata['bom']}, bytes={metadata['n_bytes']}."
            ),
            evidence=dict(metadata),
        )
    )
    return TabularRead(frame, metadata, issues, None)


def _read_excel(
    file_bytes: bytes,
    filename: str,
    options: Dict[str, Any],
    metadata: Dict[str, Any],
    issues: List[Dict[str, Any]],
) -> TabularRead:
    ext = metadata.get("extension") or extension_of(filename)
    engine = "xlrd" if ext == ".xls" else "openpyxl"
    metadata["engine"] = engine
    metadata["encoding"] = None
    metadata["delimiter"] = None

    try:
        frame = pd.read_excel(
            io.BytesIO(file_bytes),
            engine=engine,
            dtype=object,
        )
    except ImportError as exc:
        err = make_issue(
            "excel_engine_missing",
            "error",
            (
                f"Engine Excel {engine!r} indisponível para {ext}. "
                "C15 deve declarar o pacote no lockfile; C01 não finge leitura."
            ),
            evidence={
                "filename": filename,
                "extension": ext,
                "engine": engine,
                "report_to": "C15",
                "error": str(exc),
            },
        )
        issues.append(err)
        return TabularRead(pd.DataFrame(), metadata, issues, err)
    except Exception as exc:
        err = make_issue(
            "excel_parse_error",
            "error",
            f"Falha ao interpretar Excel: {exc}",
            evidence={
                "filename": filename,
                "extension": ext,
                "engine": engine,
                "error_type": type(exc).__name__,
            },
        )
        issues.append(err)
        return TabularRead(pd.DataFrame(), metadata, issues, err)

    metadata["sheet_name"] = 0
    issues.append(
        make_issue(
            "read_metadata",
            "info",
            f"Excel lido: engine={engine}, bytes={metadata['n_bytes']}.",
            evidence=dict(metadata),
        )
    )
    return TabularRead(frame, metadata, issues, None)


def _decode_csv_bytes(
    file_bytes: bytes,
    requested_encoding: Optional[str],
    bom_encoding: Optional[str],
) -> tuple:
    if requested_encoding:
        try:
            return file_bytes.decode(requested_encoding), requested_encoding
        except LookupError as exc:
            raise ValueError(f"Codificação não suportada: {requested_encoding!r}.") from exc
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"Não foi possível decodificar com encoding={requested_encoding!r} "
                f"(posição {exc.start})."
            ) from exc

    candidates = []
    if bom_encoding:
        candidates.append(bom_encoding)
    for enc in SUPPORTED_ENCODINGS:
        if enc not in candidates:
            candidates.append(enc)

    last_error = None
    for enc in candidates:
        try:
            return file_bytes.decode(enc), enc
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    raise ValueError(
        "Não foi possível decodificar o CSV com as encodings suportadas "
        f"{list(SUPPORTED_ENCODINGS)}."
    ) from last_error


def _detect_delimiter(text: str) -> str:
    sample_lines = [ln for ln in text.splitlines() if ln.strip()][:20]
    sample = "\n".join(sample_lines)
    if not sample:
        return ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=DELIMITER_CANDIDATES)
        if dialect.delimiter:
            return dialect.delimiter
    except csv.Error:
        pass
    first = sample_lines[0]
    counts = {d: first.count(d) for d in [",", ";", "\t", "|"]}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def _extract_parse_position(exc: BaseException) -> Optional[Dict[str, Any]]:
    msg = str(exc)
    evidence: Dict[str, Any] = {"message": msg}
    for attr in ("lineno", "line_num", "row", "col", "column"):
        if hasattr(exc, attr):
            evidence[attr] = getattr(exc, attr)
    return evidence
