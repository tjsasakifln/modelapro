"""P02 workflow helpers: binding, invalidation, grade/method, batch, alternatives.

Pure functions, testable without Streamlit. Do not parse files, do not
recompute producer classifications, do not invent endpoints.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional, Sequence

SCHEMA_VERSION = "MP/1"

GRADE_ALIASES = ("min_fundamentacao_grade", "target_degree", "minimum_grade")
CANONICAL_GRADE_KEY = "minimum_fundamentacao_grade"

# Methods the BASE_SHA API/C07 actually honor. "none" skips independent
# validation. holdout is an alias of random on the producer side.
SUPPORTED_EVALUATION_METHODS = (
    ("none", "Não executar validação independente"),
    ("holdout", "Holdout aleatório"),
    ("group", "Partição por grupo"),
    ("temporal", "Partição temporal"),
    ("kfold", "K-fold"),
)
SUPPORTED_EVALUATION_METHOD_IDS = tuple(item[0] for item in SUPPORTED_EVALUATION_METHODS)

GRADE_REQUIREMENT_STATUSES = (
    "not_requested",
    "met",
    "not_met",
    "pending",
    "error",
)

GRADE_REQUIREMENT_LABELS = {
    "not_requested": "Grau mínimo não solicitado",
    "met": "Grau mínimo atingido",
    "not_met": "Grau mínimo não atingido",
    "pending": "Grau mínimo ainda pendente",
    "error": "Erro ao verificar o grau mínimo",
}

DEPENDENTS_BY_CHANGE = {
    "file": ("preview", "mapping", "subject", "result", "review", "issuance"),
    "import_options": ("preview", "mapping", "subject", "result", "review", "issuance"),
    "subject": ("result", "review", "issuance"),
    "policy": ("result", "review", "issuance"),
    "unit": ("result", "review", "issuance"),
    "dates": ("result", "review", "issuance"),
    "target": ("subject", "result", "review", "issuance"),
    "profile": ("result", "review", "issuance"),
    "sample": ("preview", "mapping", "result", "review", "issuance"),
    "document": ("review", "issuance"),
    "inspection": ("result", "review", "issuance"),
}

BATCH_UI_VALIDO = "valido"
BATCH_UI_NAO_SUPORTADO = "nao_suportado"
BATCH_UI_PENDENTE = "pendente"

NAV_FALLBACK_WHEN_ABSENT = {
    "target_unit": "Informe a unidade do valor na preparação da amostra.",
    "reference_date": "Informe a data-base na preparação da amostra.",
    "subject": "Informe as características do imóvel avaliando.",
    "preview": "Envie o arquivo e revise a interpretação antes de calcular.",
    "result": "Ainda não há resultado para este trabalho.",
}


def mapping_binding_token(
    *,
    filename: Optional[str] = None,
    nbytes: Optional[int] = None,
    import_options: Optional[Mapping[str, Any]] = None,
    input_sha256: Optional[str] = None,
    schema_fingerprint: Optional[str] = None,
) -> str:
    """Bind mapping/session keys to this file and its interpreted schema.

    A different file must not reuse the previous imóvel's widget values.
    """
    options = import_options or {}
    parts = [
        str(filename or ""),
        str(nbytes if nbytes is not None else ""),
        str(options.get("locale") or ""),
        str(options.get("delimiter") or ""),
        str(options.get("encoding") or ""),
        str(input_sha256 or ""),
        str(schema_fingerprint or ""),
    ]
    return "|".join(parts)


def schema_fingerprint(preview: Optional[Mapping[str, Any]]) -> str:
    if not preview:
        return ""
    column_map = preview.get("column_map") or {}
    if isinstance(column_map, Mapping) and isinstance(column_map.get("entries"), list):
        names = [
            str((entry or {}).get("internal") or (entry or {}).get("original") or "")
            for entry in column_map.get("entries") or []
            if isinstance(entry, Mapping)
        ]
    elif isinstance(column_map, Mapping):
        names = [str(k) for k in column_map.keys() if k != "entries"]
    else:
        names = []
    payload = {
        "input_sha256": preview.get("input_sha256"),
        "columns": names,
        "schema_version": preview.get("schema_version"),
    }
    dumped = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()[:16]


def widget_namespace(binding_token: str) -> str:
    digest = hashlib.sha256((binding_token or "").encode("utf-8")).hexdigest()
    return digest[:12]


def normalize_minimum_grade(value: Any) -> Optional[int]:
    if value is None or value == "" or value == "not_requested":
        return None
    if isinstance(value, bool):
        raise ValueError("grau mínimo não pode ser booleano")
    number = int(value)
    if number not in (1, 2, 3):
        raise ValueError("grau mínimo deve ser nulo ou inteiro 1..3")
    return number


def canonical_search_policy(
    minimum_grade: Optional[int] = None,
    *,
    base: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Emit only search_policy.minimum_fundamentacao_grade as the grade key."""
    policy = {
        "mode": "default",
        "budget": None,
        "objective": "minimum_fundamentacao_grade",
        "seed": None,
    }
    if base:
        for key in ("mode", "budget", "objective", "seed"):
            if key in base:
                policy[key] = base[key]
        if not policy.get("mode"):
            policy["mode"] = "default"
    for alias in GRADE_ALIASES:
        policy.pop(alias, None)
    if isinstance(base, Mapping):
        for alias in GRADE_ALIASES:
            if alias in base and CANONICAL_GRADE_KEY in base:
                if base.get(alias) != base.get(CANONICAL_GRADE_KEY):
                    raise ValueError(
                        "aliases de grau mínimo conflitantes; a interface emite só a chave canônica"
                    )
    policy[CANONICAL_GRADE_KEY] = minimum_grade
    return policy


