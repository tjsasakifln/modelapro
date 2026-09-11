import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path
from .results import ModelResult
from .config_manager import config
from .logging_manager import logger
import io
import base64

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

GRAU_LABELS = {1: "Grau I", 2: "Grau II", 3: "Grau III"}


def _fmt(value: Optional[float], decimals: int = 2, prefix: str = "") -> str:
    """Formats a numeric value for display in the report, or a dash if missing."""
    if value is None:
        return "—"
    try:
        if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
            return "—"
        return f"{prefix}{value:.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)

class ResultsGenerator:
    @staticmethod
    def generate_charts(model_result: ModelResult) -> Dict[str, str]:
        """
        Generates charts for the model result and returns them as base64 strings.
        """
        charts = {}
        
        if not model_result.success or not model_result.model_metrics:
            return charts
            
        try:
            # 1. Residuals vs Fitted
            plt.figure(figsize=(10, 6))
            sns.scatterplot(x=model_result.fitted_values, y=model_result.residuals)
            plt.axhline(y=0, color='r', linestyle='--')
            plt.xlabel('Fitted Values')
            plt.ylabel('Residuals')
            plt.title('Residuals vs Fitted')
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            charts['residuals_vs_fitted'] = base64.b64encode(buf.getvalue()).decode('utf-8')
            plt.close()
            
            # 2. Histogram of Residuals
            plt.figure(figsize=(10, 6))
            sns.histplot(model_result.residuals, kde=True)
            plt.title('Histogram of Residuals')
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            charts['residuals_hist'] = base64.b64encode(buf.getvalue()).decode('utf-8')
            plt.close()
            
            # 3. Observado vs. Estimado (NBR 14653-2, §8.2.1.4.1 e §10.1-k)
            fitted = np.asarray(model_result.fitted_values, dtype=float)
            residuals = np.asarray(model_result.residuals, dtype=float)
            observed = fitted + residuals

            plt.figure(figsize=(10, 6))
            sns.scatterplot(x=observed, y=fitted)

            min_val = float(min(observed.min(), fitted.min()))
            max_val = float(max(observed.max(), fitted.max()))
            plt.plot([min_val, max_val], [min_val, max_val], color='r', linestyle='--', label='Bissetriz (y = x)')

            plt.xlabel('Preços Observados')
            plt.ylabel('Valores Estimados pelo Modelo')
            plt.title('Observado vs. Estimado')
            plt.legend()

            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            charts['observed_vs_estimated'] = base64.b64encode(buf.getvalue()).decode('utf-8')
            plt.close()

            # 4. QQ Plot
            # Requires statsmodels or scipy
            # Skipping for brevity in this initial pass, but easy to add

        except Exception as e:
            logger.error(f"Error generating charts: {str(e)}")
            
        return charts

    @staticmethod
    def build_market_summary(
        df: pd.DataFrame, variable_cols: Optional[List[str]] = None
    ) -> Optional[dict]:
        """
        Builds the `market_summary` dict consumed by generate_pdf_report's
        "Diagnóstico do Mercado" section (NBR 14653-2 §10.1-f): sample size
        n plus min/mean/max for each candidate base variable, computed
        directly from the real data (never fabricated text).

        Design decision: this is an OPTIONAL convenience helper, not a step
        generate_pdf_report performs internally. The caller (e.g. the
        worker) already knows exactly which columns are the actual
        variáveis-base used as model input; results_generator.py would
        otherwise have to reverse-engineer that from transformed column
        names on the fitted model (e.g. mapping "ln(area)" back to "area"),
        which the caller can trivially avoid by just passing its own column
        list. If None is returned (or market_summary is never passed to
        generate_pdf_report), the report simply omits the section.
        """
        if df is None or df.empty:
            return None
        cols = variable_cols if variable_cols else list(df.select_dtypes(include=[np.number]).columns)
        variables = []
        for col in cols:
            if col not in df.columns:
                continue
            series = pd.to_numeric(df[col], errors='coerce')
            if series.notna().sum() == 0:
                continue
            variables.append({
                "name": col,
                "min": float(series.min()),
                "mean": float(series.mean()),
                "max": float(series.max()),
            })
        if not variables:
            return None
        return {"n": len(df), "variables": variables}

    @staticmethod
    def generate_pdf_report(
        model_result: ModelResult,
        target_col: str = "",
        avaliando_raw: Optional[Dict[str, float]] = None,
        solicitante: str = "",
        finalidade: str = "",
        exhaustive: Optional[bool] = None,
        combinations_tested: Optional[int] = None,
        search_message: str = "",
        market_summary: Optional[dict] = None,
        charts: Optional[Dict[str, str]] = None,
        market_data: Optional[pd.DataFrame] = None,
    ) -> Optional[bytes]:
        """
        Generates the NBR 14653-2 §10.2 (simplified report) PDF for the given
        model, covering items a)-h) and k) of §10.1: identificação do
        solicitante, finalidade, objetivo, pressupostos/ressalvas, método e
        procedimento, especificação da avaliação (Tabela 1, grau de
        fundamentação/precisão), and tratamento dos dados e identificação do
        resultado (fórmula, coeficientes, métricas, gráfico Observado vs.
        Estimado). When avaliando_raw is provided, also reports the point
        estimate, the 80% confidence interval, the campo de arbítrio (±15%)
        and the resulting "valores admissíveis" (Anexo A.10.1.1). When
        exhaustive is False, also discloses that the variable/transformation
        search degraded to the top-N-correlation fallback heuristic and that
        the guarantee of global optimality does not apply to this result
        (transparência metodológica, Anexo A) - pass it (together with
        combinations_tested / search_message) from
        OptimalCombinationResult.exhaustive; leave it as None if that
        information is unavailable.

        market_summary: optional dict (see build_market_summary) rendering
        the "Diagnóstico do Mercado" section (NBR 14653-2 §10.1-f - sample
        size n plus min/mean/max per candidate base variable). Omitted from
        the report entirely when None.

        charts: optional dict of already-generated base64 chart strings
        (same shape as generate_charts()'s return value). When provided, it
        is reused instead of calling generate_charts() again internally -
        avoiding computing the same 3 charts twice per analysis (once for
        the websocket payload, once for the PDF). When None (e.g. standalone
        /test use), generate_charts() is still called internally as before.

        market_data: optional DataFrame with the original market data
        (including identification columns like endereço, if the caller
        merges DataLoadResult.identification_df in) rendered as the
        "Planilha dos Dados de Mercado Utilizados" table (NBR §10.1-i).
        Best-effort/minimal implementation: capped at the first 200 rows to
        keep the PDF a manageable size, with a note when truncated; a
        properly paginated, full planilha is left for a future round.
        Omitted from the report entirely when None.

        Returns the PDF as bytes, or None if generation fails (logged).
        """
        try:
            import jinja2
            import weasyprint

            validation_result = model_result.validation_result

            # --- Especificação da avaliação (Tabela 1) ---
            grau_fundamentacao_label = GRAU_LABELS.get(
                validation_result.grau_fundamentacao if validation_result else None,
                "Não classificado",
            )
            grau_precisao_label = GRAU_LABELS.get(
                validation_result.grau_precisao if validation_result else None,
                "Não calculado",
            )

            # When grau_precisao is None, distinguish WHY: was the IC 80%
            # amplitude computed but out of range for every faixa of Tabela
            # 5 (needs a market-diagnosis-based justification, per the NOTA
            # of Tabela 5), or was it never computed at all (no avaliando
            # informed)?
            grau_precisao_note = None
            amplitude_pct = validation_result.precisao_amplitude_pct if validation_result else None
            if validation_result and validation_result.grau_precisao is None:
                if amplitude_pct is not None and amplitude_pct > 50:
                    grau_precisao_note = (
                        f"Amplitude do IC 80% = {_fmt(amplitude_pct, 1)}% — não classificável "
                        f"quanto à precisão (Tabela 5). Requer justificativa no laudo com base "
                        f"no diagnóstico do mercado (NBR 14653-2, NOTA da Tabela 5)."
                    )
                elif amplitude_pct is None:
                    grau_precisao_note = (
                        "Não calculado — informe as características do imóvel avaliando para "
                        "obter o grau de precisão."
                    )

            item_scores = []
            if validation_result and validation_result.item_scores:
                for it in sorted(validation_result.item_scores, key=lambda i: i.item):
                    item_scores.append({
                        "item": it.item,
                        "description": it.description,
                        "grau_label": GRAU_LABELS.get(it.grau_achieved, "Não atingido"),
                        "detail": it.detail,
                    })

            # --- Fórmula e coeficientes ---
            coef_rows = []
            for var, coef in (model_result.coefficients or {}).items():
                coef_rows.append({
                    "variable": var,
                    "coefficient": _fmt(coef, 6),
                    "pvalue": _fmt((model_result.pvalues or {}).get(var), 4),
                    "vif": _fmt((model_result.vif or {}).get(var), 3) if var != "const" else "—",
                })

            # --- Métricas do modelo ---
            mm = model_result.model_metrics
            metrics = {
                "r2": _fmt(mm.r2, 4) if mm else "—",
                "r2_adjusted": _fmt(mm.r2_adjusted, 4) if mm else "—",
                "f_statistic": _fmt(mm.f_statistic, 3) if mm else "—",
                "f_pvalue": _fmt(mm.f_pvalue, 4) if mm else "—",
                "durbin_watson": _fmt(mm.autocorrelation_durbin_watson, 3) if mm else "—",
            }

            # --- Gráfico Observado vs. Estimado ---
            # Reuse caller-provided charts (already generated once for the
            # websocket payload) instead of paying for generate_charts()
            # again; only fall back to generating internally when nothing
            # was supplied (standalone/test use).
            resolved_charts = charts if charts is not None else ResultsGenerator.generate_charts(model_result)
            chart_b64 = resolved_charts.get("observed_vs_estimated") if resolved_charts else None

            # --- Imóvel avaliando (Anexo A.10.1.1) ---
            has_avaliando = bool(avaliando_raw)
            avaliando_items = list(avaliando_raw.items()) if avaliando_raw else []
            central_estimate = ic80_inferior = ic80_superior = None
            campo_arbitrio_inferior = campo_arbitrio_superior = None
            valores_admissiveis_inferior = valores_admissiveis_superior = None

            if has_avaliando and validation_result:
                details = validation_result.details or {}
                ic80_inferior = details.get("ic80_inferior")
                ic80_superior = details.get("ic80_superior")
                campo_arbitrio_inferior = details.get("campo_arbitrio_inferior")
                campo_arbitrio_superior = details.get("campo_arbitrio_superior")
                valores_admissiveis_inferior = validation_result.valores_admissiveis_inferior
                valores_admissiveis_superior = validation_result.valores_admissiveis_superior

                # central_estimate is not stored directly; derive it from the
                # campo de arbítrio bounds already computed by
                # NBRValidator.finalize_precision_and_extrapolation
                # (campo_arbitrio_inf/sup = central * (1 -/+ CAMPO_ARBITRIO)).
                estimates = []
                if campo_arbitrio_inferior is not None:
                    estimates.append(campo_arbitrio_inferior / (1 - config.CAMPO_ARBITRIO))
                if campo_arbitrio_superior is not None:
                    estimates.append(campo_arbitrio_superior / (1 + config.CAMPO_ARBITRIO))
                if estimates:
                    central_estimate = sum(estimates) / len(estimates)

            # --- Diagnóstico do Mercado (NBR 14653-2 §10.1-f) ---
            market_summary_rows = []
            market_summary_n = None
            if market_summary and market_summary.get("variables"):
                market_summary_n = market_summary.get("n")
                for v in market_summary["variables"]:
                    market_summary_rows.append({
                        "name": v.get("name"),
                        "min": _fmt(v.get("min"), 2),
                        "mean": _fmt(v.get("mean"), 2),
                        "max": _fmt(v.get("max"), 2),
                    })

            # --- Planilha dos Dados de Mercado Utilizados (NBR §10.1-i) ---
            # Best-effort/minimal: capped at 200 rows so a large dataset
            # cannot blow up the PDF; a properly paginated full planilha is
            # left for a future round (see docstring).
            market_data_table = None
            if market_data is not None and not market_data.empty:
                MAX_MARKET_DATA_ROWS = 200
                display_df = market_data.head(MAX_MARKET_DATA_ROWS)
                market_data_table = {
                    "columns": [str(c) for c in display_df.columns],
                    "rows": [
                        ["" if pd.isna(v) else v for v in row]
                        for row in display_df.itertuples(index=False)
                    ],
                    "truncated": len(market_data) > MAX_MARKET_DATA_ROWS,
                    "shown_rows": len(display_df),
                    "total_rows": len(market_data),
                }

            context = {
                "app_name": config.APP_NAME,
                "data_referencia": datetime.now().strftime("%d/%m/%Y"),
                "solicitante": solicitante,
                "finalidade": finalidade,
                "target_col": target_col,
                "grau_fundamentacao_label": grau_fundamentacao_label,
                "grau_precisao_label": grau_precisao_label,
                "grau_precisao_note": grau_precisao_note,
                "item_scores": item_scores,
                "formula": model_result.formula,
                "coef_rows": coef_rows,
                "metrics": metrics,
                "chart_b64": chart_b64,
                "has_avaliando": has_avaliando,
                "avaliando_items": avaliando_items,
                "central_estimate": _fmt(central_estimate, 2),
                "ic80_inferior": _fmt(ic80_inferior, 2),
                "ic80_superior": _fmt(ic80_superior, 2),
                "campo_arbitrio_inferior": _fmt(campo_arbitrio_inferior, 2),
                "campo_arbitrio_superior": _fmt(campo_arbitrio_superior, 2),
                "valores_admissiveis_inferior": _fmt(valores_admissiveis_inferior, 2),
                "valores_admissiveis_superior": _fmt(valores_admissiveis_superior, 2),
                "market_summary_rows": market_summary_rows,
                "market_summary_n": market_summary_n,
                "market_data_table": market_data_table,
                # Transparência metodológica (Anexo A): only rendered when
                # the search's exhaustiveness is actually known.
                # exhaustive=False means the search degraded to the
                # top-N-correlation fallback heuristic and the guarantee of
                # global optimality over the full search space does NOT
                # apply to this result - this must reach the report, not
                # just server logs.
                "exhaustive": exhaustive,
                "combinations_tested": combinations_tested,
                "search_message": search_message,
            }

            env = jinja2.Environment(
                loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
                autoescape=True,
            )
            template = env.get_template("report.html")
            html_content = template.render(**context)

            pdf_bytes = weasyprint.HTML(string=html_content).write_pdf()
            return pdf_bytes

        except Exception as e:
            logger.error(f"Error generating PDF report: {str(e)}")
            return None
