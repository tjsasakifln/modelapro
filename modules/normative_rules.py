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

import copy
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
        # MP-COM/C05: a declared grade WITHOUT provenance still scores points for
        # the analysis path, but it is not evidence. The qualification layer
        # refuses ready_for_professional_signoff while this is False.
        "provenance_verified": bool(has_prov),
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
    significance_aux: Optional[float] = None,
    vif_convention: float = 10.0,
) -> List[str]:
    """Anexo A diagnostics as warnings only — never a Tabela 1/2 cutoff.

    ``significance_aux`` defaults to the Anexo A.3.1 ceiling read from the
    provenance registry rather than to a second hardcoded copy of 10%: a
    duplicated threshold can drift away from its recorded source.
    ``vif_convention`` is deliberately NOT in that registry — the standard
    defines no VIF cutoff, so it has no normative provenance to record.
    """
    if significance_aux is None:
        significance_aux = max_auxiliary_alpha()
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


#: Rules that remain WITHOUT automatic verification. Every entry must carry a
#: ``destination``: how the requirement is discharged in the announced offer.
#:   automatic              -> calculated by this module (then it belongs in RULE_MATRIX)
#:   professional_evidenced -> a human act with identified professional, motive,
#:                             version and evidence; a checkbox is not enough
#:   out_of_announced_offer -> the method/asset type is not offered in V1; the
#:                             reason must be tied to the offer, not to convenience
#:   external_blocked       -> needs a source that was not legitimately obtainable
#:
#: ``unverified`` never counts as ``passed``. Nothing here may raise a grade.
UNVERIFIED_RULES: List[Dict[str, str]] = [
    {
        "id": "9.2.1.1.extras",
        "clause": "9.2.1.1 a)-d)",
        "destination": "professional_evidenced",
        "reason": (
            "laudo na modalidade completa, análise de elasticidades e coerência de "
            "mercado, endereços/fontes dos dados e adoção da tendência central: a "
            "elasticidade e a tendência central são calculáveis, mas a COERÊNCIA com o "
            "mercado e a completude documental são atos do profissional"
        ),
        "requires": "GRAU_III_ADDITIONAL_REQUIREMENTS com evidência por item",
        "blocks": "Grau III",
    },
    {
        "id": "9.2.1.6.1.homogeneous",
        "clause": "9.2.1.6.1",
        "destination": "out_of_announced_offer",
        "reason": (
            "atalho de amostra homogênea (itens 3 e 4 apenas no Grau III; itens 5 e 6 no "
            "Grau III por ser nulo o modelo de regressão) não implementado: a oferta V1 "
            "anuncia modelo de regressão com regressores, não amostra homogênea"
        ),
        "requires": "declarar a amostra como homogênea e classificar por via própria",
        "blocks": "nada na oferta anunciada; usar a via de regressão",
    },
    {
        "id": "anexoA.2.f.variaveis_relevantes",
        "clause": "Anexo A.2 f)",
        "destination": "professional_evidenced",
        "reason": (
            "inclusão das variáveis importantes (inclusive interações) e exclusão das "
            "irrelevantes é juízo do engenheiro de avaliações; busca automática por "
            "p-valor não decide relevância econômica"
        ),
        "requires": "registro da decisão com justificativa (PRESSUPOSTOS)",
        "blocks": "emissão qualificada sem registro",
    },
    {
        "id": "anexoA.2.g.multicolinearidade",
        "clause": "Anexo A.2 g) / A.2.1.5",
        "destination": "professional_evidenced",
        "reason": (
            "a norma VEDA o uso do modelo em caso de incoerência entre as características "
            "do avaliando e a estrutura de multicolinearidade inferida; a incoerência é "
            "juízo técnico, e correlação > 0,80 é gatilho de exame, não a vedação"
        ),
        "requires": "exame registrado; VIF não é limiar normativo",
        "blocks": "uso do modelo quando declarada a incoerência",
    },
    {
        "id": "anexoA.2.h.residuos_vs_independentes",
        "clause": "Anexo A.2 h)",
        "destination": "professional_evidenced",
        "reason": "exame do gráfico de resíduos contra cada variável independente é visual e não é decidido por p-valor",
        "requires": "registro do exame",
        "blocks": "emissão qualificada sem registro",
    },
    {
        "id": "anexoA.2.1.outliers_justificativa",
        "clause": "Anexo A.2 i) / A.2.1.6",
        "destination": "professional_evidenced",
        "reason": (
            "a investigação de pontos influenciantes é obrigatória e a RETIRADA fica "
            "condicionada à apresentação de justificativas; corte silencioso para "
            "melhorar R2 ou grau viola a cláusula"
        ),
        "requires": "justificativa por exclusão, com efeito registrado",
        "blocks": "emissão qualificada quando houve exclusão sem justificativa",
    },
    {
        "id": "anexoA.8.agrupamentos",
        "clause": "Anexo A.8",
        "destination": "professional_evidenced",
        "reason": (
            "independência entre agrupamentos (tipologia, mercados, localização, usos) e "
            "interações: a norma recomenda verificar; aplica-se quando há agrupamentos"
        ),
        "requires": "registro do exame quando o modelo usa agrupamentos",
        "blocks": "nada automaticamente; ausência de exame é limitação declarada",
    },
    {
        "id": "8.2.1.5.2.campo_insuficiente",
        "clause": "8.2.1.5.2 / 8.2.1.5.3",
        "destination": "professional_evidenced",
        "reason": (
            "a suficiencia do campo de arbitrio (+/-15%) para absorver variaveis "
            "relevantes nao contempladas e juizo profissional; 8.2.1.5.3 determina que, "
            "sendo insuficiente, o modelo NAO atinge o grau minimo de fundamentacao e o "
            "fato deve ser consignado no laudo"
        ),
        "requires": "declaracao do profissional; consequencia normativa explicita",
        "blocks": "grau minimo de fundamentacao quando declarada a insuficiencia",
    },
    {
        "id": "anexoA.10.1.2.arbitrado",
        "clause": "Anexo A.10.1.2",
        "destination": "professional_evidenced",
        "reason": (
            "valores admissiveis em torno do VALOR ARBITRADO exigem intervalo de mesma "
            "amplitude do IC/PI deslocado para o valor arbitrado, limitado pelo campo de "
            "arbitrio em torno da tendencia central; adotar valor arbitrado e ato do "
            "profissional e A.10.2 veda calcular probabilidade associada"
        ),
        "requires": "valor arbitrado declarado e justificado",
        "blocks": "calculo automatico de probabilidade sobre valor arbitrado",
    },
    {
        "id": "tabelas3_4.fatores",
        "clause": "Tabelas 3-4 / 9.2.2",
        "destination": "out_of_announced_offer",
        "reason": (
            "tratamento por fatores nao integra a oferta V1, que anuncia o metodo "
            "comparativo direto com REGRESSAO; nao e omissao de requisito aplicavel e sim "
            "recorte declarado da oferta"
        ),
        "requires": "se a oferta passar a incluir fatores, implementar Tabelas 3 e 4",
        "blocks": "qualquer alegacao de suporte a tratamento por fatores",
    },
    {
        "id": "metodos.involutivo_evolutivo",
        "clause": "Tabelas 8-11 / 9.4-9.5",
        "destination": "out_of_announced_offer",
        "reason": (
            "metodos involutivo e evolutivo nao integram a oferta V1; a Tabela 6/7 do "
            "metodo da quantificacao de custo, ao contrario, passou a ser especificada "
            "porque o perfil securitario exige base de CUSTO"
        ),
        "requires": "implementar Tabelas 8-11 caso a oferta passe a anuncia-los",
        "blocks": "qualquer alegacao de suporte a involutivo/evolutivo",
    },
    {
        "id": "metodos.custo.calculo",
        "clause": "9.3 / Tabela 6 / Tabela 7",
        "destination": "external_blocked",
        "reason": (
            "a REGRA de enquadramento do metodo da quantificacao de custo esta "
            "implementada (classify_custo_fundamentacao) e a base de valor esta "
            "especificada (VALUE_BASES), mas a ROTA DE CALCULO do custo - orcamento "
            "sintetico ou CUB, BDI e depreciacao fisica - depende de insumos de custo "
            "(CUB/SINDUSCON, projeto padrao NBR 12721) que nao foram obtidos nesta "
            "campanha e cuja implementacao cabe a C01"
        ),
        "requires": "serie CUB vigente por regiao/padrao e memoria de calculo; handoff C01",
        "blocks": "emissao qualificada para perfil securitario que exija custo",
    },
    {
        "id": "abnt.vigencia_das_edicoes",
        "clause": "catalogo ABNT",
        "destination": "external_blocked",
        "reason": (
            "os limiares foram conferidos contra as edicoes efetivamente em maos "
            "(14653-2:2011 e 14653-1:2019), mas a VIGENCIA dessas edicoes nao foi "
            "confirmada em fonte oficial: o catalogo ABNT e uma aplicacao JavaScript que "
            "nao entrega o registro da norma por requisicao estatica"
        ),
        "requires": "registro do catalogo ABNT para 14653-1 e 14653-2 (edicao, status, emendas)",
        "blocks": "alegacao de conformidade com a edicao VIGENTE (a conformidade com a edicao conferida permanece)",
    },
]


