import numpy as np
import pandas as pd
import weasyprint

from modules.model_builder import ModelBuilder
from modules.results_generator import ResultsGenerator


class TestGeneratePdfReport:
    def _build_valid_model_result(self):
        np.random.seed(0)
        n = 30
        area = np.linspace(50, 200, n)
        quartos = np.random.randint(1, 5, n)
        noise = np.random.normal(0, 500, n)
        preco = 1000 * area + 5000 * quartos + 20000 + noise

        X = pd.DataFrame({'area': area, 'quartos': quartos})
        y = pd.Series(preco)

        builder = ModelBuilder()
        result = builder.build_model(X, y, degree=1)
        assert result.success is True

        avaliando_raw = {'area': 120.0, 'quartos': 3}
        result = builder.add_precision_and_extrapolation(
            result, avaliando_raw, original_df=X, degree=1
        )
        assert result.validation_result is not None
        return result, avaliando_raw

    def test_generates_valid_pdf_bytes_for_a_valid_model(self):
        model_result, avaliando_raw = self._build_valid_model_result()

        pdf_bytes = ResultsGenerator.generate_pdf_report(
            model_result,
            target_col='preco',
            avaliando_raw=avaliando_raw,
            solicitante='Fulano de Tal',
            finalidade='Teste unitário',
        )

        assert pdf_bytes is not None
        assert isinstance(pdf_bytes, bytes)
        assert pdf_bytes.startswith(b'%PDF')
        assert len(pdf_bytes) > 0

    def test_generates_pdf_without_avaliando(self):
        """generate_pdf_report must also work when no avaliando was supplied
        (has_avaliando branch of the template must degrade gracefully)."""
        np.random.seed(1)
        n = 25
        area = np.linspace(50, 200, n)
        preco = 1000 * area + 20000 + np.random.normal(0, 500, n)
        X = pd.DataFrame({'area': area})
        y = pd.Series(preco)

        builder = ModelBuilder()
        result = builder.build_model(X, y, degree=1)
        assert result.success is True

        pdf_bytes = ResultsGenerator.generate_pdf_report(result, target_col='preco')

        assert pdf_bytes is not None
        assert pdf_bytes.startswith(b'%PDF')

    def test_returns_none_without_raising_for_invalid_input(self):
        # A model_result of None is a clearly invalid/incomplete input:
        # every field access inside generate_pdf_report would fail
        # (AttributeError on model_result.validation_result). The function
        # must catch that and return None rather than propagate/raise.
        pdf_bytes = ResultsGenerator.generate_pdf_report(None)
        assert pdf_bytes is None

    def test_returns_none_for_object_missing_expected_attributes(self):
        # Another shape of "clearly invalid/incomplete": something that is
        # not a ModelResult at all and lacks the attributes the report
        # builder needs (e.g. .validation_result).
        class NotAModelResult:
            pass

        pdf_bytes = ResultsGenerator.generate_pdf_report(NotAModelResult())
        assert pdf_bytes is None


