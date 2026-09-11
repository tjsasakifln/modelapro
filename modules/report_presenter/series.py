"""Alignment and scale checks for residual/fitted series before plotting."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Dict, List, Optional, Tuple

_LOG_SCALES = frozenset({"log", "ln", "log1p", "logarithmic", "logarítmica", "logarithmica"})
_ORIGINAL_SCALES = frozenset({"original", "identity", "linear", "monetary", "price", "original_scale"})


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _finite_array(values: Any) -> Tuple[Optional[List[float]], Optional[str]]:
    if values is None:
        return None, None
    seq = _as_list(values)
    out: List[float] = []
    for item in seq:
        if item is None or isinstance(item, bool):
            return None, "série contém valor não numérico"
        try:
            number = float(item)
        except (TypeError, ValueError):
            return None, "série contém valor não numérico"
        if not math.isfinite(number):
            return None, "série contém NaN ou infinito"
        out.append(number)
    return out, None


def _ids(values: Any) -> List[str]:
    return [str(item) for item in _as_list(values)]


def _shifted_by_one(left: Sequence[str], right: Sequence[str]) -> bool:
    if len(left) != len(right) or len(left) < 2:
        return False
    if list(left) == list(right):
        return False
    return list(left[1:]) == list(right[:-1]) or list(left[:-1]) == list(right[1:])


def assess_chart_series(
    report_context: Any,
    *,
    used_row_ids: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Return plottable series only when lengths, ids and scale line up.

    Missing series → explained absence (not a calculation defect).
    Shifted or length-mismatched series → warning, do not plot, preserve calculation.
    """
    ctx = _as_mapping(report_context)
    fitted, fitted_err = _finite_array(ctx.get("fitted_values"))
    resid, resid_err = _finite_array(ctx.get("residuals"))
    observed, observed_err = _finite_array(ctx.get("observed_values"))
    row_ids = _ids(ctx.get("series_row_ids")) if ctx.get("series_row_ids") is not None else None
    used_ids = _ids(used_row_ids) if used_row_ids is not None else []
    scale = str(ctx.get("series_scale") or "").strip().lower()
    unit = str(ctx.get("series_unit") or "").strip()

    result: Dict[str, Any] = {
        "available": False,
        "plot": False,
        "reason": "",
        "warning": None,
        "fitted": None,
        "residuals": None,
        "observed": None,
        "row_ids": row_ids,
        "series_scale": scale or None,
        "series_unit": unit or None,
        "log_scale": scale in _LOG_SCALES,
        "original_scale": scale in _ORIGINAL_SCALES or not scale,
        "axis_observed": "Valores observados",
        "axis_fitted": "Valores ajustados",
        "axis_resid": "Resíduos",
        "synthetic_label": bool(ctx.get("synthetic") or ctx.get("fixture_synthetic")),
    }

    missing = []
    if fitted is None:
        missing.append("fitted_values")
    if resid is None:
        missing.append("residuals")
    if not missing and fitted is not None and resid is not None:
        pass
    if fitted is None and resid is None and observed is None:
        result["reason"] = (
            "Os gráficos de resíduos e ajustamento não constam desta minuta porque "
            "as séries alinhadas não foram fornecidas no contexto do relatório. "
            "O cálculo do snapshot permanece inalterado."
        )
        return result

    if fitted is None or resid is None:
        result["reason"] = (
            "As séries de gráfico estão incompletas "
            f"({', '.join(missing) or 'fitted_values/residuals'} ausentes). "
            "Nenhum gráfico foi inventado. O cálculo do snapshot permanece inalterado."
        )
        return result

    if fitted_err or resid_err or observed_err:
        result["warning"] = {
            "code": "REPORT_CHARTS_INVALID_VALUES",
            "message": fitted_err or resid_err or observed_err,
        }
        result["reason"] = (
            "As séries de gráfico contêm valores não finitos e não foram plotadas. "
            "O cálculo do snapshot permanece inalterado."
        )
        return result

    n_fit, n_res = len(fitted), len(resid)
    if n_fit != n_res:
        result["warning"] = {
            "code": "REPORT_CHARTS_LENGTH_MISMATCH",
            "message": (
                f"Comprimentos incompatíveis: fitted_values={n_fit}, residuals={n_res}."
            ),
        }
        result["reason"] = (
            "As séries de gráfico têm comprimentos incompatíveis e não foram plotadas. "
            "O cálculo do snapshot permanece inalterado."
        )
        return result

    if observed is not None and len(observed) != n_fit:
        result["warning"] = {
            "code": "REPORT_CHARTS_LENGTH_MISMATCH",
            "message": (
                f"Comprimentos incompatíveis: observed_values={len(observed)}, fitted_values={n_fit}."
            ),
        }
        result["reason"] = (
            "A série observada não tem o mesmo comprimento dos ajustados e não foi plotada. "
            "O cálculo do snapshot permanece inalterado."
        )
        return result

    if row_ids is not None:
        if len(row_ids) != n_fit:
            result["warning"] = {
                "code": "REPORT_CHARTS_ID_MISMATCH",
                "message": (
                    f"series_row_ids tem {len(row_ids)} identificadores para {n_fit} pontos."
                ),
            }
            result["reason"] = (
                "Os identificadores das séries não alinham com os valores e os gráficos "
                "não foram gerados. O cálculo do snapshot permanece inalterado."
            )
            return result
        if used_ids and list(row_ids) != list(used_ids):
            shifted = _shifted_by_one(row_ids, used_ids)
            result["warning"] = {
                "code": "REPORT_CHARTS_SHIFTED" if shifted else "REPORT_CHARTS_ID_MISMATCH",
                "message": (
                    "series_row_ids deslocados em uma linha em relação a used_row_ids"
                    if shifted
                    else "series_row_ids não coincidem com used_row_ids da amostra utilizada"
                ),
            }
            result["reason"] = (
                "As séries de gráfico estão desalinhadas em relação à amostra utilizada "
                "e não foram plotadas. O cálculo do snapshot permanece inalterado."
            )
            return result

    if scale in _LOG_SCALES:
        result["axis_observed"] = "Valores observados (escala de ajuste logarítmica)"
        result["axis_fitted"] = "Valores ajustados (escala logarítmica)"
        result["axis_resid"] = "Resíduos (escala logarítmica)"
        result["log_scale"] = True
        result["original_scale"] = False
    elif unit:
        result["axis_observed"] = f"Valores observados ({unit})"
        result["axis_fitted"] = f"Valores ajustados ({unit})"

    result["available"] = True
    result["plot"] = True
    result["fitted"] = fitted
    result["residuals"] = resid
    result["observed"] = observed
    result["reason"] = ""
    return result
