"""Legacy generate_pdf_report adapter still returns PDF bytes for ModelResult."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from modules.model_builder import ModelBuilder
from modules.results_generator import ResultsGenerator, format_snapshot_number, render_report
from tests.c08_report.fixtures import known_context, known_snapshot
from tests.c08_report.pdf_text import extract_pdf_text, parse_frozen_lines


def _valid_model_result():
    np.random.seed(0)
    n = 30
    area = np.linspace(50, 200, n)
    quartos = np.random.randint(1, 5, n)
    noise = np.random.normal(0, 500, n)
    preco = 1000 * area + 5000 * quartos + 20000 + noise
    X = pd.DataFrame({"area": area, "quartos": quartos})
    y = pd.Series(preco)
    builder = ModelBuilder()
    result = builder.build_model(X, y, degree=1)
    assert result.success is True
    avaliando = {"area": 120.0, "quartos": 3}
    result = builder.add_precision_and_extrapolation(result, avaliando, original_df=X, degree=1)
    return result, avaliando, X


def test_adapter_returns_pdf_for_valid_model_result():
    result, avaliando, X = _valid_model_result()
    pdf = ResultsGenerator.generate_pdf_report(
        result,
        target_col="preco",
        avaliando_raw=avaliando,
        solicitante="Fulano de Tal",
        finalidade="Teste unitário",
        exhaustive=False,
        combinations_tested=9,
        search_message="fallback de teste",
        market_summary=ResultsGenerator.build_market_summary(X, variable_cols=["area"]),
    )
    assert pdf is not None
    assert pdf[:4] == b"%PDF"
    text = extract_pdf_text(pdf)
    frozen = parse_frozen_lines(text)
    # Adapter must not stamp today as data-base.
    assert frozen["MP1_REFERENCE_DATE"] == "PENDENTE"
    today = date.today().isoformat()
    assert frozen["MP1_REFERENCE_DATE"] != today
    assert "Busca aproximada" in text
    assert "Descritiva amostral" in text
    assert "Diagnóstico do Mercado" not in text or "não é diagnóstico substantivo completo" in text.lower()


def test_adapter_does_not_truncate_market_data_at_200():
    result, avaliando, _X = _valid_model_result()
    rows = 220
    market = pd.DataFrame(
        {
            "row_id": [f"md-{i:04d}" for i in range(rows)],
            "nome": ["José " + ("Z" * 30) for _ in range(rows)],
        }
    )
    pdf = ResultsGenerator.generate_pdf_report(
        result,
        target_col="preco",
        avaliando_raw=avaliando,
        market_data=market,
    )
    assert pdf is not None
    text = extract_pdf_text(pdf)
    assert "md-0000" in text
    assert "md-0219" in text
    assert "Exibindo 200 de" not in text


def test_adapter_invalid_input_still_returns_none():
    assert ResultsGenerator.generate_pdf_report(None) is None

    class NotAModelResult:
        pass

    assert ResultsGenerator.generate_pdf_report(NotAModelResult()) is None


def test_module_level_render_report_export():
    from modules.results_generator import render_report as exported

    pdf = exported(known_snapshot(), known_context())
    assert pdf.startswith(b"%PDF")
    frozen = parse_frozen_lines(extract_pdf_text(pdf))
    assert frozen["MP1_POINT"] == format_snapshot_number(350000.0)
    # Same entry point as the class method.
    pdf2 = ResultsGenerator.render_report(known_snapshot(), known_context())
    assert parse_frozen_lines(extract_pdf_text(pdf2))["MP1_POINT"] == frozen["MP1_POINT"]