#: Rules implemented by this campaign and therefore no longer unverified.
RULE_MATRIX.extend([
    {
        "id": "anexoA.2.micronumerosidade",
        "edition": EDITION_PART2,
        "item": None,
        "clause": "Anexo A.2 a)",
        "data_needed": "n efetivo, k efetivo e contagem n_i por caracteristica dicotomica/codigo",
        "calculation": "n >= 3(k+1); n_i >= 3 (n<=30), >= 10% n (30<n<=100), >= 10 (n>100)",
        "verification_status": "verified",
        "destination": "automatic",
        "test_ids": ["C05-A04", "TestMicronumerosidade"],
    },
    {
        "id": "anexoA.3.1.significancia_auxiliar",
        "edition": EDITION_PART2,
        "item": None,
        "clause": "Anexo A.3.1",
        "data_needed": "alpha adotado nos testes nao citados na Tabela 1",
        "calculation": "alpha <= 10%; alpha acima do teto e recusado, nao afrouxado",
        "verification_status": "verified",
        "destination": "automatic",
        "test_ids": ["C05-A04", "TestPressupostos"],
    },
    {
        "id": "anexoA.2.cde.pressupostos",
        "edition": EDITION_PART2,
        "item": None,
        "clause": "Anexo A.2 c), d), e) / A.2.1.2-A.2.1.4",
        "data_needed": "p-valores dos testes de homocedasticidade, normalidade e autocorrelacao; ordenamento declarado",
        "calculation": "p <= alpha rejeita H0 e VIOLA o pressuposto; ausencia e pending",
        "verification_status": "verified",
        "destination": "automatic",
        "test_ids": ["C05-A04", "TestPressupostos"],
    },
    {
        "id": "tabela6_7.custo.enquadramento",
        "edition": EDITION_PART2,
        "item": None,
        "clause": "9.3 / Tabela 6 / Tabela 7",
        "data_needed": "graus documentais dos itens 1 (custo direto), 2 (BDI) e 3 (depreciacao fisica)",
        "calculation": "pontos 7/5/3 com obrigatorios; item pendente nao aprova",
        "verification_status": "verified",
        "destination": "automatic",
        "test_ids": ["C05-A06", "TestCustoFundamentacao"],
    },
    {
        "id": "parte1.bases_de_valor",
        "edition": EDITION_PART1_2019,
        "item": None,
        "clause": "3.1.47, 3.1.51, 3.1.11.3, 3.1.11.5, 3.1.11.6 / Secao 6 a) b)",
        "data_needed": "base de valor declarada e metodo declarado",
        "calculation": "value_basis_guard recusa base que o metodo declarado nao produz",
        "verification_status": "verified",
        "destination": "automatic",
        "test_ids": ["C05-A06", "TestValueBasisGuard"],
    },
    {
        "id": "9.1.2.nao_classificado",
        "edition": EDITION_PART2,
        "item": None,
        "clause": "9.1.2",
        "data_needed": "itens nao atendidos",
        "calculation": "nao atingir o Grau I exige indicar e justificar os itens nao atendidos",
        "verification_status": "verified",
        "destination": "professional_evidenced",
        "test_ids": ["C05-A02"],
    },
    {
        "id": "10.1.laudo_completo",
        "edition": EDITION_PART2,
        "item": None,
        "clause": "10.1 a)-m)",
        "data_needed": "presenca de cada item do laudo completo",
        "calculation": "inventario de 13 itens; ausencia bloqueia modalidade completa e, por 9.2.1.1 a), o Grau III",
        "verification_status": "verified",
        "destination": "professional_evidenced",
        "test_ids": ["C05-A02"],
    },
    {
        "id": "parte1.6.3.vistoria",
        "edition": EDITION_PART1_2019,
        "item": None,
        "clause": "6.3.1-6.3.3",
        "data_needed": "registro da vistoria ou da situacao-paradigma acordada",
        "calculation": "vistoria e essencial; situacao-paradigma e excecional, acordada e explicitada",
        "verification_status": "verified",
        "destination": "professional_evidenced",
        "test_ids": ["C05-A02", "C05-A07"],
    },
])


DESTINATIONS = (
    "automatic",
    "professional_evidenced",
    "out_of_announced_offer",
    "external_blocked",
)


def rules_by_destination(destination: str) -> List[Dict[str, Any]]:
    """Every rule routed to one destination, from both registries."""
    if destination not in DESTINATIONS:
        raise ValueError(f"destino desconhecido: {destination!r}")
    out: List[Dict[str, Any]] = []
    for r in RULE_MATRIX:
        if r.get("destination", "automatic") == destination:
            out.append(dict(r))
    for r in UNVERIFIED_RULES:
        if r.get("destination") == destination:
            out.append(dict(r))
    return out


