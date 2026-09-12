"""Unify monetary intervals. Statistical bands are not ±percent bands.

mean_ci80, prediction_interval, arbitration_interval and admissible_interval
are distinct. A percentage band is never a stand-in for a missing residual
state. Arbitration/admissible bands come from a C05 rule when present; they
are left null (with an explicit limitation) when that rule is unavailable.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Tuple

INTERVAL_POLICY_ID = "MP-C01-INTERVAL/1"

STAT_KEYS = ("mean_ci80", "prediction_interval")
POLICY_KEYS = ("arbitration_interval", "admissible_interval")


def interval_policy_id() -> str:
    return INTERVAL_POLICY_ID


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


def _copy_interval(block: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(block, Mapping):
        return None
    lower = _finite(block.get("lower"))
    upper = _finite(block.get("upper"))
    if lower is None or upper is None:
        return None
    if lower > upper:
        lower, upper = upper, lower
    out = dict(block)
    out["lower"] = lower
    out["upper"] = upper
    return out


def _c05_interval_rule(rule_bundle: Any, name: str) -> Optional[Dict[str, Any]]:
    if not isinstance(rule_bundle, Mapping):
        return None
    intervals = rule_bundle.get("intervals") or rule_bundle.get("value_intervals")
    if isinstance(intervals, Mapping) and name in intervals:
        copied = _copy_interval(intervals.get(name))
        if copied is not None:
            copied.setdefault("source", "c05.interval_rule")
            copied.setdefault("kind", name)
            return copied
    direct = rule_bundle.get(name)
    return _copy_interval(direct)


def compose_value_intervals(
    *,
    point: Any,
    mean_ci80: Any = None,
    prediction_interval: Any = None,
    c05_interval_rule: Any = None,
    residual_complete: bool = True,
    limitations: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """Return the five-key value block plus limitation codes.

    Never writes point*(1±k) as a statistical interval. Never fills
    arbitration_interval from a hardcoded 15% when C05 did not supply a rule.
    """
    notes: List[str] = list(limitations or [])
    value = {
        "point": _finite(point),
        "mean_ci80": _copy_interval(mean_ci80) if residual_complete else None,
        "prediction_interval": _copy_interval(prediction_interval) if residual_complete else None,
        "arbitration_interval": None,
        "admissible_interval": None,
    }
    if not residual_complete:
        if "residual_state_incomplete" not in notes:
            notes.append("residual_state_incomplete")
        if "percent_band_not_statistical_interval" not in notes:
            notes.append("percent_band_not_statistical_interval")

    arb = _c05_interval_rule(c05_interval_rule, "arbitration_interval")
    adm = _c05_interval_rule(c05_interval_rule, "admissible_interval")
    if arb is not None:
        arb["kind"] = arb.get("kind") or "arbitration_interval"
        arb["not_statistical"] = True
        value["arbitration_interval"] = arb
    else:
        if "arbitration_rule_unverified" not in notes:
            notes.append("arbitration_rule_unverified")
    if adm is not None:
        adm["kind"] = adm.get("kind") or "admissible_interval"
        value["admissible_interval"] = adm
    else:
        if "admissible_interval_rule_unverified" not in notes:
            notes.append("admissible_interval_rule_unverified")

    if value["mean_ci80"] is None and residual_complete:
        if "mean_ci80_not_computed" not in notes:
            notes.append("mean_ci80_not_computed")
    return value, notes
