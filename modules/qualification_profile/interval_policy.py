"""Resolve the verified arbitration policy for a qualified market profile."""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional

from modules import normative_rules

from .catalog import ProfileError, resolve_profile
from .schema import PROFILE_VERIFIED


POLICY_SCHEMA = "MP-ARBITRATION-POLICY/1"
MARKET_METHOD = "metodo_comparativo_direto_regressao"
MARKET_VALUE_BASIS = "valor_de_mercado"


def _finite(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def resolve_arbitration_policy(profile_reference: Any) -> Optional[Dict[str, Any]]:
    """Return a declarative percent-around-point rule only from verified authority.

    The request selects a catalog profile; it does not supply the percentage.
    Unknown, conflicting or inapplicable authority fails closed as ``None``.
    """
    if not isinstance(profile_reference, Mapping) or any(
        not profile_reference.get(field)
        for field in ("id", "version", "source_set_sha256")
    ):
        return None
    try:
        profile = resolve_profile(profile_reference)
    except (ProfileError, TypeError, ValueError):
        return None
    if (
        profile.get("resolved") is not True
        or profile.get("state") != PROFILE_VERIFIED
        or profile.get("method") != MARKET_METHOD
        or profile.get("value_basis") != MARKET_VALUE_BASIS
        or not profile.get("source_set_sha256")
        or not profile.get("sources")
    ):
        return None

    provenance = normative_rules.THRESHOLD_PROVENANCE.get("CAMPO_ARBITRIO")
    matching_rules = [
        rule for rule in normative_rules.RULE_MATRIX
        if rule.get("id") == "campo_arbitrio"
    ]
    if not isinstance(provenance, Mapping) or len(matching_rules) != 1:
        return None
    rule = matching_rules[0]
    if rule.get("verification_status") != "verified":
        return None
    amplitude = _finite((provenance.get("values") or {}).get("amplitude"))
    registry_value = _finite(getattr(normative_rules, "CAMPO_ARBITRIO", None))
    if amplitude is None or not 0.0 <= amplitude <= 1.0 or registry_value != amplitude:
        return None
    try:
        from modules.config_manager import Config

        configured = _finite(getattr(Config, "CAMPO_ARBITRIO", None))
    except (ImportError, TypeError, ValueError):
        configured = None
    if configured is not None and configured != amplitude:
        return None
    if provenance.get("edition") != rule.get("edition"):
        return None

    source = {
        "authority": "modules.normative_rules",
        "threshold_key": "CAMPO_ARBITRIO",
        "rule_id": "campo_arbitrio",
        "edition": provenance.get("edition"),
        "clause": provenance.get("clause"),
        "page": provenance.get("page"),
        "verification_status": "verified",
        "profile_id": profile.get("id"),
        "profile_version": profile.get("version"),
        "profile_source_set_sha256": profile.get("source_set_sha256"),
    }
    return {
        "schema_version": POLICY_SCHEMA,
        "applicability": "verified_market_regression_profile",
        "arbitration": {
            "method": "percent_around_point",
            "percent": amplitude * 100.0,
            "source": source,
        },
        "source": source,
    }