def inventory_audit() -> Dict[str, Any]:
    """A02 guard: every registered rule must carry an explicit destination.

    Returns the counts per destination plus any rule missing a destination.
    A rule without a destination is a coverage hole, not a pass.
    """
    missing: List[str] = []
    for r in UNVERIFIED_RULES:
        if r.get("destination") not in DESTINATIONS:
            missing.append(r["id"])
    for r in RULE_MATRIX:
        d = r.get("destination", "automatic")
        if d not in DESTINATIONS:
            missing.append(r["id"])
    counts = {d: len(rules_by_destination(d)) for d in DESTINATIONS}
    return {
        "counts": counts,
        "total": len(RULE_MATRIX) + len(UNVERIFIED_RULES),
        "missing_destination": missing,
        "complete": not missing,
    }


def verified_rule_ids() -> List[str]:
    return [r["id"] for r in RULE_MATRIX if r.get("verification_status") == "verified"]


def unverified_rule_ids() -> List[str]:
    return [r["id"] for r in UNVERIFIED_RULES]


# ---------------------------------------------------------------------------
# MP-COM-20260912/C05 — source provenance, micronumerosidade, pressupostos,
# método da quantificação de custo e conteúdo do laudo.
#
# Every threshold below was read against the edition text itself (see
# SOURCE_DOCUMENTS); no value here comes from a README, a secondary source or
# model memory. The protected text is NOT reproduced: only clause anchors,
# paraphrased criteria and the numbers that the rule turns on.
# ---------------------------------------------------------------------------

CONSULTATION_DATE = "2026-09-11"

#: Documents whose integral text was consulted. ``sha256`` identifies the exact
#: file that was read; the files themselves are copyright-protected and are NOT
#: redistributed (``docs/normas/`` is git-ignored at the repository root).
SOURCE_DOCUMENTS: Dict[str, Dict[str, Any]] = {
    EDITION_PART2: {
        "id": "abnt-nbr-14653-2-2011",
        "title": "ABNT NBR 14653-2:2011 — Avaliação de bens — Parte 2: Imóveis urbanos",
        "edition_or_version": "2011 (1ª edição)",
        "sha256": "8fed8e7cf52187f7a46cada34685b70c517f32a2333d498295ea4f09e2668896",
        "consulted_on": CONSULTATION_DATE,
        "access": "exemplar licenciado disponibilizado localmente pelo responsável do projeto",
        "redistribution": "proibida; apenas metadados, âncoras de cláusula e critérios parafraseados",
        "currency_status": "edition_on_hand_verified_currency_unconfirmed",
    },
    EDITION_PART1_2019: {
        "id": "abnt-nbr-14653-1-2019",
        "title": "ABNT NBR 14653-1:2019 — Avaliação de bens — Parte 1: Procedimentos gerais",
        "edition_or_version": "2019 (2ª edição)",
        "sha256": "125eeed437c28a07691bfef72eaf4a3c9e1a3a1720e6a5e2cce1e548a02fcc92",
        "consulted_on": CONSULTATION_DATE,
        "access": "exemplar licenciado disponibilizado localmente pelo responsável do projeto",
        "redistribution": "proibida; apenas metadados, âncoras de cláusula e critérios parafraseados",
        "currency_status": "edition_on_hand_verified_currency_unconfirmed",
    },
}

#: Known dangling cross-reference: Parte 2:2011 cites Parte 1:**2001**, an
#: edition superseded by Parte 1:2019. Where the two differ, the quantified
#: rule that governs the urban-property regression scope is Parte 2's own.
CROSS_EDITION_NOTES: List[Dict[str, str]] = [
    {
        "id": "campo_arbitrio.cross_edition",
        "detail": (
            "8.2.1.5.1 da Parte 2:2011 quantifica o campo de arbítrio em ±15% e "
            "remete a '3.8 da ABNT NBR 14653-1:2001'. Na Parte 1:2019 a definição "
            "foi renumerada para 3.1.9 e NÃO repete a amplitude de 15%. A "
            "quantificação de ±15% aplicada pelo produto é a da Parte 2:2011, "
            "não uma leitura da Parte 1:2019."
        ),
        "clauses": "Parte 2:2011 8.2.1.5.1; Parte 1:2019 3.1.9",
    },
    {
        "id": "laudo_completo.cross_edition",
        "detail": (
            "10.1 da Parte 2:2011 remete diversos itens a 7.2/7.3/7.7.2 e Seção 8 "
            "da Parte 1:**2001**. A Parte 1:2019 reorganizou essa numeração; a "
            "correspondência item a item exige conferência e não é presumida aqui."
        ),
        "clauses": "Parte 2:2011 10.1; Parte 1:2019 (renumerada)",
    },
]

