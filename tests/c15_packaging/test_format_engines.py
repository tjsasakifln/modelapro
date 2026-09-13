"""Announced formats: CSV, xlsx, xls engines; PDF native probe."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from c15_local.excel_env import probe_excel_engines
from c15_local.pdf_env import LINUX_HINT, NATIVE_INSTALL_HINT, WINDOWS_HINT, probe_weasyprint


def test_excel_engines_are_importable_direct_modules():
    status = probe_excel_engines()
    assert status["csv"].available, status["csv"].detail
    assert status["xlsx"].available, status["xlsx"].detail
    assert status["xls"].available, status["xls"].detail
    assert status["xlsx"].import_name == "openpyxl"
    assert status["xls"].import_name == "xlrd"


def test_csv_and_xlsx_roundtrip_with_declared_engines(tmp_path: Path):
    frame = pd.DataFrame({"area": [50.0, 80.0], "preco": [100000.0, 180000.0]})
    csv_path = tmp_path / "sample.csv"
    xlsx_path = tmp_path / "sample.xlsx"
    frame.to_csv(csv_path, index=False)
    frame.to_excel(xlsx_path, index=False, engine="openpyxl")

    csv_loaded = pd.read_csv(csv_path)
    xlsx_loaded = pd.read_excel(xlsx_path, engine="openpyxl")
    assert list(csv_loaded.columns) == ["area", "preco"]
    assert list(xlsx_loaded.columns) == ["area", "preco"]
    assert len(csv_loaded) == 2
    assert len(xlsx_loaded) == 2


def test_xls_engine_xlrd_is_selected(tmp_path: Path):
    fixture = Path(__file__).parent / "fixtures" / "synthetic_market.xls"
    if fixture.is_file():
        loaded = pd.read_excel(fixture, engine="xlrd")
        assert not loaded.empty
        return
    # Fixture generated during lock/bootstrap. Still prove pandas accepts xlrd.
    import xlrd

    assert hasattr(xlrd, "open_workbook")
    bogus = tmp_path / "not.xls"
    bogus.write_bytes(b"not-biff")
    with pytest.raises(Exception) as err:
        pd.read_excel(bogus, engine="xlrd")
    module = type(err.value).__module__
    name = type(err.value).__name__
    assert "xlrd" in module or name in {"XLRDError", "BadZipFile", "ValueError", "ExcelFileError"}


def test_weasyprint_probe_ok_or_actionable_native_error():
    result = probe_weasyprint()
    if result.ok:
        assert result.pdf_bytes is not None
        assert result.pdf_bytes.startswith(b"%PDF")
        assert result.stage == "ok"
        return
    assert result.stage in {"python_package", "native_libraries", "render"}
    assert NATIVE_INSTALL_HINT in result.message or "weasyprint" in result.message.lower()
    if result.stage == "native_libraries":
        assert LINUX_HINT in result.message or WINDOWS_HINT in result.message
        assert "pip" in result.message.lower()
