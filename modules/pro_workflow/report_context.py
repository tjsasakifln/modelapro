"""Build the report context from the same inputs used by the valuation job.

The report renderer deliberately does not inspect Streamlit session state or
re-read an upload.  This module is the adapter between the persisted MP/1 job
inputs and C03's PDF/DOCX/dossier renderers.  Missing professional evidence is
left missing; the adapter never manufactures an inspection, source or review.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping as ABCMapping
from typing import Any, Dict, List, Mapping, Optional, Sequence


REPORT_CONTEXT_SCHEMA = "MP-REPORT-CONTEXT/1"
OUTPUT_MANIFEST_SCHEMA = "MP-OUTPUT-MANIFEST/1"
_DECIMAL_COORDINATE = re.compile(r"^[+-]?(?:\d+|\d+[.,]\d+|[.,]\d+)$")


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


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coordinate(value: Any, *, minimum: float, maximum: float) -> Optional[float]:
    candidate = value
    if isinstance(value, str):
        text = value.strip()
        if not _DECIMAL_COORDINATE.fullmatch(text):
            return None
        candidate = text.replace(",", ".")
    number = _finite(candidate)
    if number is None or number < minimum or number > maximum:
        return None
    # Keep the canonical origin compact and stable across persist/reopen
    # cycles.  Besides avoiding a UI-only textual drift (0 -> 0.0), this still
    # remains a JSON number and does not weaken the coordinate range check.
    return 0 if number == 0 else number


def _normalize_geolocation(value: Any, *, fallback: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Normalize a complete decimal-degree location without blessing bad input."""
    raw = _mapping(value)
    extra = _mapping(fallback)
    latitude_raw = _first(
        raw.get("latitude"), raw.get("lat"), extra.get("latitude"), extra.get("lat")
    )
    longitude_raw = _first(
        raw.get("longitude"), raw.get("lon"), raw.get("lng"),
        extra.get("longitude"), extra.get("lon"), extra.get("lng"),
    )
    latitude = _coordinate(latitude_raw, minimum=-90.0, maximum=90.0)
    longitude = _coordinate(longitude_raw, minimum=-180.0, maximum=180.0)
    address = _text(_first(
        raw.get("address"), raw.get("endereco"), raw.get("endereço"),
        extra.get("address"), extra.get("endereco"), extra.get("endereço"),
    ))
    source = _text(_first(
        raw.get("source"), raw.get("fonte"), raw.get("origem"),
        extra.get("source"), extra.get("fonte"), extra.get("origem"),
    ))
    if latitude is None and longitude is None and not address and not source:
        return {}
    issues: List[str] = []
    if latitude is None:
        issues.append("latitude_missing_or_out_of_range")
    if longitude is None:
        issues.append("longitude_missing_or_out_of_range")
    if not address:
        issues.append("complete_address_missing")
    if not source:
        issues.append("source_missing")
    return {
        "latitude": latitude,
        "longitude": longitude,
        "address": address,
        "source": source,
        "coordinate_system": "decimal_degrees_wgs84",
        "complete": not issues,
        "issues": issues,
    }