#: Provenance for every numeric threshold this module applies.
#: ``page`` is the page of the consulted PDF; ``literal`` records whether the
#: number is stated as such in the text or is an interpretation of it.
THRESHOLD_PROVENANCE: Dict[str, Dict[str, Any]] = {
    "ITEM2_FACTORS": {
        "values": {"grau_iii": 6, "grau_ii": 4, "grau_i": 3},
        "edition": EDITION_PART2, "clause": "Tabela 1 item 2", "page": 30,
        "literal": True,
        "detail": "n ≥ 6(k+1) / 4(k+1) / 3(k+1), k = nº de variáveis independentes.",
    },
    "MEASURE_LOWER_FACTOR": {
        "values": {"factor": 0.5},
        "edition": EDITION_PART2, "clause": "Tabela 1 item 4 (a)", "page": 30,
        "literal": True,
        "detail": "medidas não inferiores à metade do limite amostral inferior.",
    },
    "MEASURE_UPPER_FACTOR": {
        "values": {"factor": 2.0},
        "edition": EDITION_PART2, "clause": "Tabela 1 item 4 (a)", "page": 30,
        "literal": False,
        "detail": (
            "O texto diz 'não sejam superiores a 100 % do limite amostral superior'. "
            "Adotada a leitura 'até 100% ACIMA do limite superior' (fator 2,0), e não "
            "'até 100% DO limite superior' (fator 1,0). Justificativa: (i) o fator 1,0 "
            "tornaria o item 4 autocontraditório, pois nenhuma extrapolação seria "
            "admissível e os Graus II/I do item 4 ficariam vazios, contra a própria "
            "estrutura da Tabela 1; (ii) a condição inferior é expressa como 'metade do "
            "limite inferior' (0,5×), de modo que a leitura simétrica do par é 0,5× no "
            "piso e 2,0× no teto. A fronteira permanece explícita e testável; ver "
            "MEASURE_UPPER_FACTOR_ALTERNATIVE para a leitura concorrente."
        ),
        "interpretation_id": "item4a.upper_factor",
        "alternative_reading": {"factor": 1.0, "effect": "extrapolação nunca admitida"},
    },
    "VALUE_LIMITS": {
        "values": {"grau_ii": 0.15, "grau_i": 0.20},
        "edition": EDITION_PART2, "clause": "Tabela 1 item 4 (b)", "page": 31,
        "literal": True,
        "detail": (
            "Grau II: valor estimado não ultrapassa 15% do valor calculado no limite da "
            "fronteira amostral, para UMA variável, em módulo. Grau I: 20%, para as "
            "variáveis referidas, de per si E simultaneamente, em módulo."
        ),
    },
    "ITEM5_LIMITS": {
        "values": {"grau_iii": 0.10, "grau_ii": 0.20, "grau_i": 0.30},
        "edition": EDITION_PART2, "clause": "Tabela 1 item 5", "page": 31,
        "literal": True,
        "detail": "Nível de significância (somatório das duas caudas) por regressor, teste bicaudal.",
    },
    "ITEM6_LIMITS": {
        "values": {"grau_iii": 0.01, "grau_ii": 0.02, "grau_i": 0.05},
        "edition": EDITION_PART2, "clause": "Tabela 1 item 6", "page": 31,
        "literal": True,
        "detail": "Nível de significância máximo para rejeição da hipótese nula do modelo (teste F).",
    },
    "TABELA2_PONTOS": {
        "values": {"grau_iii": 16, "grau_ii": 10, "grau_i": 6},
        "edition": EDITION_PART2, "clause": "Tabela 2 / 9.2.1.6", "page": 32,
        "literal": True,
        "detail": (
            "Pontos mínimos 16/10/6. Itens obrigatórios: Grau III → 2,4,5,6 no Grau III e "
            "os demais no mínimo no Grau II; Grau II → 2,4,5,6 no mínimo no Grau II e os "
            "demais no mínimo no Grau I; Grau I → todos no mínimo no Grau I. "
            "Pontuação: Grau I = 1 ponto, Grau II = 2, Grau III = 3 (9.2.1.6 b)."
        ),
    },
    "PRECISAO_LIMITS": {
        "values": {"grau_iii": 30.0, "grau_ii": 40.0, "grau_i": 50.0},
        "edition": EDITION_PART2, "clause": "Tabela 5 / 9.2.3", "page": 34,
        "literal": True,
        "detail": (
            "Amplitude do IC de 80% em torno da estimativa de tendência central: "
            "≤30% / ≤40% / ≤50%. NOTA: acima de 50% não há classificação quanto à "
            "precisão e é necessária justificativa com base no diagnóstico do mercado."
        ),
    },
    "CAMPO_ARBITRIO": {
        "values": {"amplitude": 0.15},
        "edition": EDITION_PART2, "clause": "8.2.1.5.1", "page": 24,
        "literal": True,
        "detail": (
            "Intervalo com amplitude de 15% para mais e para menos em torno da "
            "estimativa de tendência central. 8.2.1.5.4: não se confunde com o IC de 80%."
        ),
    },
    "MICRONUMEROSIDADE": {
        "values": {"n_min_factor": 3, "ni_small": 3, "ni_mid_fraction": 0.10, "ni_large": 10,
                   "n_small_max": 30, "n_mid_max": 100},
        "edition": EDITION_PART2, "clause": "Anexo A.2 a)", "page": 42,
        "literal": True,
        "detail": (
            "n ≥ 3(k+1); para n ≤ 30, n_i ≥ 3; para 30 < n ≤ 100, n_i ≥ 10% n; para "
            "n > 100, n_i ≥ 10 — onde n_i é o número de dados de mesma característica, "
            "no caso de variáveis dicotômicas e qualitativas por códigos alocados ou ajustados."
        ),
    },
    "SIGNIFICANCE_AUX": {
        "values": {"max_alpha": 0.10},
        "edition": EDITION_PART2, "clause": "Anexo A.3.1", "page": 45,
        "literal": True,
        "detail": (
            "O nível de significância máximo admitido nos demais testes estatísticos "
            "(os não citados na Tabela 1) não deve ser superior a 10%. É teto normativo "
            "do α desses testes — não é um piso de qualidade nem corte da Tabela 1/2."
        ),
    },
    "CORRELATION_ATTENTION": {
        "values": {"threshold": 0.80},
        "edition": EDITION_PART2, "clause": "Anexo A.2.1.5.2", "page": 44,
        "literal": True,
        "detail": (
            "Analisar a matriz das correlações com atenção especial para resultados "
            "superiores a 0,80. NÃO é reprovação automática e a norma NÃO define corte "
            "de VIF; qualquer limiar de VIF é convenção de mercado, não normativo."
        ),
    },
    "TABELA7_PONTOS_CUSTO": {
        "values": {"grau_iii": 7, "grau_ii": 5, "grau_i": 3},
        "edition": EDITION_PART2, "clause": "Tabela 7 / 9.3", "page": 35,
        "literal": True,
        "detail": (
            "Método da quantificação de custo: pontos mínimos 7/5/3. Itens obrigatórios: "
            "Grau III → item 1 no Grau III e os demais no mínimo no Grau II; Grau II → "
            "itens 1 e 2 no mínimo no Grau II; Grau I → todos no mínimo no Grau I. "
            "9.3.1: para o Grau III é obrigatória a apresentação do laudo na modalidade completa."
        ),
    },
}

MEASURE_UPPER_FACTOR_ALTERNATIVE = 1.0


def threshold_provenance(key: str) -> Dict[str, Any]:
    """Provenance record for a threshold family. Raises on unknown key.

    Returns a DEEP copy: a shallow one leaves the nested ``values`` mapping
    shared, so a caller mutating it would silently rewrite the normative
    registry for the rest of the process.
    """
    if key not in THRESHOLD_PROVENANCE:
        raise KeyError(f"sem proveniência registrada para o limiar {key!r}")
    return copy.deepcopy(THRESHOLD_PROVENANCE[key])


# --- Anexo A.2 a): micronumerosidade -----------------------------------------

MICRO_OK = "ok"
MICRO_VIOLATED = "violated"
MICRO_PENDING = "pending"


def minimum_ni(n: Any) -> Optional[int]:
    """Anexo A.2 a): minimum n_i per characteristic, as a function of n.

    n ≤ 30 → 3; 30 < n ≤ 100 → 10% of n; n > 100 → 10.
    The 10% branch is a minimum, so it is rounded UP (a fractional datum
    cannot satisfy a count). Returns None when n is not a usable count.
    """
    n_f = as_float(n)
    if n_f is None or n_f < 0:
        return None
    n_i = int(n_f)
    if n_i <= 30:
        return 3
    if n_i <= 100:
        return int(math.ceil(0.10 * n_i))
    return 10


