"""Validated reconstruction/replacement/depreciated cost calculation.

The engine sums only case inputs: it embeds neither CUB tables nor licensed
price schedules. Market value is deliberately ignored. Documentary grades
are derived from evidence-bearing calculation modes, never client grades.
"""
from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from modules.normative_rules import classify_custo_fundamentacao

SCHEMA_VERSION = "MP-COST/1"
BOM_SCHEMA_VERSION = "MP-COST-BOM/1"
LAND_CATEGORIES = frozenset({"land", "terreno", "ground"})
EXCLUSION_CATEGORIES = frozenset({"exclusion", "excluded", "not_covered"})
BUILDING_CATEGORIES = frozenset({"building_component", "component", "item", "quantity", "additional_expense", "expense"})
KNOWN_CATEGORIES = LAND_CATEGORIES | EXCLUSION_CATEGORIES | BUILDING_CATEGORIES
VALUE_BASIS = frozenset({"reconstruction_cost", "replacement_cost", "depreciated_cost"})
DIRECT_GRADES = {"synthetic_budget": 3, "cub_similar": 2, "cub_adjusted": 1}
BDI_GRADES = {"calculated": 3, "justified": 2, "arbitrated": 1}
DEPRECIATION_GRADES = {"recovery_cost": 3, "new_asset": 3, "technical_method": 2, "arbitrated": 1}
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def _finite(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _source_ref(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if not isinstance(value, Mapping):
        return None
    for key in ("reference", "ref", "id", "document_id", "title"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _issue(code: str, message: str, *, affected_ids: Sequence[str] = (), evidence: Any = None) -> dict:
    return {"code": code, "severity": "error", "origin": "c01.cost_valuation", "message": message,
            "affected_ids": list(affected_ids), "evidence": dict(evidence) if isinstance(evidence, Mapping) else {}}


def land_not_implicit(items: Sequence[Mapping[str, Any]]) -> bool:
    return not any(str(item.get("category") or "").lower() in LAND_CATEGORIES for item in items)


def _empty_value(basis: str, currency: Any) -> dict:
    return {"point": None, "mean_ci80": None, "prediction_interval": None,
            "arbitration_interval": None, "admissible_interval": None, "basis": basis,
            "estimand": "depreciated_reconstruction_cost" if basis == "depreciated_cost" else "reconstruction_cost_sum",
            "unit": currency}


def _evidence_item(item: int, mode: Optional[str], grade: Optional[int], source: Any, detail: str) -> dict:
    return {"item": item, "id": f"tabela6.item{item}", "grade": grade, "mode": mode,
            "evidence_status": "verified" if grade is not None else "pending",
            "provenance_verified": grade is not None and _source_ref(source) is not None,
            "provenance": _source_ref(source), "source": source, "detail": detail}


def _direct_grade(direct: Any, items: Sequence[Mapping[str, Any]]) -> dict:
    if not isinstance(direct, Mapping):
        return _evidence_item(1, None, None, None, "Modalidade/fonte do custo direto não informada.")
    mode = str(direct.get("mode") or "")
    source = direct.get("source")
    grade = DIRECT_GRADES.get(mode) if _source_ref(source) else None
    if mode == "cub_adjusted" and not (direct.get("adjustments") or direct.get("justification")):
        grade = None
    if not items:
        grade = None
    return _evidence_item(1, mode or None, grade, source, "Grau derivado da modalidade e da fonte do custo direto.")


def _bdi(bdi: Any) -> Tuple[Optional[float], dict, List[dict], bool]:
    if bdi is None:
        return 0.0, _evidence_item(2, None, None, None, "BDI não informado; zero não é evidência documental."), [], True
    if not isinstance(bdi, Mapping):
        return None, _evidence_item(2, None, None, None, "BDI inválido."), [_issue("bdi_invalid", "BDI deve ser um objeto.")], False
    mode, source, rate = str(bdi.get("mode") or ""), bdi.get("source"), _finite(bdi.get("rate"))
    errors: List[dict] = []
    if mode not in BDI_GRADES:
        errors.append(_issue("bdi_mode_unknown", "Modalidade de BDI desconhecida.", evidence={"mode": mode}))
    if rate is None or rate < 0:
        errors.append(_issue("bdi_rate_invalid", "Taxa de BDI deve ser finita e não negativa.", evidence={"rate": bdi.get("rate")}))
    if not _source_ref(source):
        errors.append(_issue("bdi_source_missing", "BDI informado exige referência de fonte."))
    if mode == "calculated":
        components = bdi.get("components")
        if not isinstance(components, Mapping) or not components:
            errors.append(_issue("bdi_components_missing", "BDI calculado exige componentes identificados."))
        else:
            values = [_finite(value) for value in components.values()]
            if any(value is None or value < 0 for value in values):
                errors.append(_issue("bdi_component_invalid", "Componentes do BDI devem ser finitos e não negativos."))
            else:
                formula = str(bdi.get("formula") or "additive")
                calculated = (sum(value for value in values if value is not None) if formula == "additive"
                              else math.prod(1.0 + value for value in values if value is not None) - 1.0 if formula == "compound" else None)
                if calculated is None:
                    errors.append(_issue("bdi_formula_unknown", "Fórmula de BDI deve ser additive ou compound."))
                elif rate is not None and not math.isclose(rate, calculated, rel_tol=1e-12, abs_tol=1e-12):
                    errors.append(_issue("bdi_rate_mismatch", "Taxa de BDI diverge dos componentes.", evidence={"rate": rate, "calculated_rate": calculated}))
    elif mode in {"justified", "arbitrated"} and not str(bdi.get("justification") or "").strip():
        errors.append(_issue("bdi_justification_missing", "BDI justificado/arbitrado exige justificativa."))
    evidence = _evidence_item(2, mode or None, BDI_GRADES.get(mode) if not errors else None, source,
                              "Grau derivado do cálculo/justificativa e fonte do BDI.")
    return rate, evidence, errors, not errors


def _depreciation(dep: Any, *, required: bool) -> Tuple[Optional[float], dict, List[dict], bool]:
    if dep is None:
        ev = _evidence_item(3, None, None, None, "Depreciação não informada.")
        return (None if required else 0.0), ev, ([_issue("depreciation_missing", "Base depreciada exige depreciação explícita; ausência não autoriza custo bruto.")] if required else []), not required
    if not isinstance(dep, Mapping):
        return None, _evidence_item(3, None, None, None, "Depreciação inválida."), [_issue("depreciation_invalid", "Depreciação deve ser um objeto.")], False
    mode, source, rate = str(dep.get("mode") or ""), dep.get("source"), _finite(dep.get("rate"))
    errors: List[dict] = []
    if mode == "recovery_cost":
        new_cost, recovery_cost = _finite(dep.get("new_cost")), _finite(dep.get("recovery_cost"))
        if new_cost is None or new_cost <= 0 or recovery_cost is None or recovery_cost < 0 or recovery_cost > new_cost:
            errors.append(_issue("depreciation_recovery_invalid", "Custo de recuperação exige recovery_cost entre zero e new_cost positivo."))
        else:
            derived = recovery_cost / new_cost
            if rate is not None and not math.isclose(rate, derived, rel_tol=1e-12, abs_tol=1e-12):
                errors.append(_issue("depreciation_rate_mismatch", "Taxa de depreciação diverge do custo de recuperação."))
            rate = derived
    elif mode == "new_asset":
        rate = 0.0 if rate is None else rate
        if rate != 0:
            errors.append(_issue("depreciation_new_asset_nonzero", "Bem novo deve registrar taxa de depreciação zero."))
    elif mode == "technical_method":
        if not all(dep.get(key) not in (None, "") for key in ("method", "age", "useful_life", "condition")):
            errors.append(_issue("depreciation_technical_evidence_missing", "Método técnico exige método, idade, vida útil e estado de conservação."))
    elif mode == "arbitrated":
        if not str(dep.get("justification") or "").strip():
            errors.append(_issue("depreciation_justification_missing", "Depreciação arbitrada exige justificativa."))
    else:
        errors.append(_issue("depreciation_mode_unknown", "Modalidade de depreciação desconhecida.", evidence={"mode": mode}))
    if rate is None or rate < 0 or rate >= 1:
        errors.append(_issue("depreciation_invalid", "Taxa de depreciação deve estar em [0, 1).", evidence={"rate": dep.get("rate")}))
    if not _source_ref(source):
        errors.append(_issue("depreciation_source_missing", "Depreciação informada exige referência de fonte."))
    ev = _evidence_item(3, mode or None, DEPRECIATION_GRADES.get(mode) if not errors else None, source,
                        "Grau derivado do método e da evidência da depreciação física.")
    return rate, ev, errors, not errors


def compute_reconstruction_cost(bom: Any, *, market_point: Any = None,
                                value_basis: str = "reconstruction_cost",
                                include_depreciation: bool = False) -> Dict[str, Any]:
    """Validate and calculate an explicit BOM with a replayable memory."""
    basis = str(value_basis)
    basis_error = None
    if basis not in VALUE_BASIS:
        basis_error = _issue("cost_value_basis_unknown", "Base de custo desconhecida; nenhum resultado foi calculado.", evidence={"value_basis": value_basis})
        basis = "reconstruction_cost"
    currency = bom.get("currency") if isinstance(bom, Mapping) else None
    value = _empty_value(basis, currency)
    if not isinstance(bom, Mapping):
        return {"schema_version": SCHEMA_VERSION, "bom_schema_version": None, "computable": False,
                "reason": "cost_bom_missing", "value": value, "items": [], "exclusions": [],
                "land_present": False, "land_included": False, "used_market_factor": False,
                "market_point_ignored": _finite(market_point), "reference_location": None, "reference_date": None,
                "fundamentacao": {**classify_custo_fundamentacao({1: None, 2: None, 3: None}), "items": []},
                "issues": [_issue("cost_bom_missing", "BOM/fonte de custo ausente; nenhuma estimativa foi produzida.")]}

    issues: List[dict] = [basis_error] if basis_error else []
    if bom.get("schema_version") != BOM_SCHEMA_VERSION:
        issues.append(_issue(
            "cost_bom_schema_invalid",
            f"cost_bom.schema_version deve ser {BOM_SCHEMA_VERSION}.",
            evidence={"schema_version": bom.get("schema_version")},
        ))
    reference_location = bom.get("reference_location") or bom.get("location")
    reference_date = bom.get("reference_date")
    if not isinstance(reference_location, str) or not reference_location.strip() or not _valid_date(reference_date):
        issues.append(_issue("cost_reference_invalid", "Referência local e data ISO válida são obrigatórias.", evidence={"reference_location": reference_location, "reference_date": reference_date}))
    if not isinstance(currency, str) or not _CURRENCY_RE.fullmatch(currency):
        issues.append(_issue("cost_currency_invalid", "Moeda deve ser código ISO 4217 em três letras maiúsculas.", evidence={"currency": currency}))
    raw_items = bom.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        issues.append(_issue("cost_items_missing", "BOM deve conter ao menos um item.")); raw_items = []
    accepted: List[dict] = []; exclusions: List[dict] = []; direct_items: List[dict] = []
    direct_subtotal = land_subtotal = 0.0
    land_present = land_included = False
    for index, raw in enumerate(raw_items):
        item_id = str(raw.get("item_id") or f"item-{index + 1}") if isinstance(raw, Mapping) else f"item-{index + 1}"
        if not isinstance(raw, Mapping):
            issues.append(_issue("cost_item_invalid", "Item do BOM deve ser objeto.", affected_ids=[item_id])); continue
        category = str(raw.get("category") or "")
        if category not in KNOWN_CATEGORIES:
            issues.append(_issue("cost_category_unknown", "Categoria de custo desconhecida.", affected_ids=[item_id], evidence={"category": category})); continue
        if category in EXCLUSION_CATEGORIES:
            exclusions.append({"item_id": item_id, "reason": raw.get("reason") or "excluded"}); continue
        quantity, unit_cost = _finite(raw.get("quantity")), _finite(raw.get("unit_cost"))
        extra = _finite(raw.get("additional_expenses", 0))
        item_source = raw.get("source") or raw.get("origin")
        item_currency, item_date = raw.get("currency", currency), raw.get("reference_date", reference_date)
        item_location = raw.get("location", reference_location)
        bad = False
        if quantity is None or unit_cost is None or extra is None or quantity < 0 or unit_cost < 0 or extra < 0:
            issues.append(_issue("cost_item_amount_invalid", "Quantidade, custo unitário e despesa adicional devem ser finitos e não negativos.", affected_ids=[item_id])); bad = True
        if not _source_ref(item_source):
            issues.append(_issue("cost_item_source_missing", "Cada item incluído exige fonte identificada.", affected_ids=[item_id])); bad = True
        if item_currency != currency:
            issues.append(_issue("cost_currency_mismatch", "Conversão de moeda não é implícita.", affected_ids=[item_id], evidence={"item_currency": item_currency, "bom_currency": currency})); bad = True
        if item_date != reference_date:
            issues.append(_issue("cost_reference_date_mismatch", "Atualização temporal não é implícita; data do item deve coincidir com a data-base.", affected_ids=[item_id], evidence={"item_date": item_date, "reference_date": reference_date})); bad = True
        if item_location != reference_location:
            issues.append(_issue("cost_reference_location_mismatch", "Ajuste geográfico não é implícito; local do item deve coincidir com a referência.", affected_ids=[item_id], evidence={"item_location": item_location, "reference_location": reference_location})); bad = True
        if bad: continue
        amount = quantity * unit_cost + extra
        normalized = {"item_id": item_id, "description": raw.get("description"), "category": category,
                      "quantity": quantity, "unit": raw.get("unit"), "unit_cost": unit_cost,
                      "additional_expenses": extra, "amount": amount, "currency": currency,
                      "source": item_source, "location": item_location,
                      "reference_date": item_date}
        if category in LAND_CATEGORIES:
            land_present = True
            if raw.get("include_land") is not True:
                exclusions.append({"item_id": item_id, "reason": "land_not_explicitly_included"}); continue
            land_included = True; land_subtotal += amount
        else:
            direct_items.append(normalized); direct_subtotal += amount
        accepted.append(normalized)

    item1 = _direct_grade(bom.get("direct_cost"), direct_items)
    bdi_rate, item2, bdi_issues, bdi_valid = _bdi(bom.get("bdi")); issues.extend(bdi_issues)
    depreciation_required = include_depreciation or basis == "depreciated_cost"
    dep_rate, item3, dep_issues, dep_valid = _depreciation(bom.get("depreciation"), required=depreciation_required); issues.extend(dep_issues)
    bdi_amount = direct_subtotal * bdi_rate if bdi_valid and bdi_rate is not None else None
    reproduction_building = direct_subtotal + bdi_amount if bdi_amount is not None else None
    depreciation_amount = reproduction_building * dep_rate if reproduction_building is not None and dep_valid and dep_rate is not None else None
    depreciated_building = reproduction_building - depreciation_amount if reproduction_building is not None and depreciation_amount is not None else None
    computable = bool(direct_items and not issues and reproduction_building is not None)
    if computable:
        building_value = depreciated_building if depreciation_required else reproduction_building
        if building_value is None: computable = False
        else: value["point"] = float(building_value + land_subtotal)
    scores = {1: item1.get("grade"), 2: item2.get("grade"), 3: item3.get("grade")}
    fundamentacao = dict(classify_custo_fundamentacao(scores)); fundamentacao["items"] = [item1, item2, item3]
    return {"schema_version": SCHEMA_VERSION, "bom_schema_version": bom.get("schema_version"),
            "computable": computable, "reason": None if computable else (issues[0]["code"] if issues else "cost_not_computable"),
            "value": value, "items": accepted, "exclusions": exclusions,
            "land_present": land_present, "land_included": land_included,
            "used_market_factor": False, "market_point_ignored": _finite(market_point),
            "reference_location": reference_location, "reference_date": reference_date, "currency": currency,
            "memory": {"direct_subtotal": direct_subtotal, "bdi_rate": bdi_rate, "bdi_amount": bdi_amount,
                       "reproduction_building": reproduction_building, "depreciation_rate": dep_rate,
                       "depreciation_amount": depreciation_amount, "depreciated_building": depreciated_building,
                       "land_subtotal": land_subtotal, "total": value.get("point"),
                       "formula": "direct + BDI - physical depreciation + explicitly included land",
                       "automatic_currency_or_date_adjustment": False},
            "fundamentacao": fundamentacao, "issues": issues}