class TestChartsParameterAvoidsRecomputation:
    """
    generate_pdf_report must reuse an already-computed `charts` dict instead
    of calling generate_charts() again internally (avoiding computing the
    same charts twice per analysis - once for the websocket payload, once
    for the PDF). When charts is None, it must still fall back to computing
    them internally (standalone/test use).
    """

    def _build_valid_model_result(self):
        np.random.seed(0)
        n = 30
        area = np.linspace(50, 200, n)
        preco = 1000 * area + 20000 + np.random.normal(0, 500, n)
        X = pd.DataFrame({'area': area})
        y = pd.Series(preco)
        builder = ModelBuilder()
        result = builder.build_model(X, y, degree=1)
        assert result.success is True
        return result

    def test_generate_charts_not_called_when_charts_is_provided(self, monkeypatch):
        model_result = self._build_valid_model_result()

        call_count = {"n": 0}
        original = ResultsGenerator.generate_charts

        def counting_generate_charts(*args, **kwargs):
            call_count["n"] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(ResultsGenerator, "generate_charts", staticmethod(counting_generate_charts))

        # Precompute the charts once, exactly as the worker would.
        precomputed_charts = original(model_result)
        assert call_count["n"] == 0  # calling `original` directly bypasses the patched wrapper

        pdf_bytes = ResultsGenerator.generate_pdf_report(
            model_result, target_col='preco', charts=precomputed_charts
        )

        assert pdf_bytes is not None
        assert call_count["n"] == 0, "generate_charts must not be called again when charts is provided"

    def test_generate_charts_called_when_charts_is_none(self, monkeypatch):
        model_result = self._build_valid_model_result()

        call_count = {"n": 0}
        original = ResultsGenerator.generate_charts

        def counting_generate_charts(*args, **kwargs):
            call_count["n"] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(ResultsGenerator, "generate_charts", staticmethod(counting_generate_charts))

        pdf_bytes = ResultsGenerator.generate_pdf_report(
            model_result, target_col='preco', charts=None
        )

        assert pdf_bytes is not None
        assert call_count["n"] > 0, "generate_charts must be called internally when charts is not provided"


class TestMarketSummaryRendering:
    """
    market_summary, when provided, must appear in the rendered report
    (the 'Diagnóstico do Mercado' section, NBR 14653-2 §10.1-f). We verify
    this at the HTML-rendering layer (intercepting weasyprint.HTML's input)
    rather than re-parsing the final PDF bytes, since checking the
    intermediate HTML string is the more practical/direct assertion here.
    """

    def _build_valid_model_result(self):
        np.random.seed(2)
        n = 25
        area = np.linspace(50, 200, n)
        preco = 1000 * area + 20000 + np.random.normal(0, 500, n)
        X = pd.DataFrame({'area': area})
        y = pd.Series(preco)
        builder = ModelBuilder()
        result = builder.build_model(X, y, degree=1)
        assert result.success is True
        return result, X

    def test_market_summary_appears_in_rendered_html(self, monkeypatch):
        model_result, X = self._build_valid_model_result()

        market_summary = ResultsGenerator.build_market_summary(X, variable_cols=['area'])
        assert market_summary is not None
        assert market_summary['variables'][0]['name'] == 'area'

        captured = {}
        real_html_cls = weasyprint.HTML

        class SpyHTML:
            def __init__(self, *args, **kwargs):
                captured['html_string'] = kwargs.get('string')
                self._inner = real_html_cls(*args, **kwargs)

            def write_pdf(self, *args, **kwargs):
                return self._inner.write_pdf(*args, **kwargs)

        monkeypatch.setattr(weasyprint, "HTML", SpyHTML)

        pdf_bytes = ResultsGenerator.generate_pdf_report(
            model_result, target_col='preco', market_summary=market_summary
        )

        assert pdf_bytes is not None
        assert 'html_string' in captured and captured['html_string'] is not None

        html = captured['html_string']
        assert "Descritiva amostral" in html
        assert "não é diagnóstico substantivo completo do mercado" in html.lower()
        assert "area" in html
        # Sanity: the n reported in market_summary must show up too.
        assert str(market_summary['n']) in html

    def test_market_summary_section_absent_when_not_provided(self, monkeypatch):
        model_result, _ = self._build_valid_model_result()

        captured = {}
        real_html_cls = weasyprint.HTML

        class SpyHTML:
            def __init__(self, *args, **kwargs):
                captured['html_string'] = kwargs.get('string')
                self._inner = real_html_cls(*args, **kwargs)

            def write_pdf(self, *args, **kwargs):
                return self._inner.write_pdf(*args, **kwargs)

        monkeypatch.setattr(weasyprint, "HTML", SpyHTML)

        pdf_bytes = ResultsGenerator.generate_pdf_report(
            model_result, target_col='preco', market_summary=None
        )

        assert pdf_bytes is not None
        assert "Descritiva amostral" not in captured['html_string']
