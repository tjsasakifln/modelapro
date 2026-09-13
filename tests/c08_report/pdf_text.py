"""Extract text from rendered PDF bytes without adding a product dependency."""

from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from pathlib import Path


def _normalize_extracted_text(text: str) -> str:
    """pypdf sometimes emits UTF-16-style NUL-padded characters."""
    if "\x00" in text:
        text = text.replace("\x00", "")
    return text


def extract_pdf_text(pdf_bytes: bytes) -> str:
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        raise AssertionError("not a PDF")
    try:
        from pypdf import PdfReader
    except ImportError:
        PdfReader = None
    if PdfReader is not None:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        text = _normalize_extracted_text(text)
        if text.strip():
            return text
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "doc.pdf"
            txt_path = Path(tmp) / "doc.txt"
            pdf_path.write_bytes(pdf_bytes)
            subprocess.run(
                [pdftotext, "-layout", str(pdf_path), str(txt_path)],
                check=True,
            )
            return txt_path.read_text(encoding="utf-8", errors="replace")
    raise AssertionError("neither pypdf nor pdftotext is available to extract PDF text")


def pdf_page_count(pdf_bytes: bytes) -> int:
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


def parse_frozen_lines(text: str) -> dict:
    frozen = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("MP1_"):
            continue
        key, sep, value = line.partition("=")
        if sep:
            frozen[key.strip()] = value.strip()
    return frozen
