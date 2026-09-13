"""Controlled snapshot mutations and detectors.

Each detector must fail for the intended cause. A fixture that is invalid
for another reason is not a pass. No product imports.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Mapping


CAUSES = (
    "wrong_coefficient_order",
    "missing_ci",
    "percent_band_replacing_uncertainty",
    "none_instead_of_holdout",
    "swapped_unit",
    "omitted_row",
    "incompatible_recommendation",
)


def _deep(obj: Any) -> Any:
    return copy.deepcopy(obj)


def mutate(snapshot: Mapping[str, Any], cause: str) -> Dict[str, Any]:
    if cause not in CAUSES:
        raise ValueError(cause)
    snap = _deep(dict(snapshot))
    if cause == "wrong_coefficient_order":
        coefs = list(((snap.get("model") or {}).get("coefficients") or []))
        if len(coefs) >= 2:
            coefs[0], coefs[1] = coefs[1], coefs[0]
            snap.setdefault("model", {})["coefficients"] = coefs
        else:
            mapping = dict((snap.get("model") or {}).get("coefficients") or {})
            items = list(mapping.items())
            if len(items) >= 2:
                items[0], items[1] = items[1], items[0]
                snap.setdefault("model", {})["coefficients"] = dict(items)
    elif cause == "missing_ci":
        snap.setdefault("value", {})["mean_ci80"] = None
    elif cause == "percent_band_replacing_uncertainty":
        point = (snap.get("value") or {}).get("point")
        if point is None:
            point = 100.0
        p = float(point)
        snap.setdefault("value", {})["mean_ci80"] = {"lower": p * 0.9, "upper": p * 1.1, "kind": "percent_band"}
        snap["value"]["prediction_interval"] = {"lower": p * 0.8, "upper": p * 1.2, "kind": "percent_band"}
    elif cause == "none_instead_of_holdout":
        snap.setdefault("validation", {}).setdefault("statistical", {})["procedure"] = {
            "method": "none",
            "usable_for_model_selection": True,
        }
        req = snap.setdefault("provenance", {}).setdefault("request_spec", {})
        req.setdefault("evaluation_policy", {})["method"] = "none"
    elif cause == "swapped_unit":
        current = (snap.get("target") or {}).get("unit")
        snap.setdefault("target", {})["unit"] = "BRL/m2" if current != "BRL/m2" else "ft2"
    elif cause == "omitted_row":
        used = list((snap.get("sample") or {}).get("used_row_ids") or [])
        if used:
            snap.setdefault("sample", {})["used_row_ids"] = used[1:]
            snap["sample"]["used"] = len(snap["sample"]["used_row_ids"])
    elif cause == "incompatible_recommendation":
        snap["next_actions"] = [
            {
                "code": "issue_laudo",
                "title": "Emitir laudo automaticamente",
                "incompatible_with": ["pending_unit", "grade_not_met"],
            }
        ]
    snap.setdefault("provenance", {})["p04_mutation"] = cause
    return snap


def detect(original: Mapping[str, Any], mutated: Mapping[str, Any], *, expected_cause: str) -> Dict[str, Any]:
    """Return which cause is evidenced. Must match expected_cause to pass."""
    reasons: List[str] = []
    orig_val = original.get("value") or {}
    mut_val = mutated.get("value") or {}
    orig_ci = orig_val.get("mean_ci80")
    mut_ci = mut_val.get("mean_ci80")

    if orig_ci is not None and mut_ci is None:
        reasons.append("missing_ci")

    if isinstance(mut_ci, Mapping) and mut_ci.get("kind") == "percent_band":
        reasons.append("percent_band_replacing_uncertainty")
    elif isinstance(orig_ci, Mapping) and isinstance(mut_ci, Mapping):
        point = mut_val.get("point")
        if point is not None:
            p = float(point)
            lo, hi = mut_ci.get("lower"), mut_ci.get("upper")
            try:
                if abs(float(lo) - 0.9 * p) < 1e-9 and abs(float(hi) - 1.1 * p) < 1e-9:
                    reasons.append("percent_band_replacing_uncertainty")
            except (TypeError, ValueError):
                pass

    orig_coefs = (original.get("model") or {}).get("coefficients")
    mut_coefs = (mutated.get("model") or {}).get("coefficients")
    if orig_coefs is not None and mut_coefs is not None and orig_coefs != mut_coefs:
        reasons.append("wrong_coefficient_order")

    orig_method = ((original.get("validation") or {}).get("statistical") or {}).get("procedure") or {}
    mut_method = ((mutated.get("validation") or {}).get("statistical") or {}).get("procedure") or {}
    orig_eval = ((original.get("provenance") or {}).get("request_spec") or {}).get("evaluation_policy") or {}
    mut_eval = ((mutated.get("provenance") or {}).get("request_spec") or {}).get("evaluation_policy") or {}
    if (orig_method.get("method") == "holdout" or orig_eval.get("method") == "holdout") and (
        mut_method.get("method") == "none" or mut_eval.get("method") == "none"
    ):
        reasons.append("none_instead_of_holdout")

    if (original.get("target") or {}).get("unit") != (mutated.get("target") or {}).get("unit"):
        reasons.append("swapped_unit")

    orig_used = list((original.get("sample") or {}).get("used_row_ids") or [])
    mut_used = list((mutated.get("sample") or {}).get("used_row_ids") or [])
    if orig_used and mut_used and set(mut_used) < set(map(str, orig_used)) | set(orig_used):
        if len(mut_used) < len(orig_used):
            reasons.append("omitted_row")

    mut_actions = mutated.get("next_actions") or []
    if any(
        (a.get("code") == "issue_laudo") or ("laudo automaticamente" in str(a.get("title", "")).lower())
        for a in mut_actions
        if isinstance(a, Mapping)
    ):
        reasons.append("incompatible_recommendation")

    unique = []
    for r in reasons:
        if r not in unique:
            unique.append(r)
    matched = expected_cause in unique
    # Fail for the intended cause, not because another detector fired first.
    primary = unique[0] if unique else None
    return {
        "expected": expected_cause,
        "detected": unique,
        "primary": primary,
        "matched_expected": matched,
        "ok": matched and (primary == expected_cause or expected_cause in unique),
    }


def assert_cause(original: Mapping[str, Any], mutated: Mapping[str, Any], cause: str) -> None:
    result = detect(original, mutated, expected_cause=cause)
    if not result["matched_expected"]:
        raise AssertionError(
            f"mutation {cause!r} was not detected; detectors saw {result['detected']!r}"
        )
    if result["primary"] != cause:
        raise AssertionError(
            f"mutation {cause!r} failed for a different primary cause {result['primary']!r} "
            f"(all={result['detected']!r})"
        )
