"""Build the report context from the same inputs used by the valuation job.

The report renderer deliberately does not inspect Streamlit session state or
re-read an upload.  This module is the adapter between the persisted MP/1 job
inputs and C03's PDF/DOCX/dossier renderers.  Missing professional evidence is
left missing; the adapter never manufactures an inspection, source or review.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping as ABCMapping
from typing import Any, Dict, List, Mapping, Optional, Sequence


REPORT_CONTEXT_SCHEMA = "MP-REPORT-CONTEXT/1"
OUTPUT_MANIFEST_SCHEMA = "MP-OUTPUT-MANIFEST/1"


def _finite(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def formula_from_coefficients(
    coefficients: Mapping[str, Any],
    feature_order: Optional[Sequence[str]] = None,
    *,
    target_name: str = "y",
    intercept_column: Optional[str] = "const",
) -> Optional[str]:
    """Display formula from stored coefficients. Not a substitute for integral coefficients."""
    if not isinstance(coefficients, Mapping) or not coefficients:
        return None
    order = [str(x) for x in (feature_order or list(coefficients.keys()))]
    if not order:
        order = [str(k) for k in coefficients.keys()]
    intercept_names = {intercept_column or "const", "const", "Intercept"}
    intercept_term = None
    terms: List[str] = []
    for name in order:
        value = _finite(coefficients.get(name))
        if value is None:
            continue
        if name in intercept_names:
            intercept_term = format(value, ".17g")
            continue
        sign = "+" if value >= 0 else "-"
        terms.append(f"{sign} {format(abs(value), '.17g')}*{name}")
    if intercept_term is None and not terms:
        return None
    body = intercept_term if intercept_term is not None else "0"
    if terms:
        body = body + " " + " ".join(terms)
    return f"{target_name} = {body}"


def aligned_fit_series(
    winner_fit: Any,
    *,
    used_row_ids: Sequence[str],
    target_unit: Optional[str] = None,
    y_transform_name: Optional[str] = None,
) -> Dict[str, Any]:
    """fitted/residual/observed series aligned to used_row_ids only.

    Residuals stay on the modeled scale. Log residuals are never labeled as
    monetary prices. Missing design yields an unavailable series, not invented
    values.
    """
    used = [str(x) for x in list(used_row_ids or [])]
    identity = y_transform_name in {None, "", "identity", "linear", "none"}
    scale = "original" if identity else "transformed"
    unit = target_unit if identity else f"transformed({y_transform_name or 'y'})"
    unavailable = {
        "fitted_values": None,
        "residuals": None,
        "observed_values": None,
        "series_row_ids": list(used),
        "series_scale": scale,
        "series_unit": unit,
        "available": False,
        "reason": "fit_design_unavailable",
    }

    x_design = getattr(winner_fit, "X_design", None)
    if x_design is None and isinstance(winner_fit, Mapping):
        x_design = winner_fit.get("X_design")
    y_design = getattr(winner_fit, "y_design", None)
    if y_design is None and isinstance(winner_fit, Mapping):
        y_design = winner_fit.get("y_design")
    model = getattr(winner_fit, "model_object", None)
    if model is None and isinstance(winner_fit, Mapping):
        model = winner_fit.get("model_object")

    fitted = None
    observed = None
    if model is not None:
        fitted = getattr(model, "fittedvalues", None)
        observed = getattr(model, "model", None)
        if observed is not None:
            observed = getattr(observed, "endog", None)
    if observed is None:
        observed = y_design
    if fitted is None and x_design is not None:
        coefficients = None
        if isinstance(winner_fit, Mapping):
            coefficients = winner_fit.get("coefficients")
        else:
            coefficients = getattr(winner_fit, "coefficients", None)
        if isinstance(coefficients, Mapping) and hasattr(x_design, "columns"):
            try:
                import numpy as np

                order = [str(c) for c in x_design.columns]
                beta = np.array([float(coefficients.get(name, 0.0)) for name in order], dtype=float)
                X = np.asarray(x_design.to_numpy(), dtype=float)
                if X.shape[1] == beta.shape[0] and np.isfinite(X).all() and np.isfinite(beta).all():
                    fitted = X @ beta
            except Exception:
                fitted = None

    if fitted is None or observed is None:
        return unavailable

    try:
        import numpy as np

        fit_arr = np.asarray(fitted, dtype=float).reshape(-1)
        obs_arr = np.asarray(observed, dtype=float).reshape(-1)
    except Exception:
        return unavailable
    if fit_arr.size != obs_arr.size or fit_arr.size == 0:
        return unavailable
    if used and fit_arr.size != len(used):
        # Do not silently align to a different sample; series must be used_row_ids.
        return {
            **unavailable,
            "reason": "series_length_mismatch_used_row_ids",
        }
    if not bool(__import__("numpy").isfinite(fit_arr).all()) or not bool(
        __import__("numpy").isfinite(obs_arr).all()
    ):
        return {**unavailable, "reason": "non_finite_series"}
    resid = obs_arr - fit_arr
    return {
        "fitted_values": [float(v) for v in fit_arr.tolist()],
        "residuals": [float(v) for v in resid.tolist()],
        "observed_values": [float(v) for v in obs_arr.tolist()],
        "series_row_ids": list(used) if used else [str(i) for i in range(fit_arr.size)],
        "series_scale": scale,
        "series_unit": unit or ("original" if identity else scale),
        "available": True,
        "reason": None,
    }


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, ABCMapping) else {}


def _first(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple, dict)) and not value:
            continue
        return value
    return None


def _json_value(value: Any) -> Any:
    """Return a strict-JSON value; attachment bytes become digest metadata."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        payload = bytes(value)
        return {"sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
    if isinstance(value, ABCMapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_value(value.item())
        except (TypeError, ValueError):
            pass
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return str(value)


def _row_source(row: Mapping[str, Any], *, input_sha256: Optional[str]) -> Optional[str]:
    values = _mapping(row.get("values"))
    for key in ("fonte", "source", "origem", "url", "endereco", "endereço"):
        value = _first(row.get(key), values.get(key))
        if value is not None:
            return str(value)
    row_id = row.get("row_id") or row.get("id")
    if input_sha256 and row_id is not None:
        return f"input-sha256:{input_sha256}#row={row_id}"
    return None


def _normalize_rows(
    rows: Any,
    *,
    input_sha256: Optional[str],
    exclusions: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    reasons = dict(exclusions or {})
    for raw in rows or []:
        if not isinstance(raw, ABCMapping):
            continue
        row = _json_value(raw)
        row_id = str(row.get("row_id") or row.get("id") or "")
        source = _row_source(row, input_sha256=input_sha256)
        if source:
            row["source"] = source
        if row_id in reasons and not row.get("justification"):
            row["justification"] = reasons[row_id]
        normalized.append(row)
    return normalized


def complete_report_context(
    base_context: Optional[Mapping[str, Any]],
    *,
    request_spec: Mapping[str, Any],
    subject_raw: Optional[Mapping[str, Any]] = None,
    snapshot: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Enrich the worker's row/series context with actual professional inputs.

    C02 may place report fields either directly in RequestSpec or under
    ``report_context``.  Direct fields win for backwards compatibility.  The
    result is JSON-safe so the worker can persist it as ``report_context.json``.
    Raw attachment bytes are never copied into that JSON; their exact hashes
    and sizes remain available and bytes stay in the evidence/artifact store.
    """
    spec = _mapping(request_spec)
    supplied = _mapping(spec.get("report_context"))
    base = _mapping(base_context)
    snap = _mapping(snapshot)
    provenance = _mapping(snap.get("provenance"))
    workflow = _mapping(provenance.get("workflow_context"))
    inspection = _mapping(_first(spec.get("inspection"), supplied.get("inspection")))
    professional = _mapping(
        _first(spec.get("professional_identity"), supplied.get("professional_identity"))
    )
    subject = _mapping(
        _first(subject_raw, supplied.get("subject"), workflow.get("subject_raw"))
    )

    exclusions: Dict[str, str] = {}
    for item in spec.get("justified_exclusions") or []:
        if not isinstance(item, ABCMapping):
            continue
        row_id = item.get("row_id") or item.get("id")
        reason = item.get("justification") or item.get("reason")
        if row_id is not None and reason:
            exclusions[str(row_id)] = str(reason)

    input_sha = str(
        snap.get("input_sha256") or _mapping(base.get("sources")).get("input_sha256") or ""
    ) or None
    resolved = dict(base)
    resolved.update(
        {
            "schema_version": REPORT_CONTEXT_SCHEMA,
            "applicant": _first(spec.get("applicant"), supplied.get("applicant"), base.get("applicant")),
            "purpose": _first(spec.get("purpose"), supplied.get("purpose"), base.get("purpose")),
            "rights": _first(spec.get("rights"), supplied.get("rights"), base.get("rights")),
            "inspection_date": _first(
                spec.get("inspection_date"), inspection.get("date"), supplied.get("inspection_date"),
                base.get("inspection_date")
            ),
            "subject": subject,
            "asset_identification": _first(
                spec.get("asset_identification"),
                supplied.get("asset_identification"),
                subject,
                base.get("asset_identification"),
            ),
            "region_characterization": _first(
                spec.get("region_characterization"), supplied.get("region_characterization"),
                base.get("region_characterization")
            ),
            "property_characterization": _first(
                spec.get("property_characterization"),
                supplied.get("property_characterization"),
                inspection.get("verified_characteristics"),
                base.get("property_characterization"),
            ),
            "methodology_justification": _first(
                spec.get("methodology_justification"),
                supplied.get("methodology_justification"),
                _mapping(spec.get("qualification_profile")).get("method"),
                base.get("methodology_justification"),
            ),
            "assumptions": _first(
                spec.get("assumptions"),
                supplied.get("assumptions"),
                [inspection.get("special_assumptions")]
                if inspection.get("special_assumptions")
                else None,
                base.get("assumptions"),
            ),
            "documents": _first(spec.get("documents"), supplied.get("documents"), base.get("documents")),
            "documentary_files": _first(
                spec.get("documentary_files"), supplied.get("documentary_files"),
                base.get("documentary_files")
            ),
            "annexes": _first(spec.get("annexes"), supplied.get("annexes"), base.get("annexes")),
            "professional_identity": professional or base.get("professional_identity") or None,
            "synthetic_test_only": bool(_first(
                spec.get("synthetic_test_only"), supplied.get("synthetic_test_only"),
                base.get("synthetic_test_only"), False
            )),
        }
    )
    resolved["used_rows"] = _normalize_rows(
        base.get("used_rows"), input_sha256=input_sha
    )
    resolved["excluded_rows"] = _normalize_rows(
        base.get("excluded_rows"), input_sha256=input_sha, exclusions=exclusions
    )

    # Technical source hashes are retained alongside (never in place of)
    # documentary/market citations explicitly supplied by the operator.
    technical_sources = _mapping(base.get("sources"))
    human_sources = _first(spec.get("sources"), supplied.get("sources"))
    if human_sources:
        resolved["sources"] = human_sources
        resolved["technical_sources"] = technical_sources
    else:
        resolved["sources"] = technical_sources
    return _json_value(resolved)


def build_output_manifest(
    snapshot: Mapping[str, Any],
    report_context: Mapping[str, Any],
    *,
    representations: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Describe content and files actually available before qualification.

    The generic inventory is derived from populated report fields and byte
    metadata. Caller-supplied ``output_evidence`` is retained as an unverified
    declaration and cannot turn an absent representation into conformance.
    """
    snap = _mapping(snapshot)
    ctx = _mapping(report_context)
    validation = _mapping(snap.get("validation"))
    value = _mapping(snap.get("value"))
    sample = _mapping(snap.get("sample"))
    files = {str(name): _json_value(meta) for name, meta in (representations or {}).items()}
    # Caller declarations are retained for audit but never promoted to
    # conformance evidence. Requirement IDs enter ``items`` only when a C03
    # verifier can bind them to an emitted representation; no such generic
    # verifier exists, so arbitrary strings/``True`` values must remain empty.
    declared_output_evidence = _json_value(_mapping(ctx.get("output_evidence")))
    items: Dict[str, Any] = {}
    content = {
        "applicant": bool(_first(ctx.get("applicant"), snap.get("applicant"))),
        "asset_identification": bool(
            _first(ctx.get("asset_identification"), ctx.get("subject"))
        ),
        "rights": bool(ctx.get("rights")),
        "reference_date": bool(snap.get("reference_date")),
        "inspection_date": bool(_first(snap.get("inspection_date"), ctx.get("inspection_date"))),
        "value_point": value.get("point") is not None,
        "mean_ci80": bool(value.get("mean_ci80")),
        "prediction_interval": bool(value.get("prediction_interval")),
        "fundamentacao": bool(_mapping(validation.get("fundamentacao"))),
        "precisao": bool(_mapping(validation.get("precisao"))),
        "used_sample": bool(sample.get("used_row_ids")) and bool(ctx.get("used_rows")),
        "excluded_sample": len(sample.get("excluded_row_ids") or [])
        == len(ctx.get("excluded_rows") or []),
        "region_characterization": bool(ctx.get("region_characterization")),
        "property_characterization": bool(ctx.get("property_characterization")),
        "methodology_justification": bool(ctx.get("methodology_justification")),
        "assumptions": ctx.get("assumptions") is not None,
        "documents": bool(ctx.get("documents")),
        "annexes": bool(ctx.get("annexes")),
    }
    return {
        "schema_version": OUTPUT_MANIFEST_SCHEMA,
        "items": items,
        "unverified_declarations": declared_output_evidence,
        "content": content,
        "representations": files,
    }
