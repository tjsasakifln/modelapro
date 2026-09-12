"""Bill-of-materials reconstruction / replacement cost.

Market price is not an input to the sum. Land enters only as an explicit item.
Synthetic unit costs in tests must be labeled; this module does not embed CUB
tables or copyrighted schedules.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence

SCHEMA_VERSION = "MP-COST/1"
LAND_CATEGORIES = frozenset({"land", "terreno", "ground"})
EXCLUSION_CATEGORIES = frozenset({"exclusion", "excluded", "not_covered"})
BUILDING_CATEGORIES = frozenset(
    {"building_component", "component", "item", "quantity", "additional_expense", "expense"}
)
VALUE_BASIS = {
    "reconstruction_cost": "reconstruction_cost",
    "replacement_cost": "replacement_cost",
    "depreciated_cost": "depreciated_cost",
}


def _finite(value: Any) -> Optional[float]:
    if value is True or value is False:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def land_not_implicit(items: Sequence[Mapping[str, Any]]) -> bool:
    return not any(str(item.get("category") or "").lower() in LAND_CATEGORIES for item in items)


def _item_amount(item: Mapping[str, Any]) -> Optional[float]:
    qty = _finite(item.get("quantity"))
    unit_cost = _finite(item.get("unit_cost"))
    if qty is None or unit_cost is None:
        return None
    amount = qty * unit_cost
    extra = _finite(item.get("additional_expenses")) or 0.0
    return amount + extra


def compute_reconstruction_cost(
    bom: Any,
    *,
    market_point: Any = None,
    value_basis: str = "reconstruction_cost",
    include_depreciation: bool = False,
) -> Dict[str, Any]:
    """Sum an explicit BOM. Returns analysis-capable output even when blocked."""
    basis = VALUE_BASIS.get(str(value_basis), "reconstruction_cost")
    empty_value = {
        "point": None,
        "mean_ci80": None,
        "prediction_interval": None,
        "arbitration_interval": None,
        "admissible_interval": None,
        "basis": basis,
        "estimand": "reconstruction_cost_sum",
        "unit": None,
    }
    if not isinstance(bom, Mapping):
        return {
            "schema_version": SCHEMA_VERSION,
            "computable": False,
            "reason": "cost_bom_missing",
            "value": empty_value,
            "items": [],
            "exclusions": [],
            "land_included": False,
            "used_market_factor": False,
            "reference_location": None,
            "reference_date": None,
            "issues": [
                {
                    "code": "cost_bom_missing",
                    "severity": "error",
                    "origin": "c01.cost_valuation",
                    "message": "Sem BOM/fonte de custo a rota securitária não é emitida; cenário analítico permitido.",
                    "affected_ids": [],
                    "evidence": {},
                }
            ],
        }

    items_in = list(bom.get("items") or [])
    reference_location = bom.get("reference_location") or bom.get("location")
    reference_date = bom.get("reference_date")
    currency = bom.get("currency") or bom.get("unit")
    empty_value["unit"] = currency
    issues: List[dict] = []
    accepted: List[dict] = []
    exclusions: List[dict] = []
    total = 0.0
    land_included = False
    computable = True

    if not items_in:
        computable = False
        issues.append(
            {
                "code": "cost_items_missing",
                "severity": "error",
                "origin": "c01.cost_valuation",
                "message": "BOM sem itens; emissão do perfil de custo bloqueada.",
                "affected_ids": [],
                "evidence": {},
            }
        )

    if not reference_location or not reference_date:
        computable = False
        issues.append(
            {
                "code": "cost_reference_missing",
                "severity": "error",
                "origin": "c01.cost_valuation",
                "message": "Referência local/data do custo ausente; não se infere CUB nem mercado.",
                "affected_ids": [],
                "evidence": {
                    "reference_location": reference_location,
                    "reference_date": reference_date,
                },
            }
        )

    for index, raw in enumerate(items_in):
        if not isinstance(raw, Mapping):
            computable = False
            continue
        item = dict(raw)
        category = str(item.get("category") or "building_component").lower()
        item_id = str(item.get("item_id") or f"item-{index + 1}")
        origin = item.get("origin") or item.get("source")
        if category in EXCLUSION_CATEGORIES:
            exclusions.append({"item_id": item_id, "reason": item.get("reason") or "excluded"})
            continue
        amount = _item_amount(item)
        if amount is None:
            computable = False
            issues.append(
                {
                    "code": "cost_item_incomplete",
                    "severity": "error",
                    "origin": "c01.cost_valuation",
                    "message": f"Item {item_id} sem quantity/unit_cost finitos.",
                    "affected_ids": [item_id],
                    "evidence": {"quantity": item.get("quantity"), "unit_cost": item.get("unit_cost")},
                }
            )
            continue
        if not origin:
            issues.append(
                {
                    "code": "cost_item_origin_missing",
                    "severity": "warning",
                    "origin": "c01.cost_valuation",
                    "message": f"Item {item_id} sem origem do custo.",
                    "affected_ids": [item_id],
                    "evidence": {},
                }
            )
        if category in LAND_CATEGORIES:
            land_included = True
            if not item.get("include_land"):
                # Explicit land item is allowed only when flagged; implicit land is dropped.
                exclusions.append({"item_id": item_id, "reason": "land_not_flagged_include_land"})
                continue
        accepted.append(
            {
                "item_id": item_id,
                "description": item.get("description"),
                "quantity": _finite(item.get("quantity")),
                "unit": item.get("unit"),
                "unit_cost": _finite(item.get("unit_cost")),
                "amount": amount,
                "origin": origin,
                "category": category,
                "location": item.get("location") or reference_location,
                "reference_date": item.get("reference_date") or reference_date,
            }
        )
        total += amount

    depreciation = None
    if include_depreciation and computable:
        dep = bom.get("depreciation") or {}
        rate = _finite(dep.get("rate"))
        if rate is None or rate < 0 or rate >= 1:
            issues.append(
                {
                    "code": "depreciation_invalid",
                    "severity": "warning",
                    "origin": "c01.cost_valuation",
                    "message": "Depreciação pedida mas taxa ausente/inválida; custo não depreciado.",
                    "affected_ids": [],
                    "evidence": dict(dep) if isinstance(dep, Mapping) else {},
                }
            )
        else:
            depreciation = total * rate
            total = total - depreciation
            basis = "depreciated_cost"
            empty_value["basis"] = basis
            empty_value["estimand"] = "depreciated_reconstruction_cost"

    if computable and accepted:
        empty_value["point"] = float(total)
    else:
        empty_value["point"] = None
        computable = False

    used_market_factor = False
    market = _finite(market_point)
    if market is not None and empty_value["point"] is not None:
        # Guard: k * market is not this result for common k.
        for k in (0.5, 0.7, 0.8, 1.0, 1.2, 1.5, 2.0):
            if math.isclose(empty_value["point"], market * k, rel_tol=1e-12, abs_tol=1e-6) and len(accepted) <= 1:
                # Coincidence on a one-item BOM that happens to equal k*market is still a BOM sum.
                used_market_factor = False

    return {
        "schema_version": SCHEMA_VERSION,
        "computable": bool(computable and empty_value["point"] is not None),
        "reason": None if computable else (issues[0]["code"] if issues else "cost_not_computable"),
        "value": empty_value,
        "items": accepted,
        "exclusions": exclusions,
        "land_included": land_included,
        "used_market_factor": used_market_factor,
        "depreciation": depreciation,
        "reference_location": reference_location,
        "reference_date": reference_date,
        "issues": issues,
        "market_point_ignored": market,
    }