def classify_micronumerosidade(
    n: Any,
    k: Any,
    category_counts: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Anexo A.2 a): global n ≥ 3(k+1) AND per-characteristic n_i minimums.

    ``category_counts`` maps the name of each dichotomous / allocated-code /
    adjusted-code characteristic actually used in the model to the number of
    sample data carrying it. Absence of that mapping is NOT compliance: the
    per-characteristic leg stays pending.

    This is a *pressuposto* of Anexo A.2, not a Tabela 1 item: it never awards
    points and never raises a grade. It can only expose a violation.
    """
    source = {
        "edition": EDITION_PART2,
        "clause": "Anexo A.2 a)",
        "page": 42,
        "status": "verified",
    }
    n_f, k_f = as_float(n), as_float(k)
    if n_f is None or k_f is None or n_f < 0 or k_f < 0:
        return {
            "status": MICRO_PENDING,
            "n": n, "k": k,
            "n_minimum": None, "ni_minimum": None,
            "violations": [], "checked_characteristics": [],
            "detail": "n ou k efetivo ausente; micronumerosidade não avaliada (ausência não é conformidade).",
            "source": source,
        }
    n_i, k_i = int(n_f), int(k_f)
    n_min = 3 * (k_i + 1)
    ni_min = minimum_ni(n_i)

    violations: List[Dict[str, Any]] = []
    if n_i < n_min:
        violations.append({
            "kind": "global_n",
            "observed": n_i,
            "criterion": f"n >= 3(k+1) = {n_min}",
            "detail": f"n={n_i} < {n_min}: micronumerosidade global (Anexo A.2 a).",
        })

    checked: List[str] = []
    pending_leg = category_counts is None
    if category_counts is not None:
        for name in sorted(category_counts):
            raw = category_counts[name]
            count = as_float(raw)
            if count is None or count < 0:
                violations.append({
                    "kind": "characteristic_count_invalid",
                    "characteristic": name,
                    "observed": raw,
                    "criterion": f"n_i >= {ni_min}",
                    "detail": f"contagem inválida para a característica {name!r}.",
                })
                continue
            checked.append(name)
            if ni_min is not None and int(count) < ni_min:
                violations.append({
                    "kind": "characteristic_ni",
                    "characteristic": name,
                    "observed": int(count),
                    "criterion": f"n_i >= {ni_min}",
                    "detail": (
                        f"característica {name!r} com n_i={int(count)} < {ni_min} "
                        f"(regra para n={n_i}, Anexo A.2 a)."
                    ),
                })

    if violations:
        status = MICRO_VIOLATED
        detail = f"{len(violations)} violação(ões) de micronumerosidade (Anexo A.2 a)."
    elif pending_leg:
        status = MICRO_PENDING
        detail = (
            f"n={n_i} >= {n_min} atendido, mas as contagens por característica "
            "(dicotômicas / códigos alocados / ajustados) não foram informadas: "
            "a perna n_i permanece pendente, não aprovada."
        )
    else:
        status = MICRO_OK
        detail = (
            f"n={n_i} >= {n_min} e todas as {len(checked)} características verificadas "
            f"com n_i >= {ni_min}."
        )

    return {
        "status": status,
        "n": n_i, "k": k_i,
        "n_minimum": n_min,
        "ni_minimum": ni_min,
        "violations": violations,
        "checked_characteristics": checked,
        "per_characteristic_evaluated": not pending_leg,
        "detail": detail,
        "source": source,
    }


# --- Anexo A.2 c)–i) + A.3.1: pressupostos do modelo -------------------------

PRESSUPOSTO_SATISFIED = "satisfied"
PRESSUPOSTO_VIOLATED = "violated"
PRESSUPOSTO_PENDING = "pending"
PRESSUPOSTO_PROFESSIONAL = "professional_decision_required"

#: Each assumption carries hypothesis, method, direction of the test, the
#: condition under which it applies and the prescribed reaction. A p-value
#: alone is never the finding — Anexo A.2 states the requirement, A.3.1 caps
#: the significance level of these (non-Tabela-1) tests at 10%.
PRESSUPOSTOS: List[Dict[str, Any]] = [
    {
        "id": "anexoA.2.c.homocedasticidade",
        "clause": "Anexo A.2 c) / A.2.1.3",
        "page": 42,
        "requirement": "os erros são variáveis aleatórias com variância constante (homocedásticos)",
        "hypothesis_null": "variância dos erros constante",
        "direction": "rejeitar H0 (p <= alpha) indica heterocedasticidade, isto é, VIOLAÇÃO",
        "methods_cited": ["análise gráfica resíduos vs valores ajustados", "teste de Park", "teste de White"],
        "method_note": (
            "A.2.1.3 cita Park e White. Breusch-Pagan não é citado pela norma; se usado, "
            "é substituto metodológico e deve ser declarado como tal."
        ),
        "reaction": "modelo heterocedástico não satisfaz A.2 c); exige correção ou justificativa técnica no laudo",
        "automatable": True,
    },
    {
        "id": "anexoA.2.d.normalidade",
        "clause": "Anexo A.2 d) / A.2.1.2",
        "page": 42,
        "requirement": "os erros são variáveis aleatórias com distribuição normal",
        "hypothesis_null": "erros normalmente distribuídos",
        "direction": "rejeitar H0 (p <= alpha) indica não normalidade, isto é, VIOLAÇÃO",
        "methods_cited": [
            "histograma de resíduos padronizados",
            "frequências relativas observadas nos intervalos [-1;+1] ~68%, [-1,64;+1,64] ~90%, [-1,96;+1,96] ~95%",
            "testes não paramétricos",
        ],
        "method_note": (
            "A.2.1.2 admite aferição por frequências relativas; o produto deve reportar "
            "esse cotejo além de qualquer teste, pois é o método que a norma descreve."
        ),
        "reaction": "não normalidade compromete os testes t/F dos itens 5 e 6 e exige tratamento declarado",
        "automatable": True,
    },
    {
        "id": "anexoA.2.e.autocorrelacao",
        "clause": "Anexo A.2 e) / A.2.1.4",
        "page": 42,
        "requirement": "os erros são não autocorrelacionados (independentes sob normalidade)",
        "hypothesis_null": "erros não autocorrelacionados",
        "direction": "rejeitar H0 (p <= alpha) indica autocorrelação, isto é, VIOLAÇÃO",
        "methods_cited": ["gráfico de resíduos cotejados com valores ajustados, após pré-ordenamento"],
        "method_note": (
            "A.2.1.4 EXIGE pré-ordenamento dos elementos amostrais (pelos valores ajustados "
            "e, se for o caso, pelas variáveis suspeitas) ANTES do exame. Um teste de "
            "autocorrelação aplicado na ordem original do arquivo não cumpre a cláusula."
        ),
        "reaction": "autocorrelação exige reordenamento declarado e tratamento; não se ignora por p favorável em outra ordem",
        "automatable": True,
        "requires_declared_ordering": True,
    },
    {
        "id": "anexoA.2.f.variaveis_relevantes",
        "clause": "Anexo A.2 f)",
        "page": 42,
        "requirement": (
            "variáveis importantes incorporadas ao modelo — inclusive as decorrentes de "
            "interação — e variáveis irrelevantes ausentes"
        ),
        "reaction": "decisão do engenheiro de avaliações; não é decidível por busca automática de p-valor",
        "automatable": False,
        "professional_decision": True,
    },
    {
        "id": "anexoA.2.g.multicolinearidade",
        "clause": "Anexo A.2 g) / A.2.1.5",
        "page": 42,
        "requirement": (
            "havendo multicolinearidade, examinar a coerência das características do imóvel "
            "avaliando com a estrutura de multicolinearidade inferida"
        ),
        "prohibition": "vedada a utilização do modelo em caso de incoerência",
        "attention_threshold": THRESHOLD_PROVENANCE["CORRELATION_ATTENTION"]["values"]["threshold"],
        "attention_clause": "A.2.1.5.2 (matriz de correlações, atenção a resultados > 0,80)",
        "reaction": (
            "É a única cláusula deste bloco que VEDA o uso do modelo. A vedação depende de "
            "um juízo de coerência sobre o avaliando; correlação > 0,80 é gatilho de exame, "
            "não a vedação em si. VIF não é limiar normativo."
        ),
        "automatable": False,
        "professional_decision": True,
        "blocks_use_when_incoherent": True,
    },
    {
        "id": "anexoA.2.h.residuos_vs_independentes",
        "clause": "Anexo A.2 h)",
        "page": 42,
        "requirement": (
            "o gráfico de resíduos não pode sugerir regularidade estatística com respeito "
            "às variáveis independentes"
        ),
        "reaction": "exame gráfico com registro; ausência de gráfico examinado não é conformidade",
        "automatable": False,
        "professional_decision": True,
    },
    {
        "id": "anexoA.2.i.pontos_influenciantes",
        "clause": "Anexo A.2 i) / A.2.1.6",
        "page": 42,
        "requirement": (
            "pontos influenciantes, ou aglomerados deles, devem ser investigados e sua "
            "retirada fica condicionada à apresentação de justificativas"
        ),
        "methods_cited": ["resíduos vs cada variável independente", "resíduos vs valores ajustados",
                          "estatística de Cook", "distância de Mahalanobis"],
        "reaction": (
            "Investigação é obrigatória; a RETIRADA é condicionada a justificativa "
            "apresentada. Exclusão automática para melhorar R²/grau viola a cláusula."
        ),
        "automatable": False,
        "professional_decision": True,
        "removal_requires_justification": True,
    },
    {
        "id": "anexoA.8.agrupamentos",
        "clause": "Anexo A.8",
        "page": 46,
        "requirement": (
            "usando diferentes agrupamentos (tipologia, mercados, localização, usos), "
            "verificar a independência entre os agrupamentos, entre as variáveis e "
            "possíveis interações"
        ),
        "reaction": "recomendação da norma; aplica-se quando há agrupamentos, e o exame deve ser registrado",
        "automatable": False,
        "professional_decision": True,
        "normative_strength": "recomenda-se",
    },
]

PRESSUPOSTOS_BY_ID = {p["id"]: p for p in PRESSUPOSTOS}


def max_auxiliary_alpha() -> float:
    """Anexo A.3.1 ceiling for the significance level of non-Tabela-1 tests."""
    return float(THRESHOLD_PROVENANCE["SIGNIFICANCE_AUX"]["values"]["max_alpha"])


def evaluate_pressuposto(
    pressuposto_id: str,
    *,
    p_value: Any = None,
    alpha: Any = None,
    professional_finding: Any = None,
    ordering_declared: Optional[bool] = None,
) -> Dict[str, Any]:
    """Evaluate one Anexo A.2 assumption with its hypothesis and reaction.

    For automatable assumptions the verdict follows the stated direction:
    p <= alpha rejects H0 and therefore VIOLATES the requirement. ``alpha``
    defaults to the A.3.1 ceiling of 10% and is refused above it.
    """
    spec = PRESSUPOSTOS_BY_ID.get(pressuposto_id)
    if spec is None:
        raise KeyError(f"pressuposto desconhecido: {pressuposto_id!r}")
    ceiling = max_auxiliary_alpha()
    source = {"edition": EDITION_PART2, "clause": spec["clause"], "page": spec.get("page"),
              "status": "verified"}
    out: Dict[str, Any] = {
        "id": pressuposto_id,
        "requirement": spec["requirement"],
        "clause": spec["clause"],
        "source": source,
        "observed": None,
        "criterion": None,
    }

    if not spec.get("automatable"):
        finding = professional_finding
        if finding is None:
            out.update({
                "status": PRESSUPOSTO_PROFESSIONAL,
                "detail": (
                    f"{spec['clause']}: exige exame e registro do engenheiro de avaliações. "
                    "Sem registro, permanece pendente de decisão profissional — ausência "
                    "não é conformidade."
                ),
                "reaction": spec.get("reaction"),
            })
            return out
        satisfied = bool(finding.get("satisfied")) if isinstance(finding, Mapping) else bool(finding)
        justification = finding.get("justification") if isinstance(finding, Mapping) else None
        if not justification:
            out.update({
                "status": PRESSUPOSTO_PROFESSIONAL,
                "detail": (
                    f"{spec['clause']}: decisão profissional informada sem justificativa "
                    "registrada; a norma condiciona o ato à justificativa apresentada."
                ),
                "reaction": spec.get("reaction"),
            })
            return out
        out.update({
            "status": PRESSUPOSTO_SATISFIED if satisfied else PRESSUPOSTO_VIOLATED,
            "observed": justification,
            "detail": (
                f"{spec['clause']}: decisão profissional registrada "
                f"({'satisfeito' if satisfied else 'violado'}) com justificativa."
            ),
            "reaction": spec.get("reaction"),
        })
        return out

    a = as_float(alpha)
    if a is None:
        a = ceiling
    if a > ceiling:
        out.update({
            "status": PRESSUPOSTO_PENDING,
            "detail": (
                f"alpha={a:.4f} excede o teto de {ceiling:.0%} do Anexo A.3.1 para testes "
                "não citados na Tabela 1; avaliação recusada em vez de afrouxada."
            ),
            "alpha": a, "alpha_ceiling": ceiling,
        })
        return out
    if spec.get("requires_declared_ordering") and not ordering_declared:
        out.update({
            "status": PRESSUPOSTO_PENDING,
            "alpha": a, "alpha_ceiling": ceiling,
            "detail": (
                f"{spec['clause']} exige pré-ordenamento declarado dos elementos amostrais "
                "antes do exame de autocorrelação; sem ele o resultado não é conclusivo."
            ),
            "reaction": spec.get("reaction"),
        })
        return out
    p = as_float(p_value)
    if p is None:
        out.update({
            "status": PRESSUPOSTO_PENDING,
            "alpha": a, "alpha_ceiling": ceiling,
            "detail": f"{spec['clause']}: p-valor ausente ou não finito; pressuposto não avaliado.",
            "reaction": spec.get("reaction"),
        })
        return out
    violated = p <= a
    out.update({
        "status": PRESSUPOSTO_VIOLATED if violated else PRESSUPOSTO_SATISFIED,
        "alpha": a,
        "alpha_ceiling": ceiling,
        "observed": p,
        "criterion": f"p > {a:.4f} para não rejeitar H0 ({spec['hypothesis_null']})",
        "hypothesis_null": spec["hypothesis_null"],
        "direction": spec["direction"],
        "detail": (
            f"{spec['clause']}: p={p:.4f} {'<=' if violated else '>'} alpha={a:.4f} — "
            f"{'H0 rejeitada: pressuposto VIOLADO' if violated else 'H0 não rejeitada'}. "
            f"{spec.get('method_note', '')}"
        ).strip(),
        "reaction": spec.get("reaction"),
    })
    return out


# --- 9.3 / Tabelas 6 e 7: método da quantificação de custo -------------------
#
# Needed by the securitário profile: when the base of value is a
# reconstruction/replacement cost, the value CANNOT be obtained by applying a
# coefficient to a market price. Parte 1:2019 defines the bases:
#   3.1.11.5 custo de reprodução  — reproduzir bem idêntico, SEM depreciação
#   3.1.11.3 custo de reedição    — custo de reprodução MENOS a depreciação
#   3.1.11.6 custo de substituição— custo de reedição de bem de mesma utilidade
#   3.1.51   valor em risco       — parcela do bem que se deseja segurar,
#                                   podendo corresponder ao valor máximo segurável
# A regressão do método comparativo estima valor de mercado (3.1.47) e não
# produz nenhuma dessas bases.

TABELA6_ITEMS: List[Dict[str, Any]] = [
    {
        "item": 1,
        "id": "tabela6.item1",
        "description": "Estimativa do custo direto",
        "criteria": {
            3: "elaboração de orçamento, no mínimo sintético",
            2: "custo unitário básico para projeto semelhante ao projeto padrão",
            1: "custo unitário básico para projeto diferente do projeto padrão, com os devidos ajustes",
        },
        "evidence_kind": "documental",
    },
    {
        "item": 2,
        "id": "tabela6.item2",
        "description": "BDI",
        "criteria": {3: "calculado", 2: "justificado", 1: "arbitrado"},
        "evidence_kind": "documental",
    },
    {
        "item": 3,
        "id": "tabela6.item3",
        "description": "Depreciação física",
        "criteria": {
            3: ("calculada por levantamento do custo de recuperação do bem para deixá-lo no "
                "estado de novo, ou casos de bens novos / projetos hipotéticos"),
            2: ("calculada por métodos técnicos consagrados, considerando idade, vida útil e "
                "estado de conservação"),
            1: "arbitrada",
        },
        "evidence_kind": "documental",
    },
]

TABELA7_PONTOS_III = 7
TABELA7_PONTOS_II = 5
TABELA7_PONTOS_I = 3


def classify_custo_fundamentacao(item_scores: Mapping[int, Any]) -> Dict[str, Any]:
    """Tabela 7: enquadramento do método da quantificação de custo.

    Pontos mínimos 7/5/3. Obrigatórios: Grau III → item 1 no Grau III e os
    demais no mínimo no Grau II; Grau II → itens 1 e 2 no mínimo no Grau II;
    Grau I → todos no mínimo no Grau I.

    Every item here is documentary: none is computed from the market sample.
    A pending item blocks the enquadramento — absence is never approval.
    """
    source = {"edition": EDITION_PART2, "clause": "Tabela 7 / 9.3", "page": 35,
              "status": "verified"}
    pending_items = [i for i in (1, 2, 3) if item_scores.get(i) is None]
    numeric = {i: int(item_scores.get(i) or 0) for i in (1, 2, 3)}
    pontos = sum(numeric.values())

    if pending_items:
        return {
            "grade": None, "points": pontos, "pending_items": pending_items,
            "detail": (
                f"Itens {pending_items} da Tabela 6 pendentes; enquadramento da Tabela 7 "
                f"não é aprovado por ausência (pontos conhecidos={pontos})."
            ),
            "source": source, "evidence_status": EVIDENCE_PENDING,
        }

    if pontos >= TABELA7_PONTOS_III and numeric[1] >= 3 and numeric[2] >= 2 and numeric[3] >= 2:
        grade, detail = 3, f"Tabela 7: Grau III (pontos={pontos}). 9.3.1 exige laudo na modalidade completa."
    elif pontos >= TABELA7_PONTOS_II and numeric[1] >= 2 and numeric[2] >= 2:
        grade, detail = 2, f"Tabela 7: Grau II (pontos={pontos})."
    elif pontos >= TABELA7_PONTOS_I and all(v >= 1 for v in numeric.values()):
        grade, detail = 1, f"Tabela 7: Grau I (pontos={pontos})."
    else:
        grade, detail = None, f"Tabela 7: não classificado (pontos={pontos})."

    return {
        "grade": grade, "points": pontos, "pending_items": [],
        "detail": detail, "source": source, "evidence_status": EVIDENCE_CALCULATED,
    }


#: Bases of value, with the method that legitimately produces each one.
#: ``derivable_from_market_regression`` is the guard that A06 turns on.
VALUE_BASES: Dict[str, Dict[str, Any]] = {
    "valor_de_mercado": {
        "label": "Valor de mercado",
        "definition_clause": "ABNT NBR 14653-1:2019, 3.1.47",
        "definition": ("quantia mais provável pela qual se negociaria voluntária e "
                       "conscientemente um bem, em uma data de referência, dentro das "
                       "condições do mercado vigente"),
        "produced_by": ["metodo_comparativo_direto_regressao"],
        "derivable_from_market_regression": True,
    },
    "custo_de_reproducao": {
        "label": "Custo de reprodução",
        "definition_clause": "ABNT NBR 14653-1:2019, 3.1.11.5",
        "definition": ("custo necessário para reproduzir um bem idêntico, com a consideração "
                       "dos seus insumos pertinentes, sem considerar eventual depreciação"),
        "produced_by": ["metodo_quantificacao_de_custo"],
        "derivable_from_market_regression": False,
        "required_memory": ["custo_direto", "bdi"],
    },
    "custo_de_reedicao": {
        "label": "Custo de reedição",
        "definition_clause": "ABNT NBR 14653-1:2019, 3.1.11.3",
        "definition": "custo de reprodução, descontada a depreciação do bem, tendo em vista o estado em que se encontra",
        "produced_by": ["metodo_quantificacao_de_custo"],
        "derivable_from_market_regression": False,
        "required_memory": ["custo_direto", "bdi", "depreciacao_fisica"],
    },
    "custo_de_substituicao": {
        "label": "Custo de substituição",
        "definition_clause": "ABNT NBR 14653-1:2019, 3.1.11.6",
        "definition": "custo de reedição de um bem, com a mesma utilidade e características assemelhadas ao avaliando",
        "produced_by": ["metodo_quantificacao_de_custo"],
        "derivable_from_market_regression": False,
        "required_memory": ["custo_direto", "bdi", "depreciacao_fisica"],
    },
    "valor_em_risco": {
        "label": "Valor em risco",
        "definition_clause": "ABNT NBR 14653-1:2019, 3.1.51",
        "definition": ("valor representativo da parcela do bem que se deseja segurar e que "
                       "pode corresponder ao valor máximo segurável"),
        "produced_by": ["definicao_contratual_apolice"],
        "derivable_from_market_regression": False,
        "note": (
            "Parte 1:2019 (0.3) coloca o valor em risco ora na abordagem pelo valor de "
            "mercado (quando o bem é segurado pelo valor de mercado), ora entre os valores "
            "específicos (quando os critérios da apólice diferem do valor de mercado). "
            "Qual dos dois se aplica é definido PELA APÓLICE, não pelo avaliador."
        ),
    },
    "limite_maximo_de_garantia": {
        "label": "Limite máximo de garantia (LMG)",
        "definition_clause": "ato regulatório/contratual do produto securitário",
        "definition": "montante máximo indenizável definido pelas condições contratuais",
        "produced_by": ["definicao_contratual_apolice"],
        "derivable_from_market_regression": False,
        "note": "Não é um tipo de valor da ABNT NBR 14653-1; é cláusula do contrato de seguro.",
    },
}


def value_basis_guard(basis_id: str, produced_by_method: str) -> Dict[str, Any]:
    """Refuse a base of value that the declared method cannot produce.

    This is the A06 guard: a comparative-method regression estimates market
    value and must never be converted into a reconstruction cost or into a
    contractual guarantee limit by an arbitrary coefficient.
    """
    basis = VALUE_BASES.get(basis_id)
    if basis is None:
        return {
            "status": "unsupported",
            "basis": basis_id,
            "detail": f"base de valor desconhecida: {basis_id!r}; não há regra registrada.",
        }
    if produced_by_method in basis["produced_by"]:
        return {
            "status": "ok",
            "basis": basis_id,
            "method": produced_by_method,
            "definition_clause": basis["definition_clause"],
            "detail": f"{basis['label']} é produzido por {produced_by_method}.",
        }
    return {
        "status": "refused",
        "basis": basis_id,
        "method": produced_by_method,
        "definition_clause": basis["definition_clause"],
        "required_method": list(basis["produced_by"]),
        "required_memory": basis.get("required_memory") or [],
        "detail": (
            f"{basis['label']} ({basis['definition_clause']}) NÃO é produzido por "
            f"{produced_by_method}. Exige {basis['produced_by']}. Converter preço de "
            "mercado nessa base por coeficiente é vedado: são grandezas distintas."
        ),
    }


# --- 10.1: conteúdo mínimo do laudo completo ---------------------------------

LAUDO_COMPLETO_ITEMS: List[Dict[str, Any]] = [
    {"key": "a", "id": "10.1.a", "requirement": "identificação do solicitante"},
    {"key": "b", "id": "10.1.b", "requirement": "finalidade do laudo, quando informada pelo solicitante"},
    {"key": "c", "id": "10.1.c", "requirement": "objetivo da avaliação"},
    {"key": "d", "id": "10.1.d", "requirement": "pressupostos, ressalvas e fatores limitantes",
     "cross_reference": "7.2 da ABNT NBR 14653-1:2001 (renumerada na edição 2019)"},
    {"key": "e", "id": "10.1.e", "requirement": "identificação e caracterização do imóvel avaliando",
     "cross_reference": "7.3 da ABNT NBR 14653-1:2001, no que couber"},
    {"key": "f", "id": "10.1.f", "requirement": "diagnóstico do mercado",
     "cross_reference": "7.7.2 da ABNT NBR 14653-1:2001"},
    {"key": "g", "id": "10.1.g", "requirement": "indicação do(s) método(s) e procedimento(s) utilizado(s)",
     "cross_reference": "Seção 8 da ABNT NBR 14653-1:2001"},
    {"key": "h", "id": "10.1.h", "requirement": (
        "especificação da avaliação: grau de fundamentação e de precisão atingidos; "
        "demonstrativo da pontuação quando solicitado pelo contratante")},
    {"key": "i", "id": "10.1.i", "requirement": "planilha dos dados utilizados"},
    {"key": "j", "id": "10.1.j", "requirement": (
        "no método comparativo: descrição das variáveis do modelo, com o critério de "
        "enquadramento de cada característica dos elementos amostrais e a escala das "
        "diferenças qualitativas")},
    {"key": "k", "id": "10.1.k", "requirement": (
        "tratamento dos dados e identificação do resultado: cálculos efetuados, campo de "
        "arbítrio se for o caso, justificativas do resultado adotado e, no método "
        "comparativo, o gráfico de preços observados versus valores estimados pelo modelo")},
    {"key": "l", "id": "10.1.l", "requirement": "resultado da avaliação e sua data de referência"},
    {"key": "m", "id": "10.1.m", "requirement": (
        "qualificação legal completa e assinatura do(s) profissional(is) responsável(is)")},
]

#: 9.2.1.1: additional obligations to reach Grau III, beyond the Tabela 1 points.
GRAU_III_ADDITIONAL_REQUIREMENTS: List[Dict[str, Any]] = [
    {"id": "9.2.1.1.a", "requirement": "apresentação do laudo na modalidade completa",
     "verification": "documental"},
    {"id": "9.2.1.1.b", "requirement": (
        "análise do modelo no laudo, com verificação da coerência do comportamento da "
        "variação das variáveis em relação ao mercado e suas elasticidades em torno do "
        "ponto de estimação"),
     "verification": "professional_evidenced",
     "note": "As elasticidades são calculáveis; a COERÊNCIA com o mercado é juízo profissional."},
    {"id": "9.2.1.1.c", "requirement": (
        "identificação completa dos endereços dos dados de mercado usados no modelo e das "
        "fontes de informação"),
     "verification": "documental"},
    {"id": "9.2.1.1.d", "requirement": "adoção da estimativa de tendência central",
     "verification": "calculated"},
]

#: 9.1.2: when not even Grau I is reached, the laudo must identify and justify
#: the unmet items — the standard's own route for a non-classified result.
NAO_CLASSIFICADO_OBLIGATION = {
    "id": "9.1.2",
    "clause": "9.1.2",
    "requirement": (
        "Nos casos em que o grau mínimo I não for atingido, devem ser indicados e "
        "justificados os itens das tabelas de especificação que não puderam ser atendidos, "
        "bem como os procedimentos e cálculos utilizados na identificação do valor."
    ),
    "consequence": (
        "Um resultado não classificado NÃO é um beco sem saída normativo: é uma via "
        "prevista, condicionada a indicação e justificativa explícitas. É exatamente o "
        "que sustenta o estado analysis_only do produto."
    ),
}

#: 6.3.1 (Parte 1:2019): vistoria is essential; a situação-paradigma is
#: admitted only exceptionally, agreed between the parties and stated in the
#: laudo. Tabela 1 item 1 Grau I is precisely "adoção de situação paradigma".
VISTORIA_REQUIREMENT = {
    "id": "parte1.6.3.1",
    "edition": EDITION_PART1_2019,
    "clause": "6.3.1 / 6.3.2 / 6.3.3",
    "requirement": (
        "A vistoria é atividade essencial. Em casos excepcionais, quando impossível ou "
        "inviável, admite-se situação-paradigma, desde que acordada entre as partes e "
        "explicitada no laudo. Recomenda-se que a vistoria seja realizada pelo "
        "responsável técnico."
    ),
    "verification": "professional_evidenced",
    "link_to_tabela1": "Tabela 1 item 1 Grau I corresponde à adoção de situação-paradigma.",
}

#: 6 a) e b) (Parte 1:2019): the standard's own taxonomy of finalidade and
#: objetivo. The qualification profile reuses it instead of inventing one.
FINALIDADES = [
    "locação", "arrendamento", "comodato", "aquisição", "doação", "alienação",
    "dação em pagamento", "permuta", "garantia", "fins contábeis", "seguro",
    "arrematação", "adjudicação", "indenização", "tributação",
]
OBJETIVOS = [
    "valor de mercado de compra e venda", "valor de mercado de locação",
    "valor em risco", "valor patrimonial", "valor econômico", "custo de reedição",
    "valor de liquidação forçada", "valor de desmonte", "indicadores de viabilidade",
]
FINALIDADE_OBJETIVO_SOURCE = {
    "edition": EDITION_PART1_2019, "clause": "Seção 6 a) e b)", "page": 23,
    "note": "6.6: a metodologia deve ser compatível com a natureza do bem, o objetivo e a finalidade.",
}