def _normalize_variable_classification(value: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    iterable = value.items() if isinstance(value, ABCMapping) else enumerate(value or [])
    for key, raw in iterable:
        if isinstance(raw, ABCMapping):
            item = dict(raw)
            variable = _text(item.get("variable") or item.get("name") or key)
            criterion = _text(item.get("criterion") or item.get("enquadramento"))
            coding = _text(item.get("coding") or item.get("codification") or item.get("codificacao"))
            categories = _json_value(item.get("categories") or item.get("categorias") or [])
            scale_values = _json_value(item.get("scale_values") or item.get("escala") or [])
        else:
            variable = _text(key)
            criterion = _text(raw)
            coding = None
            categories = []
            scale_values = []
        if variable:
            rows.append({
                "variable": variable,
                "criterion": criterion,
                "coding": coding,
                "categories": categories,
                "scale_values": scale_values,
                "complete": bool(criterion and (coding or categories or scale_values)),
            })
    return rows


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


def _row_source(row: Mapping[str, Any], *, input_sha256: Optional[str]) -> tuple[Optional[str], bool]:
    values = _mapping(row.get("values"))
    for key in ("fonte", "source", "origem", "url"):
        value = _first(row.get(key), values.get(key))
        if value is not None:
            return str(value), True
    row_id = row.get("row_id") or row.get("id")
    if input_sha256 and row_id is not None:
        return f"input-sha256:{input_sha256}#row={row_id}", False
    return None, False


def _normalize_rows(
    rows: Any,
    *,
    input_sha256: Optional[str],
    exclusions: Optional[Mapping[str, str]] = None,
    row_evidence: Optional[Mapping[str, Any]] = None,
    evidence_columns: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    reasons = dict(exclusions or {})
    evidence_by_id = dict(row_evidence or {})
    columns = {
        str(field): str(column)
        for field, column in dict(evidence_columns or {}).items()
        if field in {"address", "latitude", "longitude", "source", "justification"}
        and str(column).strip()
    }
    for raw in rows or []:
        if not isinstance(raw, ABCMapping):
            continue
        row = _json_value(raw)
        row_id = str(row.get("row_id") or row.get("id") or "")
        evidence = _mapping(evidence_by_id.get(row_id))
        values = _mapping(row.get("values"))
        for field, column in columns.items():
            if values.get(column) is not None:
                row[field] = _json_value(values[column])
        for key in (
            "address", "endereco", "endereço", "latitude", "longitude", "lat",
            "lon", "lng", "source", "fonte", "origem", "justification",
            "justificativa", "geolocation",
        ):
            if evidence.get(key) is not None:
                row[key] = _json_value(evidence[key])
        explicit_source = _first(
            evidence.get("source"), evidence.get("fonte"),
            evidence.get("origem"), evidence.get("url"),
        )
        if explicit_source is not None:
            source, documentary_source = str(explicit_source), True
        else:
            source, documentary_source = _row_source(row, input_sha256=input_sha256)
        if source:
            row["source"] = source
        row["source_is_documentary"] = documentary_source
        # Canonical top-level values were populated from the chosen columns and
        # then from the row-id override. They must precede a previously derived
        # nested geolocation when the professional corrects a reopened case.
        geolocation = _normalize_geolocation(row, fallback={
            **_mapping(row.get("values")),
            **_mapping(row.get("geolocation")),
        })
        if geolocation:
            row["geolocation"] = geolocation
            row["address"] = geolocation.get("address")
            row["latitude"] = geolocation.get("latitude")
            row["longitude"] = geolocation.get("longitude")
        if row_id in reasons and not row.get("justification"):
            row["justification"] = reasons[row_id]
        normalized.append(row)
    return normalized


def _merge_sample_evidence(*sources: Any) -> Dict[str, Dict[str, Any]]:
    """Overlay persisted and newly supplied evidence by canonical row id.

    Reopened projects already carry professional corrections in
    ``base_context.sample_evidence``.  A later request may update only one
    field of one row, so merging the outer mapping alone would either discard
    that persisted correction or discard its untouched fields.
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for source in sources:
        for row_id, raw in _mapping(source).items():
            if not isinstance(raw, ABCMapping):
                continue
            key = str(row_id)
            merged[key] = {**merged.get(key, {}), **dict(raw)}
    return merged


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
    subject_geolocation = _normalize_geolocation(
        subject.get("geolocation"), fallback=subject
    )
    if subject_geolocation:
        subject["geolocation"] = subject_geolocation

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
    sample_evidence = _merge_sample_evidence(
        base.get("sample_evidence"),
        supplied.get("sample_evidence"),
        spec.get("sample_evidence"),
    )
    sample_evidence_columns = {
        **_mapping(base.get("sample_evidence_columns")),
        **_mapping(supplied.get("sample_evidence_columns")),
        **_mapping(spec.get("sample_evidence_columns")),
    }
    resolved = dict(base)
    resolved.update(
        {
            "schema_version": REPORT_CONTEXT_SCHEMA,
            "applicant": _first(spec.get("applicant"), supplied.get("applicant"), base.get("applicant")),
            "purpose": _first(spec.get("purpose"), supplied.get("purpose"), base.get("purpose")),
            "objective": _first(
                spec.get("objective"), supplied.get("objective"), base.get("objective")
            ),
            "market_diagnosis": _first(
                spec.get("market_diagnosis"), supplied.get("market_diagnosis"),
                base.get("market_diagnosis")
            ),
            "variable_classification": _normalize_variable_classification(_first(
                spec.get("variable_classification"), supplied.get("variable_classification"),
                base.get("variable_classification"), []
            )),
            "grade_i_justification": _first(
                spec.get("grade_i_justification"), supplied.get("grade_i_justification"),
                base.get("grade_i_justification")
            ),
            "observations": _first(
                spec.get("observations"), supplied.get("observations"),
                base.get("observations")
            ),
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
            "synthetic_test_only": any(bool(value) for value in (
                spec.get("synthetic_test_only"), supplied.get("synthetic_test_only"),
                base.get("synthetic_test_only"),
            )),
        }
    )
    resolved["used_rows"] = _normalize_rows(
        base.get("used_rows"), input_sha256=input_sha,
        row_evidence=sample_evidence,
        evidence_columns=sample_evidence_columns,
    )
    resolved["excluded_rows"] = _normalize_rows(
        base.get("excluded_rows"), input_sha256=input_sha, exclusions=exclusions,
        row_evidence=sample_evidence,
        evidence_columns=sample_evidence_columns,
    )
    resolved["sample_evidence_columns"] = _json_value(sample_evidence_columns)
    resolved["sample_evidence"] = {
        str(row.get("row_id") or row.get("id")): {
            key: value
            for key, value in {
                "address": _mapping(row.get("geolocation")).get("address"),
                "latitude": _mapping(row.get("geolocation")).get("latitude"),
                "longitude": _mapping(row.get("geolocation")).get("longitude"),
                "source": (
                    _mapping(row.get("geolocation")).get("source")
                    if row.get("source_is_documentary") is True else None
                ),
                "justification": row.get("justification"),
            }.items()
            if value is not None
        }
        for row in (*resolved["used_rows"], *resolved["excluded_rows"])
        if row.get("row_id") is not None or row.get("id") is not None
    }

    # Technical source hashes are retained alongside (never in place of)
    # documentary/market citations explicitly supplied by the operator.
    raw_base_sources = base.get("sources")
    technical_sources = _mapping(raw_base_sources)
    human_sources = _first(spec.get("sources"), supplied.get("sources"))
    if human_sources:
        resolved["sources"] = human_sources
        resolved["technical_sources"] = technical_sources
    elif isinstance(raw_base_sources, (list, tuple)):
        resolved["sources"] = _json_value(raw_base_sources)
        resolved["technical_sources"] = {}
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
    # conformance evidence. Every item below is derived from snapshot/context
    # fields that a controlled renderer consumes.
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
        "assumptions": bool(ctx.get("assumptions")),
        "documents": bool(ctx.get("documents")),
        "annexes": bool(ctx.get("annexes")),
        "sources": bool(ctx.get("sources") or ctx.get("technical_sources")),
        "cost_memory": bool(_mapping(ctx.get("cost_memory"))),
    }

    def evidence(requirement_id: str, fragment: str, *, representation: str = "report.pdf") -> None:
        items[requirement_id] = (
            f"MP-OUTPUT-MANIFEST/1:representations.{representation}#{fragment}"
        )

    model = _mapping(snap.get("model"))
    metrics = _mapping(model.get("metrics"))
    statistical = _mapping(validation.get("statistical"))
    diagnostics = _mapping(statistical.get("diagnostics"))
    pvalues = _mapping(model.get("pvalues"))
    coefficients = _mapping(model.get("coefficients"))
    from ..report_presenter.formula import compose_model_equation
    from ..report_presenter.series import assess_chart_series

    equation = compose_model_equation(
        model, target_col=str(_mapping(snap.get("target")).get("column") or "")
    )
    series = assess_chart_series(ctx, used_row_ids=sample.get("used_row_ids") or [])
    standardized = _mapping(diagnostics.get("standardized_residuals"))
    normal_frequency = _mapping(diagnostics.get("normal_frequency_comparison"))
    correlation = _mapping(diagnostics.get("correlation_matrix"))
    elasticities = _mapping(diagnostics.get("elasticities"))
    outliers = _mapping(diagnostics.get("outlier_count"))
    fundamentacao = _mapping(validation.get("fundamentacao"))
    grade = fundamentacao.get("grade")
    item_scores = [item for item in fundamentacao.get("items") or [] if isinstance(item, ABCMapping)]
    used_rows = [row for row in ctx.get("used_rows") or [] if isinstance(row, ABCMapping)]
    excluded_rows = [
        row for row in ctx.get("excluded_rows") or [] if isinstance(row, ABCMapping)
    ]
    subject = _mapping(ctx.get("subject"))
    subject_geo = _mapping(subject.get("geolocation"))
    classifications = [
        item for item in ctx.get("variable_classification") or []
        if isinstance(item, ABCMapping)
    ]
    professional = _mapping(ctx.get("professional_identity"))
    xlsx = _mapping(files.get("sample.xlsx"))
    signed_pdf = _mapping(files.get("signed_report.pdf"))

    # Derived condition markers are not requirements and never originate in
    # caller labels. They drive conditional clauses in the catalog.
    if grade == 1:
        items["grade_i_attained"] = "snapshot.validation.fundamentacao.grade=1"
    if grade == 3:
        items["grade_iii_attained"] = "snapshot.validation.fundamentacao.grade=3"

    if ctx.get("applicant"):
        evidence("10.1.a", "identificacao-solicitante")
    if ctx.get("purpose"):
        evidence("10.1.b", "finalidade")
    if ctx.get("objective"):
        evidence("10.1.c", "objetivo-avaliacao")
    if ctx.get("assumptions"):
        evidence("10.1.d", "pressupostos-ressalvas-limitacoes")
    if subject and ctx.get("asset_identification"):
        evidence("10.1.e", "imovel-avaliando")
        evidence("meci.3.3.1.e", "imovel-avaliando")
    if ctx.get("market_diagnosis"):
        evidence("10.1.f", "diagnostico-mercado")
    if ctx.get("methodology_justification"):
        evidence("10.1.g", "metodo-procedimento")
        evidence("meci.3.2.2.mcddm", "metodo-procedimento")
    if fundamentacao and _mapping(validation.get("precisao")):
        evidence("10.1.h", "especificacao-avaliacao")
        evidence("meci.3.4.1.grau_ii", "especificacao-avaliacao")
    if used_rows and len(used_rows) == len(sample.get("used_row_ids") or []):
        evidence("10.1.i", "amostra-integral")
    if classifications and all(item.get("complete") is True for item in classifications):
        evidence("10.1.j", "criterios-enquadramento-escalas")
    adopted = value.get("adopted_value", value.get("adopted"))
    adopted_reason = (
        (adopted.get("reason") or adopted.get("policy_ref"))
        if isinstance(adopted, ABCMapping)
        else value.get("adoption_policy_ref")
    )
    if value.get("point") is not None and value.get("arbitration_interval") and adopted_reason and series.get("plot"):
        evidence("10.1.k", "tratamento-identificacao-resultado")
    if value.get("point") is not None and snap.get("reference_date"):
        evidence("10.1.l", "resultado-data-referencia")
    if all(professional.get(key) for key in ("name", "council", "registration")) and (
        professional.get("art_rrt") or professional.get("responsibility_document")
    ):
        evidence("10.1.m", "responsabilidade-tecnica")

    if equation.get("original_scale_present") and equation.get("retransformation_method"):
        evidence("meci.3.3.1.a", "equacao-unidade-original")
    if all(_finite(metrics.get(key)) is not None for key in ("r", "r2", "r2_adjusted")):
        evidence("meci.3.3.1.b", "coeficientes-ajustamento")
    non_intercepts = [name for name in coefficients if str(name).lower() not in {"const", "intercept", "intercepto"}]
    if _finite(metrics.get("f_pvalue")) is not None and non_intercepts and all(
        _finite(pvalues.get(name)) is not None for name in non_intercepts
    ):
        evidence("meci.3.3.1.c", "significancias-modelo-variaveis")
    if sample.get("used") is not None or sample.get("used_row_ids"):
        evidence("meci.3.3.1.d", "numero-dados-utilizados")
    if value.get("point") is not None and value.get("mean_ci80") and value.get("arbitration_interval"):
        evidence("meci.3.3.1.f", "resultado-intervalos")
    if series.get("plot"):
        evidence("meci.3.3.1.g", "grafico-residuos")
        evidence("meci.3.3.1.h", "grafico-observado-estimado")
        evidence("normas.12.1.15.graficos", "graficos-estatisticos")
    if item_scores and all(item.get("points") is not None for item in item_scores):
        evidence("meci.3.3.1.i", "demonstrativo-pontuacao")
        evidence("normas.12.1.16.tabela_anexa", "anexo-demonstrativo-pontuacao")
    if standardized.get("available") is True and not standardized.get("reason") and standardized.get("values") and len(standardized.get("values")) == len(sample.get("used_row_ids") or []):
        evidence("meci.3.3.1.j", "histograma-residuos-padronizados")
    intervals = [item for item in normal_frequency.get("intervals") or [] if isinstance(item, ABCMapping)]
    if normal_frequency.get("available") is True and not normal_frequency.get("reason") and {round(float(item.get("z")), 2) for item in intervals if _finite(item.get("z")) is not None} >= {1.0, 1.64, 1.96}:
        evidence("meci.3.3.1.k", "cotejo-normal-68-90-95")
    matrix_values = correlation.get("values") or []
    matrix_variables = correlation.get("variables") or []
    correlation_complete = (
        correlation.get("status") == "complete"
        and correlation.get("missing_cells") in (None, 0, [])
        and not correlation.get("missing_variables")
    )
    if correlation.get("available") is True and not correlation.get("reason") and correlation_complete and matrix_variables and len(matrix_values) == len(matrix_variables) and all(
        isinstance(row, (list, tuple)) and len(row) == len(matrix_variables) for row in matrix_values
    ):
        evidence("meci.3.3.1.l", "matriz-correlacoes")
    if _finite(metrics.get("f_statistic")) is not None:
        evidence("meci.3.3.1.m1", "f-snedecor-calculado")
    if outliers.get("available") is True and not outliers.get("reason") and _mapping(outliers.get("coverage")).get("complete") is True and all(outliers.get(key) is not None for key in ("detected", "excluded", "influential")):
        evidence("meci.3.3.1.m2", "contagem-outliers")
    if value.get("admissible_interval") and ctx.get("observations"):
        evidence("meci.3.3.1.n", "observacoes-intervalo-admissivel")
    if value.get("point") is not None and value.get("mean_ci80") and value.get("prediction_interval"):
        evidence("meci.2.3.3.2.projecoes", "projecoes-informacoes-auxiliares")
    if equation.get("present") and coefficients:
        evidence("meci.2.3.3.2.pdf", "relatorio-inferencia-completo")
        evidence("meci.3.1.7.2.anexo", "memoria-calculo-anexa")
    if xlsx.get("verified") is True and xlsx.get("sha256") and xlsx.get("size"):
        evidence("meci.2.3.3.2.excel", "amostra-efetiva", representation="sample.xlsx")
    if grade != 1 or ctx.get("grade_i_justification"):
        if grade == 1:
            evidence("meci.3.4.1.justificativa_grau_i", "justificativa-grau-i")
    if (
        elasticities.get("available") is True and not elasticities.get("reason")
        and elasticities.get("items") and elasticities.get("method")
        and _mapping(elasticities.get("coverage")).get("complete") is True
        and not _mapping(elasticities.get("coverage")).get("missing_variables")
    ):
        # The section can be represented for every fitted case.  The profile's
        # applies_when rule still decides whether grade III makes it mandatory.
        evidence("abnt.9.2.1.1.elasticidades", "elasticidades-ponto-estimacao")
    row_geolocation_complete = bool(used_rows) and all(
        _mapping(row.get("geolocation")).get("complete") is True
        and row.get("source_is_documentary") is True
        for row in used_rows + excluded_rows
    )
    if subject_geo.get("complete") is True and row_geolocation_complete and xlsx.get("verified") is True:
        evidence("normas.12.1.8.geolocalizacao", "geolocalizacao-integral", representation="sample.xlsx")
    if (
        signed_pdf.get("verified") is True
        and signed_pdf.get("trust_policy") == "icp_brasil"
        and signed_pdf.get("icp_brasil_verified") is True
    ):
        evidence("bb.guiar.assinatura_icp", "assinatura-cadeia-validada", representation="signed_report.pdf")
    return {
        "schema_version": OUTPUT_MANIFEST_SCHEMA,
        "items": items,
        "unverified_declarations": declared_output_evidence,
        "content": content,
        "representations": files,
    }
