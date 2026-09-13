"""Deterministic equation text from specification + canonical coefficients."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, Dict, List, Optional, Tuple

_LOG_NAMES = frozenset({"log", "ln", "log1p", "log_e", "natural_log", "logarithm"})
_IDENTITY_NAMES = frozenset({"identity", "none", "linear", "original", ""})


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_finite(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _storage_number(value: Optional[float]) -> str:
    if value is None:
        return "null"
    if abs(value) >= 1e15:
        return format(value, ".15g")
    if value.is_integer():
        return str(int(value))
    return format(value, ".15g")


def _display_number(value: Optional[float], decimals: int = 6) -> str:
    if value is None:
        return "—"
    if value.is_integer() and abs(value) < 1e12:
        return str(int(value))
    return f"{value:.{decimals}f}"


def _transform_name(raw: Any) -> str:
    if isinstance(raw, Mapping):
        raw = raw.get("name") or raw.get("kind") or raw.get("transform") or ""
    return str(raw or "").strip().lower()


def _coefficient_pairs(model: Mapping[str, Any]) -> List[Tuple[str, float]]:
    coefficients = model.get("coefficients")
    pairs: List[Tuple[str, float]] = []
    if isinstance(coefficients, Mapping):
        for name, coef in coefficients.items():
            number = _as_finite(coef)
            if number is None:
                continue
            pairs.append((str(name), number))
        return pairs
    if isinstance(coefficients, Sequence) and not isinstance(coefficients, (str, bytes)):
        for item in coefficients:
            if not isinstance(item, Mapping):
                continue
            name = item.get("name") or item.get("variable") or ""
            number = _as_finite(item.get("value") if "value" in item else item.get("coefficient"))
            if not name or number is None:
                continue
            pairs.append((str(name), number))
    return pairs


def _is_intercept(name: str) -> bool:
    compact = name.strip().lower().replace(" ", "")
    return compact in {"const", "intercept", "intercepto", "intercept_const", "(intercept)"}


def _lhs(target_col: str, transform: str) -> str:
    col = target_col or "y"
    if transform in _LOG_NAMES:
        return f"ln({col})"
    if transform and transform not in _IDENTITY_NAMES:
        return f"{transform}({col})"
    return col


def _compose_terms(pairs: Sequence[Tuple[str, float]], *, storage: bool) -> str:
    fmt = _storage_number if storage else _display_number
    intercept_parts = [(n, v) for n, v in pairs if _is_intercept(n)]
    other_parts = [(n, v) for n, v in pairs if not _is_intercept(n)]
    chunks: List[str] = []
    if intercept_parts:
        chunks.append(fmt(intercept_parts[0][1]))
    for name, value in other_parts:
        abs_txt = fmt(abs(value))
        term = f"{abs_txt}·{name}"
        if not chunks:
            chunks.append(term if value >= 0 else f"− {term}")
            continue
        chunks.append(f" + {term}" if value >= 0 else f" − {term}")
    if not chunks:
        return ""
    return "".join(chunks)


def compose_model_equation(
    model: Any,
    *,
    target_col: str = "",
) -> Dict[str, Any]:
    """Compose equation text from provided formula or canonical coefficients.

    Never refits. If the target was transformed, distinguishes the fitting-scale
    equation from the monetary snapshot estimate. Does not print ``exp(...)`` as
    a mean without a retransformation method supplied by the producer.
    """
    block = _as_mapping(model)
    spec = _as_mapping(block.get("specification") or block.get("candidate_spec"))
    transform_state = _as_mapping(block.get("target_transform_state"))
    provided = str(block.get("formula") or spec.get("formula") or "").strip()
    y_transform = _transform_name(
        block.get("y_transformation")
        or spec.get("y_transformation")
        or block.get("target_transform")
        or transform_state.get("name")
    )
    pairs = _coefficient_pairs(block)
    lhs = _lhs(target_col or str(block.get("target_column") or spec.get("target") or ""), y_transform)
    composed_storage = ""
    composed_display = ""
    rhs_storage = ""
    rhs_display = ""
    if pairs:
        rhs_storage = _compose_terms(pairs, storage=True)
        rhs_display = _compose_terms(pairs, storage=False)
        if rhs_storage:
            composed_storage = f"{lhs} = {rhs_storage}"
            composed_display = f"{lhs} = {rhs_display}"

    formula_text = provided or composed_storage
    source = "provided" if provided else ("composed" if composed_storage else "absent")
    log_scale = y_transform in _LOG_NAMES
    identity = y_transform in _IDENTITY_NAMES
    scale_label = "logarítmica" if log_scale else ("original" if identity else (y_transform or "não informada"))

    notes: List[str] = []
    original_scale_formula = ""
    original_scale_formula_storage = ""
    inverse = _as_mapping(transform_state.get("inverse"))
    retransformation_method = str(
        inverse.get("default_method")
        or _as_mapping(block.get("retransformation")).get("method")
        or ("identity" if identity else "")
    ).strip()
    retransformation_estimand = str(
        inverse.get("default_estimand")
        or _as_mapping(block.get("retransformation")).get("estimand")
        or ("E[Y|X]" if identity else "")
    ).strip()
    target_original = target_col or str(block.get("target_column") or spec.get("target") or "y")
    if rhs_storage and identity:
        original_scale_formula = f"{target_original} = {rhs_display}"
        original_scale_formula_storage = f"{target_original} = {rhs_storage}"
    elif rhs_storage and log_scale and retransformation_method == "exponential":
        original_scale_formula = f"{target_original} = exp({rhs_display})"
        original_scale_formula_storage = f"{target_original} = exp({rhs_storage})"
    if formula_text and log_scale:
        if original_scale_formula:
            notes.append(
                "A forma na unidade original aplica a inversa exponencial ao preditor "
                "linear. Método: exponential; estimando: "
                f"{retransformation_estimand or 'exp(E[log Y|X])'}. Essa forma não "
                "é rotulada como média condicional sem correção de viés declarada."
            )
        else:
            notes.append(
                "A equação descreve o ajuste na escala logarítmica, mas o snapshot "
                "não fornece coeficientes e método suficientes para escrever a forma "
                "na unidade original. A inversão simples exp(ajuste) não é apresentada "
                "como média monetária sem método de retransformação e correção de viés "
                "declarados pelo produtor."
            )
    elif formula_text and identity:
        notes.append("A equação descreve o ajuste na escala original do alvo.")
    elif formula_text and y_transform:
        notes.append(
            f"A equação descreve o ajuste na escala '{y_transform}'. A estimativa "
            "monetária do snapshot permanece a do valor pontual informado; não se "
            "recalcula a retransformação nesta minuta."
        )

    x_transforms = spec.get("x_transformations") or block.get("transformations") or {}
    transform_rows: List[Dict[str, str]] = []
    if isinstance(x_transforms, Mapping):
        for name, kind in x_transforms.items():
            kind_name = _transform_name(kind) or "identity"
            if kind_name in _IDENTITY_NAMES:
                continue
            transform_rows.append({"variable": str(name), "transform": kind_name})

    meanings: List[Dict[str, str]] = []
    for name, value in pairs:
        if _is_intercept(name):
            meanings.append(
                {
                    "variable": name,
                    "role": "intercepto",
                    "meaning": "Termo constante da especificação ajustada.",
                    "coefficient_storage": _storage_number(value),
                }
            )
        else:
            meanings.append(
                {
                    "variable": name,
                    "role": "coeficiente",
                    "meaning": (
                        f"Coeficiente da variável '{name}' na especificação ajustada. "
                        "Não é interpretação causal nem elasticidade além do que o snapshot declara."
                    ),
                    "coefficient_storage": _storage_number(value),
                }
            )

    return {
        "formula": formula_text,
        "formula_display": provided or composed_display or formula_text,
        "formula_storage": composed_storage or provided,
        "original_scale_formula": original_scale_formula,
        "original_scale_formula_storage": original_scale_formula_storage,
        "retransformation_method": retransformation_method or None,
        "retransformation_estimand": retransformation_estimand or None,
        "original_scale_present": bool(original_scale_formula),
        "source": source,
        "present": bool(formula_text),
        "y_transformation": y_transform or "identity",
        "fitting_scale": scale_label,
        "log_scale": log_scale,
        "identity_scale": identity,
        "notes": notes,
        "transform_rows": transform_rows,
        "variable_meanings": meanings,
        "coefficient_pairs": pairs,
        "prints_exp_as_mean": False,
    }
