"""Verifiable calculators for ABNT NBR 14653-2:2011 tabled rules.

This module does not reproduce protected table text. Each function cites
edition, item and clause and operates on explicit numeric inputs.

Item 4 (Tabela 1) requires BOTH:
  (a) measure condition on the characteristic vs sample frontier;
  (b) original-unit |Δvalue| vs the prediction with the variable(s)
      clamped to the sample frontier (15% Grau II / 20% Grau I,
      de per si and simultaneously for Grau I).
Measure-only admission is not a pass.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


EDITION_PART2 = "ABNT NBR 14653-2:2011"
EDITION_PART1_2001 = "ABNT NBR 14653-1:2001"
EDITION_PART1_2019 = "ABNT NBR 14653-1:2019"

CONTRACT_VERSION = "MP/1"

EVIDENCE_CALCULATED = "calculated"
EVIDENCE_DECLARED = "declared"
EVIDENCE_VERIFIED = "verified"
EVIDENCE_PENDING = "pending"
EVIDENCE_NOT_APPLICABLE = "not_applicable"

PRECISAO_NOT_COMPUTED = "not_computed"
PRECISAO_CLASSIFIED = "classified"
PRECISAO_UNCLASSIFIED = "unclassified"
PRECISAO_ERROR = "error"

VS_VERIFIED_RULES_LISTED = "verified_rules_listed"
VS_PARTIAL = "partial"
VS_PENDING = "pending"

KIND_QUANTITATIVE = "quantitative"
KIND_DICHOTOMOUS = "dichotomous"
KIND_ALLOCATED_CODE = "allocated_code"
KIND_ADJUSTED_CODE = "adjusted_code"
KIND_CATEGORICAL = "categorical"

QUALITATIVE_KINDS = frozenset(
    {
        KIND_DICHOTOMOUS,
        KIND_ALLOCATED_CODE,
        KIND_ADJUSTED_CODE,
        KIND_CATEGORICAL,
    }
)

# Tabela 1 item 4 (a): not more than 100% above sample max, not below half of sample min.
MEASURE_UPPER_FACTOR = 2.0
MEASURE_LOWER_FACTOR = 0.5
# Tabela 1 item 4 (b)
VALUE_LIMIT_GRAU_II = 0.15
VALUE_LIMIT_GRAU_I = 0.20

# NBR 14653-2:2011 8.2.1.5.1 (campo de arbítrio ±15% around central tendency)
CAMPO_ARBITRIO = 0.15

# Tabela 5
PRECISAO_LIM_III = 30.0
PRECISAO_LIM_II = 40.0
PRECISAO_LIM_I = 50.0

# Item 5 (teste t, two-tailed)
ITEM5_LIM_III = 0.10
ITEM5_LIM_II = 0.20
ITEM5_LIM_I = 0.30

# Item 6 (teste F)
ITEM6_LIM_III = 0.01
ITEM6_LIM_II = 0.02
ITEM6_LIM_I = 0.05

# Tabela 2
TABELA2_PONTOS_III = 16
TABELA2_PONTOS_II = 10
TABELA2_PONTOS_I = 6

INTERCEPT_COL_NAMES = frozenset({"const", "intercept", "constante", "Intercept", "CONST"})

POS_IN_SAMPLE = "in_sample"
POS_EXTENDED = "extended"
POS_OUT = "out_of_measure"
POS_INVALID = "invalid"
POS_NOT_APPLICABLE = "not_applicable"


def is_finite_number(value: Any) -> bool:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(x)


def as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x


def make_issue(
    code: str,
    message: str,
    *,
    severity: str = "warning",
    origin: str = "C03",
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


def relative_difference_pct(y_subject: Any, y_frontier: Any) -> Tuple[Optional[float], Optional[str]]:
    """|ŷ_subject − ŷ_frontier| / |ŷ_frontier| as percent.

    Returns (delta_pct, error_code). error_code is set when the ratio is
    undefined or either prediction is non-finite. Never substitutes 0.
    """
    ys = as_float(y_subject)
    yf = as_float(y_frontier)
    if ys is None:
        return None, "non_finite_subject"
    if yf is None:
        return None, "non_finite_frontier"
    if yf == 0.0:
        return None, "zero_denominator"
    return abs(ys - yf) / abs(yf) * 100.0, None


def measure_extended_bounds(sample_min: float, sample_max: float) -> Tuple[Optional[float], Optional[float], List[str]]:
    """Return (ext_min, ext_max, reasons) for the item-4 measure condition.

    The 0.5·min / 2·max faixa is a ratio-scale rule for positive physical
    measures (Tabela 1 item 4 (a)). It is not applied to non-positive
    domains; those reasons are returned so the caller can pend rather than
    invent an extension.
    """
    reasons: List[str] = []
    ext_max: Optional[float] = None
    ext_min: Optional[float] = None
    if sample_max > 0.0:
        ext_max = MEASURE_UPPER_FACTOR * sample_max
    else:
        reasons.append(
            "limite superior 2×max não é justificável para sample_max <= 0 "
            "(NBR 14653-2:2011 Tabela 1 item 4 (a); domínio não é de razão positiva)"
        )
    if sample_min > 0.0:
        ext_min = MEASURE_LOWER_FACTOR * sample_min
    elif sample_min == 0.0:
        ext_min = 0.0
    else:
        reasons.append(
            "limite inferior 0,5×min não é justificável para sample_min < 0 "
            "(NBR 14653-2:2011 Tabela 1 item 4 (a); não inventar extensão de faixa)"
        )
    return ext_min, ext_max, reasons


def measure_position(
    value: Any,
    sample_min: Any,
    sample_max: Any,
) -> Dict[str, Any]:
    """Locate `value` vs [min, max] and the verified extended measure interval."""
    val = as_float(value)
    vmin = as_float(sample_min)
    vmax = as_float(sample_max)
    out: Dict[str, Any] = {
        "value": val,
        "sample_min": vmin,
        "sample_max": vmax,
        "ext_min": None,
        "ext_max": None,
        "position": POS_INVALID,
        "reasons": [],
    }
    if val is None or vmin is None or vmax is None:
        out["reasons"].append("valor, sample_min ou sample_max ausente ou não finito")
        return out
    if vmin > vmax:
        out["reasons"].append("sample_min > sample_max")
        return out

    ext_min, ext_max, ext_reasons = measure_extended_bounds(vmin, vmax)
    out["ext_min"] = ext_min
    out["ext_max"] = ext_max
    out["reasons"].extend(ext_reasons)

    if vmin <= val <= vmax:
        out["position"] = POS_IN_SAMPLE
        return out

    # Outside sample: extended admission only where the bound is defined.
    if val > vmax:
        if ext_max is None:
            out["position"] = POS_NOT_APPLICABLE
            return out
        if val <= ext_max:
            out["position"] = POS_EXTENDED
            return out
        out["position"] = POS_OUT
        return out

    # val < vmin
    if ext_min is None:
        out["position"] = POS_NOT_APPLICABLE
        return out
    if val >= ext_min:
        out["position"] = POS_EXTENDED
        return out
    out["position"] = POS_OUT
    return out


def clamp_to_sample_frontier(value: float, sample_min: float, sample_max: float) -> float:
    if value < sample_min:
        return sample_min
    if value > sample_max:
        return sample_max
    return value


def _axis_name(axis: Mapping[str, Any]) -> str:
    name = axis.get("name") or axis.get("variable")
    return str(name) if name is not None else ""


def _axis_kind(axis: Mapping[str, Any]) -> str:
    kind = axis.get("kind")
    if kind:
        return str(kind)
    return KIND_QUANTITATIVE


def _call_predict_original(
    predict_original: Callable[[Mapping[str, Any]], Any],
    subject_raw: Mapping[str, Any],
) -> Tuple[Optional[float], Optional[Dict[str, Any]]]:
    try:
        raw = dict(subject_raw)
        result = predict_original(raw)
    except Exception as exc:  # callback is user/pipeline-provided
        return None, make_issue(
            "predict_original_failed",
            f"predict_original levantou {type(exc).__name__}: {exc}",
            severity="error",
            evidence={"exception_type": type(exc).__name__},
        )
    if isinstance(result, Mapping):
        result = result.get("point", result.get("value"))
    y = as_float(result)
    if y is None:
        return None, make_issue(
            "predict_original_non_finite",
            "predict_original devolveu valor ausente ou não finito; grau do item 4 não é atribuído",
            severity="error",
            evidence={"raw_result": None if result is None else str(result)},
        )
    return y, None


def _qualitative_membership(axis: Mapping[str, Any], value: Any) -> Tuple[str, str]:
    """Return (status, reason) for qualitative axes (Anexo A.5–A.7).

    status: in_sample | forbidden | pending
    Numeric 0.5·min / 2·max faixa is never invented for these kinds.
    """
    kind = _axis_kind(axis)
    observed = axis.get("sample_values") or axis.get("categories") or axis.get("observed_values")
    if observed is None:
        vmin = as_float(axis.get("sample_min"))
        vmax = as_float(axis.get("sample_max"))
        val = as_float(value)
        if kind == KIND_DICHOTOMOUS and val is not None and vmin is not None and vmax is not None:
            # Dichotomous: only the two observed endpoints; no interpolation/extrapolation (A.5).
            if val == vmin or val == vmax:
                if vmin == vmax and val == vmin:
                    return "in_sample", "valor dicotômico coincide com o único valor amostral"
                if vmin != vmax and (val == vmin or val == vmax):
                    return "in_sample", "valor dicotômico coincide com um dos valores amostrais"
            return (
                "forbidden",
                "Anexo A.5: vedada extrapolação ou interpolação de variável dicotômica; "
                "faixa numérica ampliada não se aplica",
            )
        return (
            "pending",
            f"conjunto amostral discreto não informado para kind={kind}; "
            "não se inventa faixa numérica (Anexo A.5–A.7)",
        )

    observed_list = list(observed)
    if value in observed_list:
        return "in_sample", "valor presente no conjunto amostral observado"

    if kind == KIND_ADJUSTED_CODE:
        return (
            "forbidden",
            "Anexo A.7: vedada extrapolação ou interpolação de códigos ajustados",
        )
    if kind == KIND_DICHOTOMOUS:
        return (
            "forbidden",
            "Anexo A.5: vedada extrapolação ou interpolação de variável dicotômica",
        )
    if kind == KIND_CATEGORICAL:
        return (
            "forbidden",
            "categoria do avaliando ausente da amostra; faixa numérica não se aplica",
        )
    # allocated_code: extrapolation beyond the constructed scale is forbidden (A.6);
    # missing interior scale positions are allowed in the sample, but only if the
    # constructed scale is known. Without the scale, do not invent.
    vmin = as_float(axis.get("sample_min"))
    vmax = as_float(axis.get("sample_max"))
    val = as_float(value)
    scale = axis.get("scale_values")
    if scale is not None and value in list(scale):
        return (
            "pending",
            "Anexo A.6: código alocado na escala construída mas não observado na amostra; "
            "interpolação de códigos alocados não é auto-validada aqui",
        )
    if val is not None and vmin is not None and vmax is not None and not (vmin <= val <= vmax):
        return (
            "forbidden",
            "Anexo A.6: vedada a extrapolação de variáveis expressas por códigos alocados",
        )
    return (
        "pending",
        "Anexo A.6: sem escala construída explícita, não se inventa faixa para código alocado",
    )


def classify_item2_quantidade_dados(n: Any, k: Any) -> Dict[str, Any]:
    """Tabela 1 item 2: n ≥ 3(k+1) / 4(k+1) / 6(k+1)."""
    source = {
        "edition": EDITION_PART2,
        "item": 2,
        "clause": "Tabela 1 item 2",
        "status": "verified",
    }
    n_f = as_float(n)
    k_f = as_float(k)
    if n_f is None or k_f is None:
        return {
            "grade": None,
            "evidence_status": EVIDENCE_PENDING,
            "n": n,
            "k": k,
            "thresholds": None,
            "detail": "n ou k efetivo ausente; ausência não vale aprovação (item 2).",
            "source": source,
        }
    n_i = int(n_f)
    k_i = int(k_f)
    if k_i < 0 or n_i < 0:
        return {
            "grade": None,
            "evidence_status": EVIDENCE_PENDING,
            "n": n_i,
            "k": k_i,
            "thresholds": None,
            "detail": "n ou k negativo; item 2 não classificado.",
            "source": source,
        }
    t1, t2, t3 = 3 * (k_i + 1), 4 * (k_i + 1), 6 * (k_i + 1)
    if n_i >= t3:
        grade = 3
    elif n_i >= t2:
        grade = 2
    elif n_i >= t1:
        grade = 1
    else:
        grade = 0
    return {
        "grade": grade,
        "evidence_status": EVIDENCE_CALCULATED,
        "n": n_i,
        "k": k_i,
        "thresholds": {"grau_i": t1, "grau_ii": t2, "grau_iii": t3},
        "detail": f"n={n_i}, k={k_i}. Mínimos: I={t1}, II={t2}, III={t3}.",
        "source": source,
    }


def classify_item5_significancia_regressores(
    pvalues: Optional[Mapping[str, Any]],
    *,
    automatic_selection: bool = False,
) -> Dict[str, Any]:
    """Tabela 1 item 5: worst (largest) regressor p-value; intercept excluded."""
    source = {
        "edition": EDITION_PART2,
        "item": 5,
        "clause": "Tabela 1 item 5",
        "status": "verified",
    }
    limitations: List[str] = []
    if automatic_selection:
        limitations.append(
            "p-valores obtidos após seleção automática de variáveis; a inferência "
            "nominal da Tabela 1 item 5 não é inalterada por essa busca. O critério "
            "tabelado (10%/20%/30%) não foi modificado."
        )
    if not pvalues:
        return {
            "grade": 0,
            "worst_p": None,
            "evidence_status": EVIDENCE_CALCULATED,
            "detail": "Sem regressores.",
            "limitations": limitations,
            "source": source,
        }
    regressor_pvals: List[float] = []
    non_finite = []
    for var, p in pvalues.items():
        if str(var) in INTERCEPT_COL_NAMES or str(var).lower() == "const":
            continue
        pf = as_float(p)
        if pf is None:
            non_finite.append(str(var))
            continue
        regressor_pvals.append(pf)
    if non_finite and not regressor_pvals:
        return {
            "grade": None,
            "worst_p": None,
            "evidence_status": EVIDENCE_PENDING,
            "detail": f"p-valores não finitos em {non_finite}; item 5 não classificado.",
            "limitations": limitations,
            "source": source,
        }
    if not regressor_pvals:
        return {
            "grade": 0,
            "worst_p": None,
            "evidence_status": EVIDENCE_CALCULATED,
            "detail": "Sem regressores (apenas intercepto).",
            "limitations": limitations,
            "source": source,
        }
    worst_p = max(regressor_pvals)
    if worst_p <= ITEM5_LIM_III:
        grade = 3
    elif worst_p <= ITEM5_LIM_II:
        grade = 2
    elif worst_p <= ITEM5_LIM_I:
        grade = 1
    else:
        grade = 0
    return {
        "grade": grade,
        "worst_p": worst_p,
        "evidence_status": EVIDENCE_CALCULATED,
        "detail": f"Pior p-valor entre regressores: {worst_p:.4f}.",
        "limitations": limitations,
        "source": source,
    }


def classify_item6_significancia_global(f_pvalue: Any) -> Dict[str, Any]:
    """Tabela 1 item 6: F-test p-value. III≤1%; II≤2%; I≤5%."""
    source = {
        "edition": EDITION_PART2,
        "item": 6,
        "clause": "Tabela 1 item 6",
        "status": "verified",
    }
    p = as_float(f_pvalue)
    if p is None:
        return {
            "grade": None,
            "evidence_status": EVIDENCE_PENDING,
            "f_pvalue": f_pvalue,
            "detail": "p-valor do teste F ausente ou não finito; item 6 não classificado.",
            "source": source,
        }
    if p <= ITEM6_LIM_III:
        grade = 3
    elif p <= ITEM6_LIM_II:
        grade = 2
    elif p <= ITEM6_LIM_I:
        grade = 1
    else:
        grade = 0
    return {
        "grade": grade,
        "evidence_status": EVIDENCE_CALCULATED,
        "f_pvalue": p,
        "detail": f"F-prob (p-valor do teste F): {p:.4f}.",
        "source": source,
    }


def classify_fundamentacao(item_scores: Mapping[int, Any]) -> Dict[str, Any]:
    """Tabela 2: pontos mínimos E itens obrigatórios.

    Missing/pending grades are not treated as approval. They contribute 0 to
    the sum for display but block any grau that requires that item.
    """
    source = {
        "edition": EDITION_PART2,
        "clause": "Tabela 2 / 9.2.1.6",
        "status": "verified",
    }
    pending_items = [i for i in range(1, 7) if item_scores.get(i) is None]
    numeric = {i: int(item_scores.get(i) or 0) for i in range(1, 7)}
    pontos = sum(numeric.values())
    obrigatorios = [numeric[i] for i in (2, 4, 5, 6)]
    complementares = [numeric[i] for i in (1, 3)]
    todos = [numeric[i] for i in range(1, 7)]

    grade: Optional[int] = None
    if pending_items:
        # Absence is not approval of the overall grau.
        grade = None
        detail = (
            f"Itens {pending_items} pendentes; enquadramento Tabela 2 não é aprovado "
            f"por ausência (pontos conhecidos={pontos})."
        )
    elif pontos >= TABELA2_PONTOS_III and all(v >= 3 for v in obrigatorios) and all(v >= 2 for v in complementares):
        grade = 3
        detail = f"Tabela 2: Grau III (pontos={pontos})."
    elif pontos >= TABELA2_PONTOS_II and all(v >= 2 for v in obrigatorios) and all(v >= 1 for v in complementares):
        grade = 2
        detail = f"Tabela 2: Grau II (pontos={pontos})."
    elif pontos >= TABELA2_PONTOS_I and all(v >= 1 for v in todos):
        grade = 1
        detail = f"Tabela 2: Grau I (pontos={pontos})."
    else:
        grade = None
        detail = f"Tabela 2: não classificado (pontos={pontos})."

    return {
        "grade": grade,
        "points": pontos,
        "pending_items": pending_items,
        "detail": detail,
        "source": source,
        "evidence_status": EVIDENCE_PENDING if pending_items else EVIDENCE_CALCULATED,
    }


def classify_precisao(amplitude_pct: Any) -> Dict[str, Any]:
    """Tabela 5: 80% CI amplitude around the central-tendency estimate.

    status is exactly not_computed | classified | unclassified | error.
    Amplitude > 50% is unclassified (não classificável), not an error.
    Non-finite amplitude is error. Missing is not_computed.
    """
    source = {
        "edition": EDITION_PART2,
        "clause": "Tabela 5 / 9.2.3",
        "status": "verified",
    }
    if amplitude_pct is None:
        return {
            "status": PRECISAO_NOT_COMPUTED,
            "grade": None,
            "amplitude_pct": None,
            "detail": "Amplitude do IC de 80% não calculada (not_computed).",
            "source": source,
        }
    amp = as_float(amplitude_pct)
    if amp is None:
        return {
            "status": PRECISAO_ERROR,
            "grade": None,
            "amplitude_pct": None,
            "detail": "Amplitude não finita; precisão em erro (não se substitui por zero).",
            "source": source,
        }
    if amp < 0:
        return {
            "status": PRECISAO_ERROR,
            "grade": None,
            "amplitude_pct": amp,
            "detail": "Amplitude negativa; precisão em erro.",
            "source": source,
        }
    if amp <= PRECISAO_LIM_III:
        grade, status = 3, PRECISAO_CLASSIFIED
        detail = f"Amplitude {amp:.2f}% <= 30% (Grau III)."
    elif amp <= PRECISAO_LIM_II:
        grade, status = 2, PRECISAO_CLASSIFIED
        detail = f"Amplitude {amp:.2f}% <= 40% (Grau II)."
    elif amp <= PRECISAO_LIM_I:
        grade, status = 1, PRECISAO_CLASSIFIED
        detail = f"Amplitude {amp:.2f}% <= 50% (Grau I)."
    else:
        grade, status = None, PRECISAO_UNCLASSIFIED
        detail = (
            f"Amplitude {amp:.2f}% > 50%: não classificável quanto à precisão. "
            f"Requer justificativa no laudo (item 9.2.3 / NOTA da Tabela 5)."
        )
    return {
        "status": status,
        "grade": grade,
        "amplitude_pct": amp,
        "detail": detail,
        "source": source,
    }


def classify_documentary_item(
    item: int,
    declared_grade: Any,
    provenance: Any,
    *,
    description: str,
) -> Dict[str, Any]:
    """Items 1 and 3 are documentary. A declared grade is not verification."""
    source = {
        "edition": EDITION_PART2,
        "item": item,
        "clause": f"Tabela 1 item {item}",
        "status": "verified",
    }
    has_prov = bool(provenance) and (
        not isinstance(provenance, Mapping)
        or any(provenance.values())
    )
    if declared_grade is None:
        return {
            "item": item,
            "description": description,
            "grade": None,
            "points": None,
            "evidence_status": EVIDENCE_PENDING,
            "provenance": provenance,
            "detail": (
                f"Item {item} documental não informado; ausência não vale aprovação. "
                "Um controle de UI sem proveniência não verifica este item."
            ),
            "source": source,
        }
    try:
        grade = int(declared_grade)
    except (TypeError, ValueError):
        return {
            "item": item,
            "description": description,
            "grade": None,
            "points": None,
            "evidence_status": EVIDENCE_PENDING,
            "provenance": provenance,
            "detail": f"Item {item}: grau declarado inválido ({declared_grade!r}).",
            "source": source,
        }
    if grade < 0 or grade > 3:
        return {
            "item": item,
            "description": description,
            "grade": None,
            "points": None,
            "evidence_status": EVIDENCE_PENDING,
            "provenance": provenance,
            "detail": f"Item {item}: grau declarado fora de 0–3.",
            "source": source,
        }
    if has_prov:
        status = EVIDENCE_DECLARED
        detail = (
            f"Grau {grade} declarado com proveniência registrada; não equivale a "
            "verificação independente do item documental."
        )
    else:
        status = EVIDENCE_DECLARED
        detail = (
            f"Grau {grade} declarado sem proveniência verificável. "
            "Selectbox/UI não transforma declaração em evidência verificada."
        )
    return {
        "item": item,
        "description": description,
        "grade": grade,
        "points": grade,
        "evidence_status": status,
        "provenance": provenance if has_prov else None,
        "detail": detail,
        "source": source,
    }


def interval_roles(
    *,
    central_estimate: Any = None,
    mean_ci80: Optional[Mapping[str, Any]] = None,
    prediction_interval: Optional[Mapping[str, Any]] = None,
    estimand: Optional[str] = None,
    adopted_estimator: Optional[str] = None,
    campo_arbitrio: float = CAMPO_ARBITRIO,
) -> Dict[str, Any]:
    """Distinguish IC da média, intervalo de predição, campo de arbítrio, admissíveis.

    Admissible intersection is only *calculated* when the use-condition is
    declared (A.10.1.1 central tendency + footnote 9 CI vs PI). Otherwise
    candidate intervals are reported and admissible stays pending.
    Valor arbitrado (A.10.1.2) is not auto-completed.
    """
    source_campo = {
        "edition": EDITION_PART2,
        "clause": "8.2.1.5.1",
        "also": f"{EDITION_PART1_2001} 3.8; {EDITION_PART1_2019} 3.1.9",
        "status": "verified",
    }
    source_adm = {
        "edition": EDITION_PART2,
        "clause": "Anexo A.10.1.1 / A.10.1.2",
        "status": "verified",
    }
    central = as_float(central_estimate)
    arbitration = None
    if central is not None:
        arbitration = {
            "lower": central * (1.0 - campo_arbitrio),
            "upper": central * (1.0 + campo_arbitrio),
            "amplitude": campo_arbitrio,
            "source": source_campo,
        }

    def _pair(interval: Optional[Mapping[str, Any]]) -> Optional[Dict[str, float]]:
        if not interval:
            return None
        lo = as_float(interval.get("lower"))
        hi = as_float(interval.get("upper"))
        if lo is None or hi is None:
            return None
        return {"lower": lo, "upper": hi}

    ci = _pair(mean_ci80)
    pi = _pair(prediction_interval)

    estimand_norm = (estimand or "").strip().lower() or None
    adopted_norm = (adopted_estimator or "").strip().lower() or None

    market_tokens = {"market_value", "valor_de_mercado", "tendencia_central", "central_tendency"}
    price_tokens = {"price", "preco", "precos", "prices"}
    central_tokens = {"central_tendency", "tendencia_central", "estimativa_de_tendencia_central"}
    arb_tokens = {"arbitrated", "arbitrado", "valor_arbitrado"}

    admissible = None
    admissible_status = EVIDENCE_PENDING
    reasons: List[str] = []

    if adopted_norm in arb_tokens:
        reasons.append(
            "A.10.1.2 (valor arbitrado) não é calculado automaticamente nesta campanha; "
            "admissibilidade pendente."
        )
        admissible_status = EVIDENCE_PENDING
    elif adopted_norm in central_tokens or adopted_norm is None:
        use_ci = estimand_norm in market_tokens if estimand_norm else None
        use_pi = estimand_norm in price_tokens if estimand_norm else None
        if estimand_norm is None:
            reasons.append(
                "estimand não declarado: A.10 nota 9 distingue IC (valor de mercado) e "
                "intervalo de predição (preços). Interseção admissível não é assumida "
                "como regra universal."
            )
            admissible_status = EVIDENCE_PENDING
        elif adopted_norm is None:
            reasons.append(
                "adopted_estimator não declarado (tendência central vs valor arbitrado); "
                "interseção admissível pendente de justificativa de uso."
            )
            admissible_status = EVIDENCE_PENDING
        else:
            chosen = ci if use_ci else (pi if use_pi else None)
            label = "mean_ci80" if use_ci else "prediction_interval"
            if chosen is None or arbitration is None:
                reasons.append(
                    f"intervalo {label} ou campo de arbítrio ausente/não finito; "
                    "admissíveis não calculados."
                )
                admissible_status = EVIDENCE_PENDING
            else:
                lo = max(chosen["lower"], arbitration["lower"])
                hi = min(chosen["upper"], arbitration["upper"])
                if lo > hi:
                    reasons.append("interseção vazia entre intervalo estatístico e campo de arbítrio")
                    admissible_status = EVIDENCE_CALCULATED
                    admissible = {"lower": None, "upper": None, "empty": True, "via": label}
                else:
                    admissible_status = EVIDENCE_CALCULATED
                    admissible = {"lower": lo, "upper": hi, "empty": False, "via": label}
    else:
        reasons.append(f"adopted_estimator={adopted_estimator!r} não reconhecido; admissíveis pendentes.")

    return {
        "mean_ci80": ci,
        "prediction_interval": pi,
        "arbitration_interval": arbitration,
        "admissible_interval": admissible,
        "admissible_status": admissible_status,
        "estimand": estimand_norm,
        "adopted_estimator": adopted_norm,
        "reasons": reasons,
        "source": source_adm,
        "note": (
            "Campo de arbítrio (8.2.1.5.1) não se confunde com o IC de 80% da Tabela 5 "
            "(8.2.1.5.4). Grau de precisão ≠ emissão de laudo."
        ),
    }


def resolve_effective_n_k(
    context: Optional[Mapping[str, Any]] = None,
    *,
    X: Any = None,
    y: Any = None,
) -> Dict[str, Any]:
    """Resolve n and k without assuming an intercept via shape[1]-1."""
    ctx = dict(context or {})
    issues: List[Dict[str, Any]] = []
    n = ctx.get("n")
    k = ctx.get("k")
    intercept = ctx.get("intercept")
    sample = ctx.get("sample") if isinstance(ctx.get("sample"), Mapping) else {}
    if n is None and sample.get("used") is not None:
        used = sample.get("used")
        n = len(used) if isinstance(used, (list, tuple)) else used
    if n is None and y is not None:
        try:
            n = len(y)
        except TypeError:
            n = None
    n_f = as_float(n)

    if k is not None:
        k_f = as_float(k)
        return {
            "n": int(n_f) if n_f is not None else None,
            "k": int(k_f) if k_f is not None else None,
            "intercept": intercept,
            "k_source": "context",
            "issues": issues,
        }

    columns: Optional[List[str]] = None
    if X is not None and hasattr(X, "columns"):
        columns = [str(c) for c in list(X.columns)]
    elif ctx.get("feature_names"):
        columns = [str(c) for c in ctx["feature_names"]]

    if columns is None:
        issues.append(
            make_issue(
                "k_unknown",
                "k efetivo não informado e não há colunas para resolvê-lo; "
                "não se assume intercepto por shape-1.",
                severity="warning",
            )
        )
        return {"n": int(n_f) if n_f is not None else None, "k": None, "intercept": intercept, "k_source": None, "issues": issues}

    intercept_cols = [c for c in columns if c in INTERCEPT_COL_NAMES or c.lower() == "const"]
    if intercept is True:
        drop = max(len(intercept_cols), 1)
        k_res = len(columns) - drop
        source = "intercept_true"
    elif intercept is False:
        k_res = len(columns)
        source = "intercept_false"
    elif intercept_cols:
        k_res = len(columns) - len(intercept_cols)
        intercept = True
        source = "intercept_column"
    else:
        issues.append(
            make_issue(
                "intercept_unknown",
                "Intercepto não declarado e nenhuma coluna const/intercept visível; "
                "k não é inferido por n_colunas-1.",
                severity="warning",
            )
        )
        return {
            "n": int(n_f) if n_f is not None else None,
            "k": None,
            "intercept": None,
            "k_source": None,
            "issues": issues,
        }
    if k_res < 0:
        k_res = None
        issues.append(make_issue("k_negative", "k resolvido negativo.", severity="error"))
    return {
        "n": int(n_f) if n_f is not None else None,
        "k": k_res,
        "intercept": intercept,
        "k_source": source,
        "issues": issues,
    }


def _build_subject_raw(axes: Sequence[Mapping[str, Any]], subject_raw: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    raw = dict(subject_raw or {})
    for axis in axes:
        name = _axis_name(axis)
        if name and name not in raw and axis.get("avaliando_value") is not None:
            raw[name] = axis.get("avaliando_value")
    return raw


def classify_item4_extrapolacao(
    axes: Optional[Sequence[Mapping[str, Any]]],
    *,
    subject_raw: Optional[Mapping[str, Any]] = None,
    predict_original: Optional[Callable[[Mapping[str, Any]], Any]] = None,
    allow_measure_only_pass: bool = False,
) -> Dict[str, Any]:
    """Tabela 1 item 4: no extrapolation (III); one var + (a)+(b) 15% (II);
    (a)+(b) 20% de per si and simultaneously (I).

    `allow_measure_only_pass` is always treated as False for Grau II/I: the
    measure-only bug must not be reintroduced. The argument exists so callers
    cannot silently opt back into the error.
    """
    del allow_measure_only_pass  # never honour a measure-only pass
    source = {
        "edition": EDITION_PART2,
        "item": 4,
        "clause": "Tabela 1 item 4 (a) e (b)",
        "status": "verified",
    }
    empty_calc = {
        "extrapolated": [],
        "out_of_measure": [],
        "in_sample": [],
        "unsupported": [],
        "measure": {},
        "per_si": {},
        "simultaneous": None,
        "boundary_delta_pct": None,
        "y_subject": None,
    }
    if not axes:
        return {
            "grade": None,
            "evidence_status": EVIDENCE_PENDING,
            "detail": (
                "Nenhuma variável do avaliando informada para checagem de extrapolação; "
                "ausência não vale aprovação."
            ),
            "calculation": empty_calc,
            "reasons": ["axes_missing"],
            "source": source,
            "issues": [
                make_issue(
                    "item4_axes_missing",
                    "Item 4 pendente: eixos do avaliando não informados.",
                    severity="warning",
                    affected_ids=["item4"],
                )
            ],
        }

    issues: List[Dict[str, Any]] = []
    reasons: List[str] = []
    measure: Dict[str, Any] = {}
    in_sample: List[str] = []
    extrapolated: List[str] = []
    out_of_measure: List[str] = []
    unsupported: List[str] = []
    pending_axes: List[str] = []
    forbidden_axes: List[str] = []

    for axis in axes:
        name = _axis_name(axis) or "<unnamed>"
        kind = _axis_kind(axis)
        val = axis.get("avaliando_value")
        if kind in QUALITATIVE_KINDS:
            status, why = _qualitative_membership(axis, val)
            measure[name] = {
                "kind": kind,
                "position": status,
                "reason": why,
                "faixa_ampliada": EVIDENCE_NOT_APPLICABLE,
            }
            if status == "in_sample":
                in_sample.append(name)
            elif status == "forbidden":
                forbidden_axes.append(name)
                reasons.append(why)
            else:
                pending_axes.append(name)
                reasons.append(why)
            continue

        pos = measure_position(val, axis.get("sample_min"), axis.get("sample_max"))
        pos["kind"] = kind
        measure[name] = pos
        position = pos["position"]
        if position == POS_INVALID:
            pending_axes.append(name)
            reasons.extend(pos["reasons"] or ["medida inválida"])
        elif position == POS_NOT_APPLICABLE:
            unsupported.append(name)
            pending_axes.append(name)
            reasons.extend(pos["reasons"] or ["extensão de faixa não justificável neste domínio"])
        elif position == POS_IN_SAMPLE:
            in_sample.append(name)
        elif position == POS_EXTENDED:
            extrapolated.append(name)
        else:
            out_of_measure.append(name)

    calculation = {
        "extrapolated": list(extrapolated),
        "out_of_measure": list(out_of_measure),
        "in_sample": list(in_sample),
        "unsupported": list(unsupported),
        "forbidden": list(forbidden_axes),
        "pending_axes": list(pending_axes),
        "measure": measure,
        "per_si": {},
        "simultaneous": None,
        "boundary_delta_pct": None,
        "y_subject": None,
    }

    if pending_axes and not out_of_measure and not forbidden_axes and not extrapolated:
        # Could not even locate some axes, and nothing already fails the item.
        return {
            "grade": None,
            "evidence_status": EVIDENCE_PENDING,
            "detail": "Item 4 pendente: " + "; ".join(reasons),
            "calculation": calculation,
            "reasons": reasons,
            "source": source,
            "issues": issues + [
                make_issue(
                    "item4_pending_axis",
                    f"Eixos sem regra de faixa justificável ou sem dados: {pending_axes}",
                    severity="warning",
                    affected_ids=pending_axes,
                )
            ],
        }

    if out_of_measure:
        detail = (
            f"Item 4 reprovado: variável(is) {out_of_measure} fora da condição de medida "
            f"(Tabela 1 item 4 (a): ≤100% acima do máximo amostral e ≥ metade do mínimo)."
        )
        return {
            "grade": 0,
            "evidence_status": EVIDENCE_CALCULATED,
            "detail": detail,
            "calculation": calculation,
            "reasons": reasons,
            "source": source,
            "issues": issues,
        }

    if forbidden_axes:
        detail = (
            f"Item 4 não admitido: variável(is) qualitativa(s) {forbidden_axes} fora do "
            f"suporte amostral. Anexo A.5–A.7 veda extrapolação (e interpolação quando "
            f"aplicável); faixa 0,5·min–2·max não se aplica."
        )
        return {
            "grade": 0,
            "evidence_status": EVIDENCE_NOT_APPLICABLE,
            "detail": detail,
            "calculation": calculation,
            "reasons": reasons,
            "source": source,
            "issues": issues,
        }

    if pending_axes and not extrapolated:
        return {
            "grade": None,
            "evidence_status": EVIDENCE_PENDING,
            "detail": "Item 4 pendente: " + "; ".join(reasons),
            "calculation": calculation,
            "reasons": reasons,
            "source": source,
            "issues": issues,
        }

    if not extrapolated:
        return {
            "grade": 3,
            "evidence_status": EVIDENCE_CALCULATED,
            "detail": "Nenhuma extrapolação: todas as variáveis quantitativas no intervalo amostral [min, max].",
            "calculation": calculation,
            "reasons": reasons,
            "source": source,
            "issues": issues,
        }

    # Extrapolated quantitative axis/axes inside the measure window: need (b).
    if predict_original is None:
        calculation["value_check"] = "missing_predict_original"
        return {
            "grade": None,
            "evidence_status": EVIDENCE_PENDING,
            "detail": (
                "Item 4: condição de medida (a) satisfeita para "
                f"{extrapolated}, mas o valor estimado na fronteira (b) não foi apurado "
                "(predict_original ausente). Ausência da checagem de valor não é aprovação. "
                "Grau III permanece 'não admitida' porque há extrapolação."
            ),
            "calculation": calculation,
            "reasons": reasons + ["missing_predict_original"],
            "source": source,
            "issues": issues + [
                make_issue(
                    "item4_missing_predict_original",
                    "Grau II/I do item 4 exige |Δvalue| vs fronteira na unidade original; "
                    "callback predict_original não fornecido.",
                    severity="warning",
                    affected_ids=extrapolated,
                )
            ],
        }

    raw = _build_subject_raw(axes, subject_raw)
    y_subject, pred_issue = _call_predict_original(predict_original, raw)
    if pred_issue:
        issues.append(pred_issue)
        return {
            "grade": None,
            "evidence_status": EVIDENCE_PENDING,
            "detail": "Item 4 pendente: falha ao obter ŷ do avaliando na unidade original.",
            "calculation": calculation,
            "reasons": reasons + [pred_issue["code"]],
            "source": source,
            "issues": issues,
        }
    calculation["y_subject"] = y_subject

    axis_by_name = {_axis_name(a): a for a in axes}
    per_si: Dict[str, Any] = {}
    per_si_errors: List[str] = []

    for name in extrapolated:
        axis = axis_by_name[name]
        vmin = as_float(axis.get("sample_min"))
        vmax = as_float(axis.get("sample_max"))
        val = as_float(axis.get("avaliando_value") if name not in raw else raw.get(name, axis.get("avaliando_value")))
        if vmin is None or vmax is None or val is None:
            per_si_errors.append(name)
            per_si[name] = {"error": "missing_bounds", "delta_pct": None}
            continue
        frontier = clamp_to_sample_frontier(val, vmin, vmax)
        clamped_raw = dict(raw)
        clamped_raw[name] = frontier
        y_front, front_issue = _call_predict_original(predict_original, clamped_raw)
        if front_issue:
            per_si_errors.append(name)
            per_si[name] = {
                "error": front_issue["code"],
                "delta_pct": None,
                "frontier_value": frontier,
                "y_frontier": None,
            }
            issues.append(front_issue)
            continue
        delta_pct, err = relative_difference_pct(y_subject, y_front)
        entry = {
            "frontier_value": frontier,
            "avaliando_value": val,
            "y_subject": y_subject,
            "y_frontier": y_front,
            "delta_pct": delta_pct,
            "error": err,
            "limit_ok_ii": (delta_pct is not None and delta_pct <= VALUE_LIMIT_GRAU_II * 100.0),
            "limit_ok_i": (delta_pct is not None and delta_pct <= VALUE_LIMIT_GRAU_I * 100.0),
        }
        if err:
            per_si_errors.append(name)
        per_si[name] = entry

    calculation["per_si"] = per_si
    if len(extrapolated) == 1 and extrapolated[0] in per_si:
        calculation["boundary_delta_pct"] = per_si[extrapolated[0]].get("delta_pct")

    # Simultaneous clamp of all extrapolated quantitative axes.
    sim_raw = dict(raw)
    sim_frontiers = {}
    for name in extrapolated:
        axis = axis_by_name[name]
        vmin = as_float(axis.get("sample_min"))
        vmax = as_float(axis.get("sample_max"))
        val = as_float(raw.get(name, axis.get("avaliando_value")))
        if vmin is None or vmax is None or val is None:
            sim_frontiers[name] = None
            continue
        sim_frontiers[name] = clamp_to_sample_frontier(val, vmin, vmax)
        sim_raw[name] = sim_frontiers[name]

    y_sim, sim_issue = _call_predict_original(predict_original, sim_raw)
    sim_delta, sim_err = (None, "predict_failed")
    if sim_issue:
        issues.append(sim_issue)
        sim_err = sim_issue["code"]
    elif y_sim is None:
        sim_err = "non_finite_frontier"
    else:
        sim_delta, sim_err = relative_difference_pct(y_subject, y_sim)

    simultaneous = {
        "clamped_raw": {k: sim_frontiers[k] for k in extrapolated},
        "y_subject": y_subject,
        "y_frontier": y_sim,
        "delta_pct": sim_delta,
        "error": sim_err,
        "limit_ok_i": (sim_delta is not None and sim_delta <= VALUE_LIMIT_GRAU_I * 100.0),
    }
    calculation["simultaneous"] = simultaneous
    if calculation["boundary_delta_pct"] is None:
        calculation["boundary_delta_pct"] = sim_delta

    if per_si_errors or sim_err:
        return {
            "grade": None,
            "evidence_status": EVIDENCE_PENDING,
            "detail": (
                "Item 4: ŷ na unidade original não pôde ser comparado à fronteira "
                f"(per-si errors={per_si_errors}, simultaneous={sim_err}). "
                "Singularidade/zero/NaN/inf não recebem grau."
            ),
            "calculation": calculation,
            "reasons": reasons + per_si_errors + ([sim_err] if sim_err else []),
            "source": source,
            "issues": issues,
        }

    if pending_axes:
        # Measure-ok extrapolation on some axes, but others unjustifiable.
        return {
            "grade": None,
            "evidence_status": EVIDENCE_PENDING,
            "detail": (
                "Item 4 pendente: há eixo(s) sem extensão de faixa justificável "
                f"{pending_axes}; não se alega validação do item."
            ),
            "calculation": calculation,
            "reasons": reasons,
            "source": source,
            "issues": issues,
        }

    per_si_ok_ii = all(per_si[n].get("limit_ok_ii") for n in extrapolated)
    per_si_ok_i = all(per_si[n].get("limit_ok_i") for n in extrapolated)
    sim_ok_i = bool(simultaneous.get("limit_ok_i"))

    if len(extrapolated) == 1 and per_si_ok_ii:
        name = extrapolated[0]
        d = per_si[name]["delta_pct"]
        detail = (
            f"Extrapolação admitida (Grau II): uma variável ('{name}') na faixa de medida (a) "
            f"e |Δvalue|={d:.4f}% ≤ 15% vs ŷ na fronteira amostral (b), unidade original."
        )
        return {
            "grade": 2,
            "evidence_status": EVIDENCE_CALCULATED,
            "detail": detail,
            "calculation": calculation,
            "reasons": reasons,
            "source": source,
            "issues": issues,
        }

    if per_si_ok_i and sim_ok_i:
        detail = (
            f"Extrapolação admitida apenas em Grau I: variáveis {extrapolated} na faixa de "
            f"medida (a); |Δvalue|≤20% de per si e simultaneamente (b), unidade original."
        )
        return {
            "grade": 1,
            "evidence_status": EVIDENCE_CALCULATED,
            "detail": detail,
            "calculation": calculation,
            "reasons": reasons,
            "source": source,
            "issues": issues,
        }

    # Failed (b) — Grau III is "não admitida"; II/I not met.
    d_show = calculation.get("boundary_delta_pct")
    detail = (
        f"Item 4 não admitido nos graus I–III: há extrapolação {extrapolated} "
        f"(Grau III = não admitida); a condição de valor (b) não se verifica "
        f"(|Δvalue| fronteira={None if d_show is None else round(d_show, 4)}%; "
        f"II exige ≤15% em uma variável; I exige ≤20% de per si e simultaneamente)."
    )
    return {
        "grade": 0,
        "evidence_status": EVIDENCE_CALCULATED,
        "detail": detail,
        "calculation": calculation,
        "reasons": reasons,
        "source": source,
        "issues": issues,
    }


def statistical_warnings(
    statistical: Optional[Mapping[str, Any]],
    *,
    significance_aux: float = 0.10,
    vif_convention: float = 10.0,
) -> List[str]:
    """Anexo A diagnostics as warnings only — never a Tabela 1/2 cutoff."""
    warnings: List[str] = []
    if not statistical:
        return warnings
    r2_adj = statistical.get("r2_adjusted")
    r2 = statistical.get("r2")
    if as_float(r2_adj) is not None:
        warnings.append(
            f"R² ajustado = {float(r2_adj):.3f} (informativo — a norma não define piso "
            f"mínimo obrigatório de R²/R² ajustado, Anexo A.4)."
        )
    elif as_float(r2) is not None:
        warnings.append(
            f"R² = {float(r2):.3f} (informativo — Anexo A.4, sem piso normativo)."
        )
    n_p = as_float(statistical.get("normality_pvalue"))
    if n_p is not None and n_p < significance_aux:
        warnings.append(
            f"Resíduos possivelmente não normais (p={n_p:.4f} < {significance_aux:.0%}) — Anexo A.3.1."
        )
    h_p = as_float(statistical.get("homoscedasticity_pvalue"))
    if h_p is not None and h_p < significance_aux:
        warnings.append(
            f"Possível heterocedasticidade (p={h_p:.4f} < {significance_aux:.0%}) — Anexo A.3.1."
        )
    vif = statistical.get("vif") or {}
    if isinstance(vif, Mapping):
        for var, val in vif.items():
            if str(var).lower() == "const" or str(var) in INTERCEPT_COL_NAMES:
                continue
            vf = as_float(val)
            if vf is not None and vf > vif_convention:
                warnings.append(
                    f"VIF de '{var}' = {vf:.2f} > {vif_convention:g} (convenção de mercado, "
                    f"NÃO é limiar normativo — a NBR 14653-2 Anexo A.2.1.5.2 não define corte "
                    f"de VIF, apenas recomenda atenção a correlações > 0,80 na matriz de "
                    f"correlações). Não reprova o modelo."
                )
    if statistical.get("automatic_selection"):
        warnings.append(
            "Seleção automática de variáveis: p-valores e intervalos desta especificação "
            "carregam limitações de inferência pós-seleção; critérios tabelados da "
            "Tabela 1 não foram alterados."
        )
    return warnings


# Rule matrix entries used by assess_normative / documentation. Calculable
# conditions only; protected table wording is not copied.
RULE_MATRIX: List[Dict[str, Any]] = [
    {
        "id": "tabela1.item1",
        "edition": EDITION_PART2,
        "item": 1,
        "clause": "Tabela 1 item 1",
        "data_needed": "declaração documental da caracterização do avaliando + proveniência",
        "calculation": "não calculável pela planilha; declared ≠ verified",
        "verification_status": "verified",
        "test_ids": ["C03-A05", "test_documentary_without_provenance_is_not_verified"],
    },
    {
        "id": "tabela1.item2",
        "edition": EDITION_PART2,
        "item": 2,
        "clause": "Tabela 1 item 2",
        "data_needed": "n efetivo, k efetivo (intercepto declarado; não shape-1)",
        "calculation": "n vs 3(k+1) / 4(k+1) / 6(k+1)",
        "verification_status": "verified",
        "test_ids": ["C03-A04", "TestItem2QuantidadeDados"],
    },
    {
        "id": "tabela1.item3",
        "edition": EDITION_PART2,
        "item": 3,
        "clause": "Tabela 1 item 3",
        "data_needed": "declaração documental da identificação dos dados + proveniência",
        "calculation": "não calculável pela planilha; declared ≠ verified",
        "verification_status": "verified",
        "test_ids": ["C03-A05"],
    },
    {
        "id": "tabela1.item4.measure",
        "edition": EDITION_PART2,
        "item": 4,
        "clause": "Tabela 1 item 4 (a)",
        "data_needed": "min/max amostrais efetivos e valor do avaliando por eixo quantitativo",
        "calculation": "in-sample [min,max]; extended ≤2·max and ≥0,5·min when positive ratio-scale",
        "verification_status": "verified",
        "test_ids": ["C03-A01", "C03-A02"],
    },
    {
        "id": "tabela1.item4.value",
        "edition": EDITION_PART2,
        "item": 4,
        "clause": "Tabela 1 item 4 (b)",
        "data_needed": "predict_original(subject_raw) na unidade original; eixos a clampar",
        "calculation": "|ŷ_av−ŷ_front|/|ŷ_front|; II ≤15% uma variável; I ≤20% de per si e simultaneamente",
        "verification_status": "verified",
        "test_ids": ["C03-A01", "C03-A02", "C03-A03"],
    },
    {
        "id": "anexoA.5_7.qualitative",
        "edition": EDITION_PART2,
        "item": 4,
        "clause": "Anexo A.5, A.6, A.7",
        "data_needed": "kind do eixo e conjunto amostral discreto",
        "calculation": "sem faixa numérica inventada; extra/interpolação vedada conforme o kind",
        "verification_status": "verified",
        "test_ids": ["C03-A02"],
    },
    {
        "id": "tabela1.item5",
        "edition": EDITION_PART2,
        "item": 5,
        "clause": "Tabela 1 item 5",
        "data_needed": "p-valores dos regressores (exceto intercepto)",
        "calculation": "pior p ≤10%/20%/30%",
        "verification_status": "verified",
        "test_ids": ["C03-A04", "TestItem5SignificanciaRegressores"],
    },
    {
        "id": "tabela1.item6",
        "edition": EDITION_PART2,
        "item": 6,
        "clause": "Tabela 1 item 6",
        "data_needed": "p-valor do teste F",
        "calculation": "p ≤1%/2%/5%",
        "verification_status": "verified",
        "test_ids": ["C03-A04", "TestItem6SignificanciaGlobal"],
    },
    {
        "id": "tabela2.enquadramento",
        "edition": EDITION_PART2,
        "item": None,
        "clause": "Tabela 2 / 9.2.1.6",
        "data_needed": "graus dos itens 1–6",
        "calculation": "pontos mínimos e obrigatórios III/II/I; pendência não aprova",
        "verification_status": "verified",
        "test_ids": ["C03-A04", "TestClassifyFundamentacao"],
    },
    {
        "id": "tabela5.precisao",
        "edition": EDITION_PART2,
        "item": None,
        "clause": "Tabela 5 / 9.2.3",
        "data_needed": "amplitude % do IC de 80% em torno da estimativa de tendência central",
        "calculation": "≤30/40/50% → grau 3/2/1; >50% unclassified; ausente not_computed; não finito error",
        "verification_status": "verified",
        "test_ids": ["C03-A04", "C03-A05"],
    },
    {
        "id": "campo_arbitrio",
        "edition": EDITION_PART2,
        "item": None,
        "clause": "8.2.1.5.1 / 8.2.1.5.4",
        "data_needed": "estimativa de tendência central",
        "calculation": "±15% em torno da estimativa; distinto do IC de 80%",
        "verification_status": "verified",
        "test_ids": ["C03-A05", "TestValoresAdmissiveisCampoDeArbitrio"],
    },
    {
        "id": "admissiveis.central",
        "edition": EDITION_PART2,
        "item": None,
        "clause": "Anexo A.10.1.1 e notas 9–10",
        "data_needed": "estimand, adopted_estimator, IC80 e/ou PI, campo de arbítrio",
        "calculation": "interseção quando a condição de uso é declarada; senão pending",
        "verification_status": "verified",
        "test_ids": ["C03-A05"],
    },
]


UNVERIFIED_RULES: List[Dict[str, str]] = [
    {
        "id": "9.2.1.1.extras",
        "clause": "9.2.1.1 a–d",
        "reason": "laudo completo, análise de elasticidades, endereços das fontes e adoção da tendência central não são auto-aprovados por cálculo",
    },
    {
        "id": "9.2.1.6.1.homogeneous",
        "clause": "9.2.1.6.1",
        "reason": "atalho de amostra homogênea (itens 3–4 só no Grau III; 5–6 Grau III por modelo nulo) não implementado",
    },
    {
        "id": "anexoA.2.micronumerosidade",
        "clause": "Anexo A.2 a) n_i",
        "reason": "mínimos n_i por característica em dummies/códigos não são calculados automaticamente",
    },
    {
        "id": "tabelas3_4.fatores",
        "clause": "Tabelas 3–4 / 9.2.2",
        "reason": "tratamento por fatores fora do escopo desta campanha",
    },
    {
        "id": "metodos.custo_involutivo_evolutivo",
        "clause": "Tabelas 6–11 / 9.3–9.5",
        "reason": "quantificação de custo, involutivo e evolutivo não classificados aqui",
    },
    {
        "id": "anexoA.8.agrupamentos",
        "clause": "Anexo A.8",
        "reason": "independência entre agrupamentos / interações não verificada automaticamente",
    },
    {
        "id": "anexoA.10.1.2.arbitrado",
        "clause": "Anexo A.10.1.2",
        "reason": "valores admissíveis com valor arbitrado exigem amplitude do IC/PI deslocada; não auto-calculado",
    },
    {
        "id": "anexoA.2.1.outliers_justificativa",
        "clause": "Anexo A.2.1.6 / A.2 i",
        "reason": "retirada de influenciantes depende de justificativa profissional, não de corte silencioso",
    },
    {
        "id": "8.2.1.5.2.campo_insuficiente",
        "clause": "8.2.1.5.2–8.2.1.5.3",
        "reason": "suficiência do campo de arbítrio para variáveis omitidas é julgamento profissional",
    },
]


def verified_rule_ids() -> List[str]:
    return [r["id"] for r in RULE_MATRIX if r.get("verification_status") == "verified"]


def unverified_rule_ids() -> List[str]:
    return [r["id"] for r in UNVERIFIED_RULES]