def canonical_evaluation_policy(
    *,
    method: str = "none",
    partitions: Any = None,
    groups: Any = None,
    seed: Any = None,
    documentary: Optional[Mapping[str, Any]] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict:
    chosen = str(method or "none")
    if chosen not in SUPPORTED_EVALUATION_METHOD_IDS:
        raise ValueError(
            f"método de avaliação independente não suportado pela API: {chosen!r}"
        )
    policy = {
        "method": chosen,
        "partitions": partitions,
        "groups": groups,
        "seed": seed,
    }
    if extra:
        for key, value in extra.items():
            if key in GRADE_ALIASES or key == CANONICAL_GRADE_KEY:
                continue
            policy.setdefault(key, value)
    if documentary is not None:
        policy["documentary"] = dict(documentary)
    return policy


def request_grade_keys(spec: Optional[Mapping[str, Any]]) -> dict:
    """Inspect a request body for grade keys. P02 bodies must be canonical-only."""
    spec = spec or {}
    search = dict(spec.get("search_policy") or {})
    evaluation = dict(spec.get("evaluation_policy") or {})
    aliases_present = [
        key for key in GRADE_ALIASES
        if key in search or key in evaluation or key in spec
    ]
    return {
        "canonical": search.get(CANONICAL_GRADE_KEY),
        "canonical_in_search": CANONICAL_GRADE_KEY in search,
        "canonical_in_evaluation": CANONICAL_GRADE_KEY in evaluation,
        "aliases_present": aliases_present,
        "canonical_only": CANONICAL_GRADE_KEY in search and not aliases_present and CANONICAL_GRADE_KEY not in evaluation,
    }


def execution_fingerprint(
    *,
    input_sha256: Optional[str] = None,
    filename: Optional[str] = None,
    nbytes: Optional[int] = None,
    request_spec: Optional[Mapping[str, Any]] = None,
    subject: Optional[Mapping[str, Any]] = None,
) -> str:
    subject_payload = subject
    if isinstance(subject, Mapping) and isinstance(subject.get("raw_values"), Mapping):
        subject_payload = subject.get("raw_values")
    material = {
        "input_sha256": input_sha256,
        "filename": filename,
        "nbytes": nbytes,
        "request_spec": request_spec or {},
        "subject": subject_payload,
    }
    dumped = json.dumps(material, ensure_ascii=False, sort_keys=True, default=str, allow_nan=False)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def should_block_duplicate_submit(
    *,
    current_fingerprint: Optional[str],
    last_fingerprint: Optional[str],
    job_status: Optional[Mapping[str, Any]] = None,
    last_job_id: Optional[str] = None,
) -> bool:
    """Block Streamlit rerun / double-click from POSTing equivalent work."""
    if not current_fingerprint:
        return False
    if current_fingerprint != last_fingerprint:
        return False
    state = (job_status or {}).get("state")
    if state in {"queued", "running"}:
        return True
    if last_job_id or (job_status or {}).get("job_id"):
        return True
    return False


def dependents_invalidated_by(change: str) -> tuple:
    return DEPENDENTS_BY_CHANGE.get(change, ())


def apply_invalidation(session: Mapping[str, Any], change: str) -> dict:
    """Return a copy of session keys with dependents dropped. Does not mutate."""
    out = dict(session)
    dropped = dependents_invalidated_by(change)
    if "preview" in dropped:
        out.pop("c09_preview", None)
        out.pop("c09_preview_token", None)
        out.pop("p02_preview", None)
        out.pop("p02_preview_token", None)
        out.pop("p02_form_model", None)
    if "mapping" in dropped:
        out.pop("p02_mapping", None)
        out.pop("p02_roles", None)
        out.pop("p02_units", None)
    if "subject" in dropped:
        out.pop("p02_subject", None)
        out.pop("p02_raw_values", None)
    if "result" in dropped:
        previous = out.get("c09_snapshot") or out.get("p02_snapshot")
        if previous is not None:
            out["p02_previous_snapshot"] = previous
            out["p02_result_stale"] = True
            out["p02_result_stale_reason"] = _stale_reason(change)
        out["p02_current_result_belongs_to"] = "previous_version"
    if "review" in dropped or "issuance" in dropped:
        previous_events = out.get("c02_review_events")
        if previous_events is not None:
            out["c02_review_events_history"] = list(previous_events)
        out["c02_review_stale"] = True
        out["c02_signature_stale"] = True
        out["c02_issuance_stale"] = True
        out["c02_consent_reusable"] = False
        out["c02_invalidation_reason"] = _stale_reason(change)
        # History is kept; live events must be rebound to the new fingerprint.
    return out


def _stale_reason(change: str) -> str:
    labels = {
        "file": "O arquivo mudou. O resultado abaixo pertence à versão anterior.",
        "import_options": "A leitura da planilha mudou. O resultado abaixo pertence à versão anterior.",
        "subject": "Os dados do imóvel avaliando mudaram. O resultado abaixo pertence à versão anterior.",
        "policy": "A política enviada mudou. O resultado abaixo pertence à versão anterior.",
        "unit": "A unidade mudou. O resultado abaixo pertence à versão anterior.",
        "dates": "A data-base ou a vistoria mudaram. O resultado abaixo pertence à versão anterior.",
        "target": "O alvo mudou. O resultado abaixo pertence à versão anterior.",
        "profile": "O perfil de qualificação mudou. Emissão e revisão anteriores ficam no histórico e não autorizam a versão atual.",
        "sample": "A amostra mudou. O resultado e a emissão abaixo pertencem à versão anterior.",
        "document": "Um documento ou evidência mudou. A revisão/assinatura anterior não pode ser reutilizada.",
        "inspection": "A vistoria mudou. O resultado abaixo pertence à versão anterior.",
    }
    return labels.get(change, "Há um resultado de uma versão anterior deste trabalho.")


def preview_failure_clears_interpretation(session: Mapping[str, Any]) -> dict:
    """A failed preview must not keep the previous interpretation."""
    out = dict(session)
    out.pop("c09_preview", None)
    out.pop("p02_preview", None)
    out.pop("p02_form_model", None)
    out["p02_preview_error_cleared"] = True
    return out


def unused_columns_view(
    column_map: Optional[Mapping[str, Any]],
    *,
    roles: Optional[Mapping[str, str]] = None,
    candidate_cols: Optional[Sequence[str]] = None,
    target_col: Optional[str] = None,
    preview_issues: Optional[Sequence[Mapping[str, Any]]] = None,
) -> list:
    """Columns visible in the preview that will not enter the model, with reason.

    Never silently omit a candidate; reasons are explicit.
    """
    roles = dict(roles or {})
    authorized = None if candidate_cols is None else set(candidate_cols)
    unused: list = []
    for name, meta in (column_map or {}).items():
        if name == "entries":
            continue
        meta = meta or {}
        role = roles.get(name) or meta.get("role") or meta.get("role_suggestion")
        original = meta.get("original_name") or name
        if name == target_col or role == "target":
            continue
        reason = None
        if role in {"identifier", "excluded", "source", "date"}:
            reason = f"papel «{role}» — não entra no modelo"
        elif authorized is not None and name not in authorized:
            reason = "não autorizada pelo avaliador nesta preparação"
        if reason:
            unused.append({
                "name": name,
                "original_name": original,
                "role": role,
                "reason": reason,
                "kind": meta.get("kind"),
            })
    for issue in preview_issues or []:
        if not isinstance(issue, Mapping):
            continue
        for affected in issue.get("affected_ids") or []:
            if any(item["name"] == affected or item.get("original_name") == affected for item in unused):
                continue
            unused.append({
                "name": affected,
                "original_name": affected,
                "role": None,
                "reason": issue.get("message") or issue.get("code") or "indicada na prévia",
                "kind": None,
                "from_issue": issue.get("code"),
            })
    return unused


def interpreted_sample_rows(preview: Optional[Mapping[str, Any]], *, limit: int = 8) -> list:
    if not preview:
        return []
    rows = preview.get("sample_preview") or []
    if isinstance(rows, list):
        return list(rows[:limit])
    return []


def policies_on_the_wire(request_spec: Optional[Mapping[str, Any]]) -> dict:
    """Only policies that actually go in the request. Decorative controls do not count."""
    spec = request_spec or {}
    search = dict(spec.get("search_policy") or {})
    evaluation = dict(spec.get("evaluation_policy") or {})
    return {
        "search_policy": search,
        "evaluation_policy": evaluation,
        "missing_policy": dict(spec.get("missing_policy") or {}),
        "outlier_policy": dict(spec.get("outlier_policy") or {}),
        "import_options": dict(spec.get("import_options") or {}),
        "minimum_fundamentacao_grade": search.get(CANONICAL_GRADE_KEY),
        "evaluation_method": evaluation.get("method"),
        "validation_requested": str(evaluation.get("method") or "none") not in {"none", "not_requested", "skip", ""},
    }


def cost_estimate_from_payload(payload: Optional[Mapping[str, Any]]) -> Optional[dict]:
    """Show cost only if the API actually returned it. Never invent a number."""
    if not isinstance(payload, Mapping):
        return None
    search = payload.get("search") or {}
    audit = search.get("audit") if isinstance(search, Mapping) else None
    for source in (payload, search, audit or {}, payload.get("validation") or {}):
        if not isinstance(source, Mapping):
            continue
        for key in ("estimated_cost", "cost_estimate", "cost"):
            if key in source and source[key] not in (None, "", {}):
                return {"present": True, "value": source[key], "source": key}
    return None


def present_grade_requirement(
    snapshot: Optional[Mapping[str, Any]],
    *,
    requested_minimum_grade: Optional[int] = None,
) -> dict:
    """Requested vs attained. Never rewrite pending/not_requested/not_met/met/error.

    Classification comes from provenance.workflow_context when present.
    Consumers do not recompute it. Absence of the extension is not 'not_requested'
    and is not 'met'.
    """
    snapshot = snapshot or {}
    validation = snapshot.get("validation") or {}
    fundamentacao = validation.get("fundamentacao") or {}
    attained = fundamentacao.get("grade")
    provenance = snapshot.get("provenance") or {}
    ctx = provenance.get("workflow_context") if isinstance(provenance, Mapping) else None

    requested = requested_minimum_grade
    status_from_ctx = None
    ctx_requested = None
    if isinstance(ctx, Mapping):
        status_from_ctx = ctx.get("grade_requirement_status")
        ctx_requested = ctx.get("requested_minimum_grade")
        if ctx_requested is not None:
            requested = ctx_requested

    if status_from_ctx in GRADE_REQUIREMENT_STATUSES:
        status = status_from_ctx
        source = "workflow_context"
        integration = None
    else:
        status = None
        source = "unavailable"
        integration = "INTEGRATION_PENDING"

    # Display facts without converting statuses into each other.
    if requested is None and status is None:
        display_status = "not_requested"
        display_note = "Grau mínimo não foi solicitado neste pedido."
    elif status is None and attained is None:
        display_status = "pending"
        display_note = (
            "O grau atingido ainda não veio no resultado. "
            "Isso não significa que o grau solicitado foi recusado."
        )
    elif status is None:
        display_status = "attained_only"
        display_note = (
            "Grau atingido informado pelo resultado; a classificação "
            "solicitado vs atingido depende da extensão P01."
        )
    else:
        display_status = status
        display_note = GRADE_REQUIREMENT_LABELS.get(status, status)

    requested_shown_as_attained = bool(
        requested is not None
        and status in {"pending", "not_requested", "not_met", "error"}
        and display_status == "met"
    )

    return {
        "requested": requested,
        "attained": attained,
        "status": status,
        "display_status": display_status,
        "label": GRADE_REQUIREMENT_LABELS.get(status) if status in GRADE_REQUIREMENT_STATUSES else (
            "Grau mínimo não solicitado" if requested is None else "Grau atingido informado; classificação P01 pendente"
        ),
        "note": display_note,
        "source": source,
        "integration": integration,
        "requested_shown_as_attained": requested_shown_as_attained,
        "pending_not_converted": status != "not_met" if status == "pending" else True,
    }


def present_validation_execution(snapshot: Optional[Mapping[str, Any]], request_spec: Optional[Mapping[str, Any]] = None) -> dict:
    """Unrequested independent validation appears as not executed, not as error/zero."""
    method = None
    if request_spec:
        method = ((request_spec.get("evaluation_policy") or {}).get("method"))
    snapshot = snapshot or {}
    validation = snapshot.get("validation") or {}
    statistical = validation.get("statistical")
    precisao = validation.get("precisao") or {}
    requested = str(method or "none") not in {"none", "not_requested", "skip", "", "None"}
    has_stats = bool(statistical) if isinstance(statistical, Mapping) else bool(statistical)
    if not requested:
        return {
            "requested": False,
            "executed": False,
            "label": "Validação independente não executada",
            "not_an_error": True,
            "not_zero": True,
            "method": method or "none",
            "precisao_status": precisao.get("status"),
        }
    executed = has_stats or precisao.get("status") not in (None, "not_computed")
    return {
        "requested": True,
        "executed": bool(executed),
        "label": "Validação independente executada" if executed else "Validação independente solicitada e ainda sem resultado",
        "not_an_error": precisao.get("status") != "error",
        "not_zero": True,
        "method": method,
        "precisao_status": precisao.get("status"),
    }


def present_subject_presence(snapshot: Optional[Mapping[str, Any]]) -> dict:
    """Absence of workflow_context is not proof the imóvel is missing."""
    snapshot = snapshot or {}
    provenance = snapshot.get("provenance") or {}
    ctx = provenance.get("workflow_context") if isinstance(provenance, Mapping) else None
    if not isinstance(ctx, Mapping):
        return {
            "extension_available": False,
            "subject_confirmed": None,
            "imovel_ausente": False,
            "false_absent_alert": False,
            "label": "Extensão de contexto do fluxo não presente — isso não prova que o imóvel está ausente.",
            "integration": "INTEGRATION_PENDING",
            "selection_scope": None,
            "limitation_codes": [],
        }
    raw = ctx.get("subject_raw")
    confirmed = raw not in (None, {}, [])
    return {
        "extension_available": True,
        "subject_confirmed": confirmed,
        "imovel_ausente": False if confirmed else raw is None,
        "false_absent_alert": False,
        "label": (
            "Imóvel avaliando confirmado no contexto do fluxo."
            if confirmed
            else "Contexto do fluxo não traz o imóvel avaliando."
        ),
        "integration": None,
        "selection_scope": ctx.get("selection_scope"),
        "limitation_codes": list(ctx.get("limitation_codes") or []),
        "schema_version": ctx.get("schema_version"),
    }


def group_issues(issues: Optional[Sequence[Any]]) -> list:
    """Group repeated warnings without dropping severity, affected ids or origin."""
    grouped: dict = {}
    order: list = []
    for issue in issues or []:
        if not isinstance(issue, Mapping):
            key = ("raw", str(issue), "info", None)
            item = {
                "code": None,
                "severity": "info",
                "origin": None,
                "message": str(issue),
                "affected_ids": [],
                "count": 1,
                "provenance": None,
            }
        else:
            key = (
                issue.get("code"),
                issue.get("message"),
                issue.get("severity") or "warning",
                issue.get("origin"),
            )
            item = {
                "code": issue.get("code"),
                "severity": issue.get("severity") or "warning",
                "origin": issue.get("origin"),
                "message": issue.get("message") or issue.get("code"),
                "affected_ids": list(issue.get("affected_ids") or []),
                "count": 1,
                "provenance": issue.get("origin"),
                "evidence": issue.get("evidence"),
            }
        if key not in grouped:
            grouped[key] = item
            order.append(key)
        else:
            grouped[key]["count"] += 1
            extra = list(issue.get("affected_ids") or []) if isinstance(issue, Mapping) else []
            for affected in extra:
                if affected not in grouped[key]["affected_ids"]:
                    grouped[key]["affected_ids"].append(affected)
    return [grouped[key] for key in order]


def alternatives_comparable(
    current: Optional[Mapping[str, Any]],
    alternative: Optional[Mapping[str, Any]],
) -> dict:
    """Compare only when unit/date/estimand and comparison sample match.

    No average across models. No frontend-only adoption.
    """
    current = current or {}
    alternative = alternative or {}
    cur_target = current.get("target") or {}
    alt_target = alternative.get("target") or current.get("target") or {}
    if alternative.get("target") is None and alternative.get("unit") is not None:
        alt_target = {
            "unit": alternative.get("unit"),
            "estimand": alternative.get("estimand"),
        }
    unit_ok = (cur_target.get("unit") or None) == (alt_target.get("unit") or alternative.get("unit") or None)
    estimand_ok = (cur_target.get("estimand") or None) == (
        alt_target.get("estimand") or alternative.get("estimand") or None
    )
    date_ok = (current.get("reference_date") or None) == (
        alternative.get("reference_date") or current.get("reference_date") or None
    )
    cur_sample = (current.get("sample") or {}).get("used")
    alt_sample = (alternative.get("sample") or {}).get("used")
    if alt_sample is None:
        alt_sample = alternative.get("comparison_sample_used")
    sample_ok = True
    if cur_sample is not None and alt_sample is not None:
        sample_ok = cur_sample == alt_sample
    ok = bool(unit_ok and estimand_ok and date_ok and sample_ok)
    reasons = []
    if not unit_ok:
        reasons.append("unidade incompatível")
    if not estimand_ok:
        reasons.append("estimando incompatível")
    if not date_ok:
        reasons.append("data-base incompatível")
    if not sample_ok:
        reasons.append("amostra de comparação incompatível")
    return {
        "comparable": ok,
        "reasons": reasons,
        "read_only": True,
        "may_adopt_in_frontend": False,
        "may_average_models": False,
        "may_turn_delta_into_ci": False,
    }


def present_batch_items(batch_payload: Optional[Mapping[str, Any]]) -> list:
    """Map C14 items to válido / não suportado / pendente without recomputing."""
    payload = batch_payload or {}
    items = payload.get("items") or payload.get("assessments") or payload.get("result", {}).get("items")
    if isinstance(payload.get("result"), Mapping) and not items:
        items = payload["result"].get("items") or payload["result"].get("assessments")
    rows = []
    for index, item in enumerate(items or []):
        item = item or {}
        status = str(item.get("status") or item.get("state") or "")
        eligibility = item.get("model_eligibility") or {}
        elig_status = eligibility.get("status") if isinstance(eligibility, Mapping) else None
        point = None
        value = item.get("value") if isinstance(item.get("value"), Mapping) else {}
        if value:
            point = value.get("point")
        if status == "unsupported" or elig_status == "unsupported":
            ui = BATCH_UI_NAO_SUPORTADO
        elif status in {"pending", "running", "cancelled", "interrupted", ""}:
            ui = BATCH_UI_PENDENTE
        elif status == "succeeded" and point is not None:
            ui = BATCH_UI_VALIDO
        elif status == "succeeded":
            ui = BATCH_UI_PENDENTE
        elif status == "failed":
            ui = BATCH_UI_PENDENTE
        else:
            ui = BATCH_UI_PENDENTE
        rows.append({
            "index": index,
            "subject_id": item.get("subject_id") or item.get("id") or index,
            "ui_status": ui,
            "raw_status": status or None,
            "eligibility": elig_status,
            "point": point,
            "recomputed_in_browser": False,
        })
    return rows


def present_delivery_state(
    job: Optional[Mapping[str, Any]],
    artifact_view: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Job succeeded is not overall 'concluído' when PDF/artifacts differ."""
    job = job or {}
    artifacts = artifact_view or {}
    state = job.get("state")
    calc_ready = bool(job.get("result_available")) or state == "succeeded"
    pdf_failed = bool(artifacts.get("pdf_failed"))
    pdf_ready = False
    for item in artifacts.get("items") or []:
        name = str(item.get("name") or "").lower()
        if name.endswith(".pdf") and item.get("state") == "ready":
            pdf_ready = True
    overall = "complete" if calc_ready and pdf_ready and not pdf_failed else (
        "calculation_ready_artifact_unavailable" if calc_ready and pdf_failed else (
            "calculation_ready" if calc_ready else (state or "unknown")
        )
    )
    if overall == "complete":
        headline = "Cálculo e documento disponíveis"
    elif overall == "calculation_ready_artifact_unavailable":
        headline = "Cálculo disponível — documento PDF indisponível"
    elif overall == "calculation_ready":
        headline = "Cálculo disponível"
    elif state == "failed":
        headline = "Falha no cálculo"
    elif state in {"queued", "running"}:
        headline = "Cálculo em andamento"
    else:
        headline = job.get("state_label") or "Estado do trabalho"
    return {
        "job_state": state,
        "calculation_ready": calc_ready,
        "pdf_failed": pdf_failed,
        "pdf_ready": pdf_ready,
        "overall": overall,
        "headline": headline,
        "labeled_concluido": False,
        "offer_calculation_download": bool(artifacts.get("offer_calculation_download") or pdf_failed),
    }


def next_actions_or_navigation_fallback(
    snapshot: Optional[Mapping[str, Any]],
    *,
    has_preview: bool = False,
    has_subject: bool = False,
    has_unit: bool = False,
    has_reference_date: bool = False,
) -> dict:
    """Use producer next_actions when present. Navigation fallback only for missing data."""
    actions = list((snapshot or {}).get("next_actions") or [])
    if actions:
        return {"source": "next_actions", "actions": actions, "fallback": False}
    fallback = []
    if not has_preview:
        fallback.append({"code": "nav_preview", "next_step": NAV_FALLBACK_WHEN_ABSENT["preview"]})
    if not has_unit:
        fallback.append({"code": "nav_unit", "next_step": NAV_FALLBACK_WHEN_ABSENT["target_unit"]})
    if not has_reference_date:
        fallback.append({"code": "nav_date", "next_step": NAV_FALLBACK_WHEN_ABSENT["reference_date"]})
    if not has_subject:
        fallback.append({"code": "nav_subject", "next_step": NAV_FALLBACK_WHEN_ABSENT["subject"]})
    if snapshot is None:
        fallback.append({"code": "nav_result", "next_step": NAV_FALLBACK_WHEN_ABSENT["result"]})
    return {"source": "navigation_fallback", "actions": fallback, "fallback": True}


def normalize_projects_list(payload: Any) -> list:
    if payload is None:
        return []
    if isinstance(payload, list):
        return list(payload)
    if isinstance(payload, Mapping):
        items = payload.get("projects")
        if isinstance(items, list):
            return list(items)
        if payload.get("project_id"):
            return [dict(payload)]
    return []


def list_route_unavailable(status_code: Optional[int]) -> bool:
    """BASE_SHA registers POST /projects/{id}/revisions only; GET is 405, not 404."""
    try:
        code = int(status_code) if status_code is not None else 0
    except (TypeError, ValueError):
        return False
    return code in {404, 405, 501}


def revisions_from_payload(payload: Any) -> list:
    if payload is None:
        return []
    if isinstance(payload, list):
        return list(payload)
    if isinstance(payload, Mapping):
        items = payload.get("revisions")
        if isinstance(items, list):
            return list(items)
        if isinstance(payload.get("revision"), Mapping):
            return [payload["revision"]]
    return []


def pick_revision(payload: Any, revision_id: Optional[str]) -> Optional[dict]:
    """Select a revision mapping by revision_id or job_id. Never screen text."""
    if not revision_id:
        return None
    wanted = str(revision_id)
    for item in revisions_from_payload(payload):
        if not isinstance(item, Mapping):
            if str(item) == wanted:
                return {"revision_id": str(item)}
            continue
        labels = (
            item.get("revision_id"),
            item.get("job_id"),
            (item.get("snapshot_ref") or {}).get("job_id") if isinstance(item.get("snapshot_ref"), Mapping) else None,
        )
        if any(str(label) == wanted for label in labels if label is not None):
            return dict(item)
    return None


def revision_recovery_plan(project_payload: Optional[Mapping[str, Any]]) -> dict:
    """Recover canonical frozen_project / job result — never screen text."""
    payload = project_payload or {}
    revision = payload.get("revision") if isinstance(payload.get("revision"), Mapping) else payload
    job_id = None
    if isinstance(revision, Mapping):
        job_id = revision.get("job_id") or (revision.get("snapshot_ref") or {}).get("job_id")
        if job_id is None and isinstance(revision.get("provenance"), Mapping):
            job_id = revision["provenance"].get("job_id")
    return {
        "project_id": payload.get("project_id") or (revision or {}).get("project_id"),
        "revision_id": (revision or {}).get("revision_id"),
        "job_id": job_id,
        "has_frozen_project": bool(revision) and any(
            key in (revision or {}) for key in ("request_spec", "model_state", "model_spec", "encoder_state")
        ),
        "recover_via": "GET /jobs/{id}/result" if job_id else "GET /projects/{id}",
        "from_screen_text": False,
    }


def viewport_flags(width: Optional[int]) -> dict:
    if width is None:
        return {"compact": False, "desktop_technical": True, "narrow_consult": False}
    return {
        "compact": width < 768,
        "desktop_technical": width >= 1200,
        "narrow_consult": width < 768,
        "width": width,
    }
