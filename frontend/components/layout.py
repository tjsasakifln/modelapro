"""Layout e apresentação do resultado (campanha C09).

O bloco principal é o valor, as faixas e as pendências para revisão
profissional. Diagnósticos, coeficientes, amostra e alternativas ficam
acessíveis — não somem. Nenhum banner «atende à norma» é derivado de um
único booleano.
"""

from __future__ import annotations

import html
import json
import math
import os
from typing import Any, Mapping, Optional, Sequence

import streamlit as st

from .forms import (
    ACTIVE_JOB_STATES,
    ApiConnectionError,
    ApiResponseError,
    JobClient,
    TERMINAL_JOB_STATES,
    may_start_execution,
)
from .professional import (
    BACKUP_NOTICE,
    HOMOLOGATION_FORBIDDEN_BADGES,
    feature_map_to_original,
    map_issuance_to_case_release,
    present_aptidao,
    present_calculated_vs_adopted,
    present_independent_validation_coverage,
    present_qualification_context,
    present_seguro_value_basis,
    present_valid_not_released,
    redact_diagnostic,
    select_qualification_profile,
)
from .workflow import (
    alternatives_comparable,
    group_issues,
    next_actions_or_navigation_fallback,
    present_delivery_state,
    present_grade_requirement,
    present_subject_presence,
    present_validation_execution,
    viewport_flags,
)

WORK_FLOW_HEADINGS = [
    "1. Encomenda e perfil",
    "2. Amostra e evidências",
    "3. Avaliando e vistoria",
    "4. Modelagem e revisão",
    "5. Emissão e arquivo",
]

FIXTURE_SCREEN_NOTICE = (
    "Verificação visual local com dados de exemplo — não é conclusão real do caso."
)

PRECISAO_STATUS_LABELS = {
    "not_computed": "Não calculada",
    "classified": "Classificada",
    "unclassified": "Não classificável",
    "error": "Erro no cálculo",
}

INTERVAL_LABELS = (
    ("mean_ci80", "Intervalo de confiança da média (80%)"),
    ("prediction_interval", "Intervalo de predição"),
    ("arbitration_interval", "Intervalo de arbitragem"),
    ("admissible_interval", "Intervalo admissível"),
)
INTERVAL_KINDS = {
    "mean_ci80": "statistical_mean",
    "prediction_interval": "prediction",
    "arbitration_interval": "arbitrated",
    "admissible_interval": "admissible",
}
ARBITRATION_NOT_CONFIDENCE = "Faixa arbitrada — não é intervalo de confiança."

ISSUANCE_LABELS = {
    "draft": "Rascunho / análise apenas",
    "review_required": "Revisão profissional necessária",
    "ready_for_professional_review": "Pronto para revisão profissional",
}

CASE_RELEASE_LABELS = {
    "analysis_only": "Análise apenas — não liberada",
    "review_required": "Revisão profissional necessária",
    "ready_for_professional_signoff": "Pronto para assinatura do responsável",
    "signed_integrity_verified": "Arquivo assinado importado com vínculo verificado",
}

JOB_STATE_LABELS = {
    "queued": "Na fila",
    "running": "Em execução",
    "succeeded": "Cálculo disponível",
    "failed": "Falha no cálculo",
    "cancelled": "Cancelado",
    "interrupted": "Interrompido",
}

ARTIFACT_STATE_LABELS = {
    "pending": "Pendente",
    "running": "Gerando",
    "ready": "Pronto para baixar",
    "failed": "Falha na geração",
}

NORMA_BANNER_FORBIDDEN = "atende à norma"


def format_optional_number(value: Any, *, decimals: int = 2, unit: Optional[str] = None) -> str:
    """Nunca aplica :.4f em None e nunca substitui ausência por zero."""
    if value is None or isinstance(value, bool):
        return "não calculado"
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            return "não calculado"
        quantized = f"{value:,.{decimals}f}"
        # 1,234.56 → 1.234,56
        quantized = quantized.replace(",", " ").replace(".", ",").replace(" ", ".")
        if unit:
            return f"{quantized} {unit}"
        return quantized
    return "não calculado"


def _interval_bounds(raw: Any) -> tuple:
    if not isinstance(raw, Mapping):
        return None, None
    return raw.get("lower"), raw.get("upper")


def present_snapshot(
    snapshot: Optional[Mapping[str, Any]],
    *,
    viewport_width: Optional[int] = None,
    max_table_rows: Optional[int] = None,
    request_spec: Optional[Mapping[str, Any]] = None,
    stale_reason: Optional[str] = None,
) -> dict:
    """Modelo de apresentação do ResultSnapshot. Testável sem Streamlit."""
    flags = viewport_flags(viewport_width)
    compact = flags["compact"]
    headings = [
        "Valor da avaliação",
        "Unidade e data-base",
        "Intervalo de confiança da média e intervalo de predição",
        "Grau e limitações",
        "Pendências para revisão profissional",
    ]
    if not snapshot:
        subject_presence = present_subject_presence(None)
        return {
            "empty": True,
            "headings": headings,
            "value_block": None,
            "intervals": [],
            "issues": [],
            "issues_count": 0,
            "warnings_visible": True,
            "norma_banner": None,
            "compact": compact,
            "narrow_consult": flags["narrow_consult"],
            "desktop_technical": flags["desktop_technical"],
            "primary_language": "pt-BR",
            "internal_keys_exposed": False,
            "next_actions": [],
            "subject_presence": subject_presence,
            "grade_requirement": present_grade_requirement(None),
            "validation_execution": present_validation_execution(None, request_spec),
            "stale_reason": stale_reason,
            "false_imovel_ausente": False,
            "qualification": present_qualification_context(None, selected_profile=(request_spec or {}).get("qualification_profile") if request_spec else None),
            "aptidao": present_aptidao(),
            "homologation_badge": None,
            "aceito_pelo_banco": False,
        }

    target = snapshot.get("target") or {}
    value = snapshot.get("value") or {}
    validation = snapshot.get("validation") or {}
    precisao = validation.get("precisao") or {}
    fundamentacao = validation.get("fundamentacao") or {}
    issuance = validation.get("issuance") or {}
    issues = list(snapshot.get("issues") or [])
    next_actions = list(snapshot.get("next_actions") or [])
    sample = dict(snapshot.get("sample") or {})
    model = dict(snapshot.get("model") or {})
    alternatives = list(snapshot.get("alternatives") or [])
    search = dict(snapshot.get("search") or {})

    point = value.get("point")
    unit = target.get("unit")
    missing_point = point is None
    if missing_point:
        point_display = "Valor não calculado"
    else:
        point_display = format_optional_number(point, decimals=2, unit=unit)

    value_block = {
        "title": "Valor da avaliação",
        "point": point,
        "point_display": point_display,
        "missing_point": missing_point,
        "substituted_zero": False,
        "unit": unit,
        "unit_display": unit if unit else "unidade não informada",
        "unit_pending": not unit,
        "estimand": target.get("estimand") or "estimando não informado",
        "reference_date": snapshot.get("reference_date") or "data-base não informada",
        "generated_at": snapshot.get("generated_at"),
        "inspection_distinct_from_emission": True,
        "target_column": target.get("column"),
    }

    intervals = []
    for key, label in INTERVAL_LABELS:
        raw = value.get(key)
        lower, upper = _interval_bounds(raw)
        kind = INTERVAL_KINDS.get(key)
        intervals.append({
            "key": key,
            "label": label,
            "kind": kind,
            "arbitrated": kind == "arbitrated",
            "not_confidence": kind == "arbitrated",
            "note": ARBITRATION_NOT_CONFIDENCE if kind == "arbitrated" else None,
            "present": raw is not None,
            "lower": lower,
            "upper": upper,
            "lower_display": format_optional_number(lower),
            "upper_display": format_optional_number(upper),
        })

    precisao_status = precisao.get("status") or "not_computed"
    precisao_view = {
        "status": precisao_status,
        "label": PRECISAO_STATUS_LABELS.get(precisao_status, str(precisao_status)),
        "grade": precisao.get("grade"),
        "amplitude_pct": precisao.get("amplitude_pct"),
        "amplitude_display": format_optional_number(precisao.get("amplitude_pct"), decimals=1),
    }

    used_ids = list(sample.get("used_row_ids") or [])
    truncated = False
    if max_table_rows is not None and len(used_ids) > max_table_rows:
        used_display = used_ids[:max_table_rows]
        truncated = True
    else:
        used_display = used_ids

    actions_view = []
    for action in next_actions:
        action = action or {}
        evidence = action.get("evidence_refs")
        if evidence is None:
            evidence = []
        limitations = action.get("limitations")
        actions_view.append({
            "code": action.get("code"),
            "priority": action.get("priority"),
            "reason": action.get("reason"),
            "next_step": action.get("next_step"),
            "evidence_refs": list(evidence) if not isinstance(evidence, str) else [evidence],
            "limitations": limitations if limitations not in (None, "") else "Limitações não informadas",
            "evidence_visible": True,
            "limitations_visible": True,
        })

    # Campo legado is_valid, se existir, é ignorado de propósito.
    _legacy_is_valid = validation.get("is_valid")  # noqa: F841

    requested_grade = None
    selected_profile = None
    if request_spec:
        requested_grade = (request_spec.get("search_policy") or {}).get("minimum_fundamentacao_grade")
        raw_profile = request_spec.get("qualification_profile")
        if isinstance(raw_profile, Mapping) and raw_profile.get("id"):
            selected_profile = select_qualification_profile(
                raw_profile.get("id"),
                purpose=raw_profile.get("purpose"),
                value_basis=raw_profile.get("value_basis"),
                method=raw_profile.get("method"),
                asset_scope=raw_profile.get("asset_scope"),
                recipient_id=raw_profile.get("recipient_id"),
                version=raw_profile.get("version"),
                source_set_sha256=raw_profile.get("source_set_sha256"),
            )
        else:
            selected_profile = raw_profile
    grade_requirement = present_grade_requirement(snapshot, requested_minimum_grade=requested_grade)
    subject_presence = present_subject_presence(snapshot)
    qualification = present_qualification_context(snapshot, selected_profile=selected_profile)
    issuance_map = map_issuance_to_case_release(issuance.get("status"))
    validation_coverage = present_independent_validation_coverage(snapshot, request_spec)
    aptidao = present_aptidao(
        grade_requirement_status=grade_requirement.get("status") or qualification.get("grade_requirement_status"),
        calculation_status=qualification.get("calculation_status"),
        profile=selected_profile if isinstance(selected_profile, Mapping) else {},
        issuance_status=issuance.get("status"),
    )
    if qualification.get("calculation_status") == "valid_not_released" or (
        grade_requirement.get("status") in {"pending", "not_met"} and point is not None
    ):
        not_released = present_valid_not_released(
            reason=grade_requirement.get("note") or "Análise calculável, não liberada para emissão.",
            action="Revisar evidências e requisitos do perfil; o pedido de grau é preservado.",
            requested_grade=requested_grade,
        )
    else:
        not_released = None
    seguro_basis = None
    if isinstance(selected_profile, Mapping) and selected_profile.get("purpose") == "seguro":
        seguro_basis = present_seguro_value_basis(selected_profile)
    adopted = present_calculated_vs_adopted(
        calculated_point=point,
        c05_admits=None,
    )
    feature_schema = None
    if isinstance(model, Mapping):
        feature_schema = model.get("feature_schema") or model.get("schema")
    if feature_schema is None:
        feature_schema = snapshot.get("feature_schema")
    raw_coefficients = model.get("coefficients") if isinstance(model, Mapping) else None
    coefficient_map = feature_map_to_original(
        raw_coefficients if isinstance(raw_coefficients, Mapping) else None,
        feature_schema if isinstance(feature_schema, Mapping) else None,
    )
    grouped = group_issues(issues)
    comparable_alts = []
    for alt in alternatives:
        alt_map = alt if isinstance(alt, Mapping) else {"candidate_id": alt}
        comparable_alts.append({
            **dict(alt_map),
            "comparison": alternatives_comparable(snapshot, alt_map),
        })
    first_contact_intervals = [
        item for item in intervals if item["key"] in {"mean_ci80", "prediction_interval"}
    ]
    second_level_intervals = [
        item for item in intervals if item["key"] not in {"mean_ci80", "prediction_interval"}
    ]
    navigation = next_actions_or_navigation_fallback(
        snapshot,
        has_preview=True,
        has_subject=subject_presence.get("subject_confirmed") is not False,
        has_unit=bool(unit),
        has_reference_date=bool(snapshot.get("reference_date")),
    )
    displayed_actions = actions_view if actions_view else [
        {
            "code": item.get("code"),
            "priority": "info",
            "reason": None,
            "next_step": item.get("next_step"),
            "evidence_refs": [],
            "limitations": "Fallback de navegação — dado ausente, não correção substantiva.",
            "evidence_visible": True,
            "limitations_visible": True,
        }
        for item in navigation["actions"]
    ]

    return {
        "empty": False,
        "headings": headings,
        "value_block": value_block,
        "intervals": intervals,
        "first_contact_intervals": first_contact_intervals,
        "second_level_intervals": second_level_intervals,
        "precisao": precisao_view,
        "fundamentacao": {
            "grade": fundamentacao.get("grade"),
            "points": fundamentacao.get("points"),
            "items": list(fundamentacao.get("items") or []),
        },
        "grade_requirement": grade_requirement,
        "validation_execution": present_validation_execution(snapshot, request_spec),
        "subject_presence": subject_presence,
        "false_imovel_ausente": False,
        "issuance": {
            "status": issuance.get("status"),
            "label": ISSUANCE_LABELS.get(issuance.get("status"), issuance.get("status") or "não informado"),
            "reasons": list(issuance.get("reasons") or []),
            "case_release_status": issuance_map.get("case_release_status"),
            "case_release_label": CASE_RELEASE_LABELS.get(issuance_map.get("case_release_status") or "", ""),
            "emitted_illegal_issuance": False,
        },
        "qualification": qualification,
        "aptidao": aptidao,
        "valid_not_released": not_released,
        "validation_coverage": validation_coverage,
        "seguro_value_basis": seguro_basis,
        "calculated_vs_adopted": adopted,
        "homologation_badge": None,
        "aceito_pelo_banco": False,
        "issues": issues,
        "grouped_issues": grouped,
        "issues_count": len(issues),
        "warnings_visible": True,
        "next_actions": displayed_actions if displayed_actions else actions_view,
        "next_actions_source": navigation["source"],
        "sample": {
            **sample,
            "used_row_ids_display": used_display,
            "table_truncated": truncated,
            "used_row_ids_total": len(used_ids),
        },
        "model": model,
        "coefficient_map": coefficient_map,
        "dummy_name_required": False,
        "search": search,
        "alternatives": comparable_alts,
        "alternatives_read_only": True,
        "diagnostics_available": bool(
            model.get("diagnostics") or model.get("coefficients") or model.get("formula")
        ),
        "norma_banner": None,
        "compact": compact,
        "narrow_consult": flags["narrow_consult"],
        "desktop_technical": flags["desktop_technical"],
        "primary_language": "pt-BR",
        "internal_keys_exposed": False,
        "statistical": dict(validation.get("statistical") or {}),
        "documentary": dict(validation.get("documentary") or {}),
        "provenance": dict(snapshot.get("provenance") or {}),
        "job_id": snapshot.get("job_id"),
        "project_id": snapshot.get("project_id"),
        "stale_reason": stale_reason,
        "technical_ids": {
            "job_id": snapshot.get("job_id"),
            "project_id": snapshot.get("project_id"),
            "input_sha256": snapshot.get("input_sha256"),
            "code_sha": snapshot.get("code_sha"),
        },
    }


def present_job_status(job: Optional[Mapping[str, Any]]) -> dict:
    job = job or {}
    state = job.get("state")
    progress = job.get("progress")
    if progress is not None:
        try:
            progress = float(progress)
            if progress < 0 or progress > 1 or not math.isfinite(progress):
                progress = None
        except (TypeError, ValueError):
            progress = None
    return {
        "job_id": job.get("job_id"),
        "state": state,
        "state_label": JOB_STATE_LABELS.get(state, state or "desconhecido"),
        "stage": job.get("stage"),
        "progress": progress,
        "result_available": bool(job.get("result_available")),
        "can_cancel": state in ACTIVE_JOB_STATES,
        "can_save": bool(job.get("result_available")) or state == "succeeded",
        "can_rerun": may_start_execution(job),
        "issues": list(job.get("issues") or []),
        "artifact_states": dict(job.get("artifact_states") or {}),
        "labeled_concluido": False,
        "calculation_ready": bool(job.get("result_available")) or state == "succeeded",
    }


def present_artifacts(artifact_states: Optional[Mapping[str, Any]]) -> dict:
    items = []
    for name, meta in (artifact_states or {}).items():
        meta = meta or {}
        state = meta.get("state") or "pending"
        items.append({
            "name": name,
            "state": state,
            "state_label": ARTIFACT_STATE_LABELS.get(state, str(state)),
            "error": meta.get("error"),
            "can_download": state == "ready",
        })
    pdf_failed = any(
        str(item["name"]).lower().endswith(".pdf") and item["state"] == "failed"
        for item in items
    )
    calc_ready = any(
        item["state"] == "ready"
        and (
            "calc" in str(item["name"]).lower()
            or str(item["name"]).lower().endswith(".json")
            or "snapshot" in str(item["name"]).lower()
        )
        for item in items
    )
    return {
        "items": items,
        "pdf_failed": pdf_failed,
        "offer_calculation_download": pdf_failed,
        "calculation_ready": calc_ready,
        "calculation_download_label": "Baixar cálculo (o PDF falhou)",
    }


def snapshot_contains_forbidden_norma_banner(view: Mapping[str, Any]) -> bool:
    if view.get("norma_banner"):
        return True
    if view.get("homologation_badge") or view.get("aceito_pelo_banco"):
        return True
    blob = json.dumps(
        {k: view.get(k) for k in ("headings", "norma_banner", "issuance", "precisao", "value_block", "homologation_badge", "aptidao")},
        ensure_ascii=False,
        default=str,
    ).lower()
    if NORMA_BANNER_FORBIDDEN in blob:
        return True
    return any(token in blob for token in HOMOLOGATION_FORBIDDEN_BADGES)


def load_css() -> None:
    css_path = os.path.join(os.path.dirname(__file__), "..", "assets", "styles.css")
    if os.path.exists(css_path):
        with open(css_path, "r", encoding="utf-8") as handle:
            st.markdown(f"<style>{handle.read()}</style>", unsafe_allow_html=True)


def header() -> None:
    st.title("MODELA PRO")
    st.markdown(
        '<p class="mp-subtitle">Encomenda, amostra, vistoria, modelagem e emissão revisada pelo responsável</p>',
        unsafe_allow_html=True,
    )


def sidebar() -> dict:
    with st.sidebar:
        st.header("Trabalho")
        from importlib.metadata import PackageNotFoundError, version
        from importlib.resources import files
        try:
            product_version = version("modelapro")
        except PackageNotFoundError:
            product_version = "checkout de desenvolvimento"
        st.caption(f"MODELA PRO · {product_version}")
        with st.expander("Ajuda e sobre esta instalação"):
            manual = files("frontend").joinpath("assets/manual.md").read_text(encoding="utf-8")
            st.markdown(manual)
            st.download_button("Baixar manual desta instalação", manual, "MODELA-PRO-manual.md", "text/markdown")
        st.caption(
            "Percurso profissional. Use Tab e as setas. O estado também está escrito, "
            "não só colorido. Duplo clique no disparo é bloqueado."
        )
        st.caption(BACKUP_NOTICE)
        visual_fixture = st.checkbox(
            "Tela de verificação visual (exemplo)",
            value=False,
            help=FIXTURE_SCREEN_NOTICE,
        )
        if visual_fixture:
            st.warning(FIXTURE_SCREEN_NOTICE)
        st.markdown("**Percurso**")
        for heading in WORK_FLOW_HEADINGS:
            st.markdown(f"- {heading}")
        api_url = st.text_input(
            "Endereço da API local",
            value=os.environ.get("MODELA_API_URL", "http://127.0.0.1:8000"),
            help="Somente serviço local. Sem armazenamento paralelo nesta interface.",
        )
        reopen_job = st.text_input("Retomar trabalho pelo identificador", value="")
        project_id = st.text_input("Identificador do projeto", value="")
        if st.checkbox("Licença, cópia de segurança e restauração", value=False):
            _render_local_operations(JobClient(api_url))
        return {
            "visual_fixture": visual_fixture,
            "api_url": api_url,
            "reopen_job": reopen_job.strip() or None,
            "project_id": project_id.strip() or None,
        }


def _render_local_operations(client: JobClient) -> None:
    """Buyer-facing consumers of authenticated local operations, including after expiry."""
    st.caption("A licença do produto não é assinatura do laudo nem qualificação profissional.")
    try:
        decision = client.operation("GET", "/operations/license").json()
        st.write("Cálculo habilitado" if decision.get("calculate") else "Cálculo não habilitado pela licença")
        st.caption("Consulta, exportação e backup permanecem disponíveis após expiração.")
        entitlement = st.file_uploader("Licença do comprador fornecida pelo titular", type=["json"], key="buyer_license")
        if st.button("Instalar licença"):
            if entitlement is None:
                st.warning("Selecione o envelope de licença recebido. Não informe chaves privadas.")
            else:
                client.operation("POST", "/operations/license", content=entitlement.getvalue())
                st.success("Envelope de licença validado e armazenado localmente.")
        if st.button("Preparar cópia de segurança"):
            st.session_state["workspace_backup_bytes"] = client.operation("GET", "/operations/backup").content
        if st.session_state.get("workspace_backup_bytes"):
            st.download_button("Baixar cópia de segurança", st.session_state["workspace_backup_bytes"],
                               file_name="modelapro-backup.zip", mime="application/zip")
        backup = st.file_uploader("Cópia para restaurar em espaço vazio", type=["zip"], key="workspace_restore")
        st.caption("A restauração exige espaço vazio e preserva os arquivos existentes. Verifica integridade antes de ativar.")
        if st.button("Restaurar cópia verificada"):
            if backup is None:
                st.warning("Selecione uma cópia de segurança.")
            else:
                result = client.operation("POST", "/operations/restore",
                                          files={"file": (backup.name, backup.getvalue(), "application/zip")}).json()
                st.success(f"Cópia restaurada: {result['job_count']} trabalhos.")
    except (ApiConnectionError, ApiResponseError) as exc:
        st.error(str(exc))


def render_flow_nav(current: int = 0) -> int:
    choice = st.radio(
        "Etapa do trabalho",
        options=WORK_FLOW_HEADINGS,
        index=min(max(current, 0), len(WORK_FLOW_HEADINGS) - 1),
        horizontal=False,
        label_visibility="visible",
    )
    return WORK_FLOW_HEADINGS.index(choice)


def _issue_text(issue: Any) -> str:
    if isinstance(issue, Mapping):
        return str(issue.get("message") or issue.get("code") or issue)
    return str(issue)


def render_snapshot_panel(view: Mapping[str, Any], *, fixture: bool = False) -> None:
    st.subheader("4. Modelagem e revisão")
    if fixture:
        st.warning(FIXTURE_SCREEN_NOTICE)
    if view.get("stale_reason"):
        st.warning(view["stale_reason"])

    if view.get("empty"):
        st.info("Ainda não há resultado para revisar.")
        presence = view.get("subject_presence") or {}
        if presence.get("extension_available") is False:
            st.caption(presence.get("label") or "")
        return

    value_block = view.get("value_block") or {}
    point_html = html.escape(str(value_block.get("point_display") or "Valor não calculado"))
    unit_html = html.escape(str(value_block.get("unit_display") or ""))
    estimand_html = html.escape(str(value_block.get("estimand") or ""))
    ref_html = html.escape(str(value_block.get("reference_date") or ""))
    compact_class = " mp-compact" if view.get("compact") else ""

    st.markdown(
        f"""
        <section class="mp-value-hero{compact_class}" role="region" aria-label="Valor da avaliação">
          <p class="mp-value-kicker">Valor da avaliação</p>
          <p class="mp-value-figure">{point_html}</p>
          <p class="mp-value-meta">
            Unidade: {unit_html}<br/>
            Estimando: {estimand_html}<br/>
            Data-base: {ref_html}
          </p>
        </section>
        """,
        unsafe_allow_html=True,
    )
    if value_block.get("generated_at"):
        st.caption(
            f"Emissão do resultado: {value_block['generated_at']} "
            "(não confundir com a data-base nem com a data da vistoria)."
        )

    precisao = view.get("precisao") or {}
    fundamentacao = view.get("fundamentacao") or {}
    issuance = view.get("issuance") or {}
    grade_req = view.get("grade_requirement") or {}
    validation_exec = view.get("validation_execution") or {}
    presence = view.get("subject_presence") or {}

    if view.get("compact"):
        st.markdown(f"**Fundamentação atingida:** grau {fundamentacao.get('grade') if fundamentacao.get('grade') is not None else 'não classificado'}")
        st.markdown(f"**Grau solicitado:** {grade_req.get('requested') if grade_req.get('requested') is not None else 'não solicitado'} — {grade_req.get('label')}")
        st.markdown(f"**Precisão:** {precisao.get('label')} (grau {precisao.get('grade') if precisao.get('grade') is not None else '—'})")
        st.markdown(f"**Situação para revisão:** {issuance.get('label')}")
    else:
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            grade = fundamentacao.get("grade")
            st.metric("Grau atingido", f"Grau {grade}" if grade is not None else "Não classificado")
            st.caption(grade_req.get("label") or "")
            if grade_req.get("requested") is not None:
                st.caption(f"Solicitado: grau {grade_req['requested']}")
        with col_b:
            st.metric("Precisão", precisao.get("label") or "Não calculada")
            if precisao.get("grade") is not None:
                st.caption(f"Grau de precisão: {precisao['grade']}")
            if validation_exec:
                st.caption(validation_exec.get("label") or "")
        with col_c:
            st.metric("Revisão profissional", issuance.get("label") or "não informado")

    if presence:
        st.caption(presence.get("label") or "")
        if presence.get("false_absent_alert"):
            st.error("Alerta falso de imóvel ausente — não deveria aparecer.")

    for reason in issuance.get("reasons") or []:
        st.info(reason)

    aptidao = view.get("aptidao") or {}
    if aptidao:
        st.markdown(f"**Aptidão do caso:** {aptidao.get('ui_status')} — {aptidao.get('headline')}")
        if aptidao.get("global_green"):
            st.error("A interface não deve produzir sucesso visual global a partir de um único indicador.")
        if aptidao.get("may_show_approved_value"):
            st.error("Caso não liberado não deve aparecer como valor aprovado.")
        if aptidao.get("can_prepare_laudo"):
            st.info("Percurso legítimo: pode seguir para a preparação do laudo final.")
    not_released = view.get("valid_not_released")
    if not_released:
        st.warning(not_released.get("reason") or "Análise acessível, não liberada.")
        if not_released.get("action"):
            st.caption(f"Ação que pode resolver: {not_released['action']}")
        if not_released.get("field"):
            st.caption(f"Campo/evidência: {not_released['field']}")
    case_release = issuance.get("case_release_label")
    if case_release:
        st.caption(f"Estado de liberação (mapeado, sem inventar status MP/1): {case_release}")
    if view.get("homologation_badge") or view.get("aceito_pelo_banco"):
        st.error("Selo institucional indevido — compatibilidade não é aceite.")
    seguro = view.get("seguro_value_basis")
    if seguro:
        st.info(seguro.get("note"))
        st.caption(f"Base de valor requerida: {seguro.get('required_label')}")
        if seguro.get("mismatch"):
            st.warning("Descompasso entre finalidade securitária e base/método — não ocultado.")
    adopted = view.get("calculated_vs_adopted") or {}
    if adopted:
        st.caption(
            f"Valor calculado: {adopted.get('calculated')}. "
            f"Valor adotado distinto só é registrado se C05 admitir ({adopted.get('note') or 'sem override silencioso'})."
        )
    coverage = view.get("validation_coverage") or {}
    if coverage:
        st.caption(coverage.get("label") or "")
        if coverage.get("presented_train_as_external"):
            st.error("Métrica de treino não pode ser apresentada como validação externa.")

    st.markdown("#### Intervalo de confiança da média e intervalo de predição")
    first_rows = [
        {
            "Intervalo": item["label"],
            "Inferior": item["lower_display"],
            "Superior": item["upper_display"],
        }
        for item in (view.get("first_contact_intervals") or view.get("intervals") or [])
        if item.get("key") in {"mean_ci80", "prediction_interval"} or item.get("kind") in {"statistical_mean", "prediction"}
    ]
    if not first_rows:
        first_rows = [
            {
                "Intervalo": item["label"],
                "Inferior": item["lower_display"],
                "Superior": item["upper_display"],
            }
            for item in view.get("intervals") or []
            if item.get("key") in {"mean_ci80", "prediction_interval"}
        ]
    if first_rows:
        st.dataframe(first_rows, use_container_width=True, hide_index=True)
    else:
        st.caption("Intervalos estatísticos não vieram neste resultado.")

    sample = view.get("sample") or {}
    st.markdown("#### Contagens da amostra")
    st.write(
        {
            "Recebidos": sample.get("received"),
            "Utilizados": sample.get("used"),
            "Excluídos": sample.get("excluded"),
        }
    )

    st.markdown("#### Pendências e avisos")
    grouped = list(view.get("grouped_issues") or [])
    issues = grouped if grouped else list(view.get("issues") or [])
    if not issues:
        st.caption("Nenhum aviso estruturado no resultado.")
    for issue in issues:
        text = _issue_text(issue)
        severity = (issue or {}).get("severity") if isinstance(issue, Mapping) else "warning"
        count = issue.get("count") if isinstance(issue, Mapping) else 1
        affected = ""
        if isinstance(issue, Mapping) and issue.get("affected_ids"):
            affected = " — afetados: " + ", ".join(str(a) for a in issue["affected_ids"][:12])
        origin = ""
        if isinstance(issue, Mapping) and issue.get("origin"):
            origin = f" (origem: {issue['origin']})"
        repeated = f" ×{count}" if count and count > 1 else ""
        line = f"{text}{repeated}{affected}{origin}"
        if severity == "error":
            st.error(line)
        elif severity == "info":
            st.info(line)
        else:
            st.warning(line)
    if not view.get("warnings_visible"):
        st.error("Avisos deveriam permanecer visíveis.")

    actions = list(view.get("next_actions") or [])
    if actions:
        st.markdown("#### Encaminhamentos sugeridos")
        st.caption("Recomendações com evidência e limitações visíveis — não são ordem de emissão.")
        for action in actions:
            st.markdown(f"**{html.escape(str(action.get('next_step') or action.get('code') or 'Ação'))}**")
            if action.get("reason"):
                st.write(action["reason"])
            evidence = action.get("evidence_refs") or []
            st.caption("Evidência: " + (", ".join(str(e) for e in evidence) if evidence else "não referenciada"))
            st.caption("Limitações: " + str(action.get("limitations") or "Limitações não informadas"))

    with st.expander("Amostra utilizada e excluída", expanded=False):
        sample = view.get("sample") or {}
        st.write(
            {
                "Recebidos": sample.get("received"),
                "Com alvo observado": sample.get("observed_target"),
                "Preparados": sample.get("prepared"),
                "Utilizados": sample.get("used"),
                "Excluídos": sample.get("excluded"),
            }
        )
        used_display = sample.get("used_row_ids_display") or []
        if used_display:
            st.dataframe(
                [{"registro": row_id} for row_id in used_display],
                use_container_width=True,
                hide_index=True,
            )
        if sample.get("table_truncated"):
            st.caption(
                f"Tabela longa: mostrando {len(used_display)} de {sample.get('used_row_ids_total')} "
                "registros. Os avisos acima não foram omitidos."
            )
        excluded = sample.get("excluded_row_ids") or []
        if excluded:
            st.caption("Registros excluídos: " + ", ".join(str(x) for x in excluded[:50]))

    with st.expander("Modelo, coeficientes e diagnósticos", expanded=False):
        model = view.get("model") or {}
        if model.get("formula"):
            st.code(model.get("formula"))
        coefficient_map = view.get("coefficient_map")
        if coefficient_map:
            st.caption("Característica original — nomes dummy não são exigidos do profissional.")
            st.dataframe(
                [
                    {
                        "Característica original": row.get("original_characteristic"),
                        "Termo do modelo": row.get("feature"),
                        "Coeficiente": row.get("value"),
                    }
                    for row in coefficient_map
                ],
                use_container_width=True,
                hide_index=True,
            )
        elif model.get("coefficients"):
            mapped = feature_map_to_original(
                model.get("coefficients") if isinstance(model.get("coefficients"), Mapping) else None,
                (model.get("feature_schema") if isinstance(model.get("feature_schema"), Mapping) else None),
            )
            if mapped:
                st.dataframe(
                    [
                        {
                            "Característica original": row.get("original_characteristic"),
                            "Termo do modelo": row.get("feature"),
                            "Coeficiente": row.get("value"),
                        }
                        for row in mapped
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
        if model.get("diagnostics"):
            st.write(model.get("diagnostics"))
        if not view.get("diagnostics_available"):
            st.caption("Diagnósticos não vieram neste resultado.")
        statistical = view.get("statistical") or {}
        if statistical:
            st.write(statistical)

    with st.expander("Faixa arbitrada e intervalo admissível (não são confiança)", expanded=False):
        extra_rows = [
            {
                "Intervalo": item["label"],
                "Inferior": item["lower_display"],
                "Superior": item["upper_display"],
                "Nota": item.get("note") or "",
            }
            for item in view.get("intervals") or []
            if item.get("key") in {"arbitration_interval", "admissible_interval"}
        ]
        if extra_rows:
            st.dataframe(extra_rows, use_container_width=True, hide_index=True)
        else:
            st.caption("Faixa arbitrada e intervalo admissível não vieram neste resultado.")
        st.caption("A faixa arbitrada nunca é apresentada como intervalo de confiança.")

    with st.expander("Busca, alternativas e ressalvas (leitura)", expanded=False):
        st.caption("Comparação somente quando unidade, data-base, estimando e amostra forem compatíveis. Sem média entre modelos e sem adoção só nesta tela.")
        search = view.get("search") or {}
        if search:
            st.write(search)
        alternatives = view.get("alternatives") or []
        if alternatives:
            for alt in alternatives:
                comparison = alt.get("comparison") or {}
                st.markdown(f"**{alt.get('candidate_id') or alt.get('id') or 'alternativa'}**")
                if comparison.get("comparable"):
                    st.write(alt)
                    st.caption("Leitura — não altera o modelo adotado.")
                else:
                    reasons = comparison.get("reasons") or ["incompatível"]
                    st.info("Não comparável: " + "; ".join(reasons))
        else:
            st.caption("Nenhuma alternativa listada neste resultado.")

    with st.expander("Identificadores técnicos", expanded=False):
        st.caption("Códigos completos ficam aqui, não no primeiro contato.")
        st.json(view.get("technical_ids") or {"job_id": view.get("job_id"), "project_id": view.get("project_id")})


def render_job_panel(view: Mapping[str, Any]) -> dict:
    st.markdown("#### Situação do cálculo")
    if view.get("job_id"):
        st.caption(f"Identificador do trabalho: {view['job_id']}")
    st.write(f"Estado: **{view.get('state_label')}**")
    if view.get("labeled_concluido"):
        st.error("O cálculo disponível não deve ser rotulado como trabalho concluído.")
    if view.get("stage"):
        st.caption(f"Etapa: {view['stage']}")
    if view.get("progress") is not None:
        st.progress(view["progress"])
    else:
        st.caption("Progresso percentual não informado — a interface não inventa porcentagem.")

    for issue in view.get("issues") or []:
        st.warning(_issue_text(issue))

    cols = st.columns(2)
    pressed = {"execute": False, "cancel": False, "refresh": False}
    st.caption(
        "O disparo está no imóvel avaliando, para enviar os valores preenchidos. "
        "Upload e edição de campo não disparam cálculo sozinhos."
    )
    with cols[0]:
        pressed["cancel"] = st.button(
            "Cancelar execução",
            disabled=not view.get("can_cancel"),
        )
    with cols[1]:
        pressed["refresh"] = st.button("Atualizar estado")
    return pressed


def render_artifact_panel(
    artifact_view: Mapping[str, Any],
    job_view: Mapping[str, Any],
    snapshot: Optional[Mapping[str, Any]] = None,
    delivery: Optional[Mapping[str, Any]] = None,
) -> dict:
    st.subheader("5. Emissão e arquivo")
    pressed = {"save": False, "download_calc": False, "download_named": None, "load_projects": False}
    delivery = delivery or present_delivery_state(job_view, artifact_view)
    st.markdown(f"**{delivery.get('headline')}**")
    if delivery.get("pdf_failed"):
        st.warning("Documento PDF indisponível. O cálculo permanece.")
    if delivery.get("labeled_concluido"):
        st.error("Não tratar o término do job como entrega completa.")

    items = list(artifact_view.get("items") or [])
    if items:
        for item in items:
            st.write(f"{item['name']}: **{item['state_label']}**")
            if item.get("error"):
                st.error(_issue_text(item["error"]))
            if item.get("can_download"):
                if st.button(f"Baixar {item['name']}", key=f"c09_dl_{item['name']}"):
                    pressed["download_named"] = item["name"]
    else:
        st.caption("Nenhum artefato registrado neste trabalho ainda.")

    if artifact_view.get("offer_calculation_download"):
        st.warning("A geração do PDF falhou. O cálculo ainda pode ser baixado.")
        pressed["download_calc"] = st.download_button(
            artifact_view.get("calculation_download_label") or "Baixar cálculo (o PDF falhou)",
            data=json.dumps(snapshot or {}, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"),
            file_name="calculo_avaliacao.json",
            mime="application/json",
            disabled=snapshot is None,
        )
    elif snapshot is not None:
        st.download_button(
            "Baixar cálculo (JSON)",
            data=json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8"),
            file_name="calculo_avaliacao.json",
            mime="application/json",
        )

    pressed["save"] = st.button(
        "Salvar revisão no projeto",
        disabled=not job_view.get("can_save"),
        help="Usa POST /projects/{id}/revisions. Sem arquivo paralelo nesta interface.",
    )
    return pressed


def load_visual_fixture() -> dict:
    path = os.path.join(os.path.dirname(__file__), "..", "assets", "visual_fixture_snapshot.json")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def render_project_panel(
    *,
    projects: Optional[Sequence[Any]] = None,
    selected_project: Optional[Mapping[str, Any]] = None,
    revisions: Optional[Mapping[str, Any]] = None,
    batch_rows: Optional[Sequence[Mapping[str, Any]]] = None,
    revisions_handoff: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Lista de projetos, revisão selecionada e lote — só rotas reais."""
    pressed = {
        "refresh_projects": False,
        "open_project_id": None,
        "open_revision_id": None,
        "create_project_id": None,
        "batch_submit": False,
        "batch_subjects_text": "",
    }
    st.markdown("#### Projetos recuperáveis")
    st.caption("A lista vem de GET /projects. Reabrir recupera o frozen_project/resultado canônicos, não o texto da tela.")
    pressed["refresh_projects"] = st.button("Atualizar lista de projetos")
    query = st.text_input("Pesquisa local de projetos", value="", key="c02_project_search")
    items = list(projects or [])
    if query.strip():
        needle = query.strip().lower()
        items = [
            item for item in items
            if needle in json.dumps(item, ensure_ascii=False, default=str).lower()
        ]
    if items:
        rows = []
        for item in items:
            if not isinstance(item, Mapping):
                rows.append({"Projeto": str(item)})
                continue
            rows.append({
                "Projeto": item.get("project_id"),
                "Revisão mais recente": item.get("latest_revision_id") or item.get("revision_id"),
                "Atualizado": item.get("updated_at") or item.get("created_at"),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
        options = [str(item.get("project_id")) for item in items if isinstance(item, Mapping) and item.get("project_id")]
        chosen = st.selectbox("Selecionar projeto", options=options or [""], key="p02_project_select")
        if st.button("Abrir revisão selecionada", disabled=not chosen):
            pressed["open_project_id"] = chosen
    else:
        st.caption("Nenhum projeto listado ainda.")

    new_id = st.text_input("Novo identificador de projeto (gravação cria revisão nova)", value="", key="p02_new_project_id")
    if new_id.strip():
        pressed["create_project_id"] = new_id.strip()

    if selected_project:
        st.markdown("#### Revisão carregada")
        st.caption("Alterar e salvar cria nova revisão — a anterior permanece.")
        revision = selected_project.get("revision") if isinstance(selected_project.get("revision"), Mapping) else selected_project
        st.write({
            "Projeto": selected_project.get("project_id") or (revision or {}).get("project_id"),
            "Revisão": (revision or {}).get("revision_id"),
            "Trabalho": (revision or {}).get("job_id") or ((revision or {}).get("snapshot_ref") or {}).get("job_id"),
        })

    if revisions_handoff:
        st.info(
            "A listagem completa de revisões depende de GET /projects/{id}/revisions "
            f"(P01). Por ora só a revisão devolvida por GET /projects/{{id}} está disponível."
        )

    rev_items = (revisions or {}).get("revisions") if isinstance(revisions, Mapping) else revisions
    if rev_items:
        labels = []
        for item in rev_items:
            if isinstance(item, Mapping):
                labels.append(str(item.get("revision_id") or item.get("job_id") or item))
            else:
                labels.append(str(item))
        chosen_rev = st.selectbox("Revisão", options=labels, key="p02_revision_select")
        if st.button("Reabrir esta revisão"):
            pressed["open_revision_id"] = chosen_rev

    st.markdown("#### Lote sobre o projeto salvo")
    st.caption("POST /projects/{id}/batch. A situação de cada item vem da API; esta tela não recalcula.")
    pressed["batch_subjects_text"] = st.text_area(
        "Sujeitos do lote (JSON: lista de objetos)",
        value='[{"area": "73,5", "bairro": "Centro"}]',
        key="p02_batch_subjects",
        help="Payload já suportado: {subjects, request_spec?, revision_id?}",
    )
    pressed["batch_submit"] = st.button("Enviar lote")
    if batch_rows:
        st.dataframe(
            [
                {
                    "Item": row.get("subject_id"),
                    "Situação": {
                        "valido": "válido",
                        "nao_suportado": "não suportado",
                        "pendente": "pendente",
                    }.get(row.get("ui_status"), row.get("ui_status")),
                    "Estado bruto": row.get("raw_status") or "—",
                    "Ponto": row.get("point") if row.get("point") is not None else "—",
                }
                for row in batch_rows
            ],
            use_container_width=True,
            hide_index=True,
        )
    return pressed


def render_review_panel(
    *,
    checklist: Optional[Sequence[Mapping[str, Any]]] = None,
    review_stale: bool = False,
    signature_stale: bool = False,
    fingerprint: Optional[str] = None,
    requires_distinct_reviewer: bool = False,
) -> dict:
    """Checklist from the selected profile's requirements. Bound to fingerprint."""
    st.markdown("#### Revisão profissional para emissão")
    st.caption(
        "Checklist gerado dos requisitos do perfil selecionado. "
        "A campanha não assina em nome do usuário. Consentimento antigo não é reutilizado."
    )
    if review_stale or signature_stale:
        st.warning(
            "Houve mudança material. A revisão/assinatura anterior permanece no histórico "
            "e não autoriza a emissão atual."
        )
    if fingerprint:
        st.caption(f"Fingerprint desta versão: {fingerprint[:16]}…")
    pressed = {
        "decision": None,
        "professional_id": "",
        "reviewer_id": "",
        "motive": "",
        "export_for_external_signer": False,
        "import_signed": False,
        "item_evidence": {},
        "signed_file": None,
    }
    items = list(checklist or [])
    item_evidence: dict = {}
    if items:
        for item in items:
            req_id = str(item.get("requirement_id") or item.get("label") or "item")
            st.markdown(f"- **{item.get('label') or req_id}** — {item.get('status') or 'pending'}")
            evidence = st.text_input(
                f"Evidência de «{item.get('label') or req_id}»",
                value=item.get("evidence") or "",
                key=f"c02_evidence_{req_id}",
                help="Evidência específica deste requisito. Vazio permanece pendente — não é atestado.",
            )
            item_evidence[req_id] = evidence
    else:
        st.caption("Nenhum item de checklist — perfil sem requisitos locais ou ainda não selecionado.")
    pressed["item_evidence"] = item_evidence
    pressed["professional_id"] = st.text_input("Profissional responsável pela decisão", value="", key="c02_review_prof")
    if requires_distinct_reviewer:
        pressed["reviewer_id"] = st.text_input("Revisor distinto", value="", key="c02_review_other")
    pressed["motive"] = st.text_area("Motivo da decisão", value="", key="c02_review_motive")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("Registrar revisão (não assina o laudo)"):
            pressed["decision"] = "reviewed"
    with col_b:
        pressed["export_for_external_signer"] = st.button("Exportar para assinador externo")
    with col_c:
        pressed["import_signed"] = st.button("Verificar arquivo assinado importado")
    pressed["signed_file"] = st.file_uploader(
        "Arquivo assinado original",
        type=["pdf", "json"],
        key="c02_signed_import",
        help="Importe o arquivo original assinado fora do produto. A campanha não assina em nome do usuário.",
    )
    st.caption("Assinatura/autoria não valida o conteúdo técnico. O produto não assina em nome do usuário.")
    return pressed


def render_recipient_panel(
    *,
    profile: Optional[Mapping[str, Any]] = None,
    submissions: Optional[Sequence[Mapping[str, Any]]] = None,
) -> dict:
    """Export/return records. No simulated bank/insurer portal."""
    st.markdown("#### Destinatário e retorno institucional")
    profile = profile or {}
    st.caption(
        f"Destinatário: {profile.get('recipient_id') or 'não informado'}. "
        "Não há envio automático a portal de banco/seguradora. "
        "HTTP 200 local não é aceite institucional."
    )
    if profile.get("purpose") == "seguro":
        st.info(
            f"Base de valor requerida: {profile.get('required_value_basis') or profile.get('value_basis')}. "
            "Método de custo é da C01; esta tela não converte mercado em custo."
        )
    pressed = {
        "export_package": False,
        "import_return": False,
        "simulate_send": False,
    }
    pressed["export_package"] = st.button("Preparar pacote de exportação do perfil")
    uploaded = st.file_uploader(
        "Importar comprovante de retorno institucional (arquivo original)",
        type=["pdf", "json", "txt"],
        key="c02_institution_return",
        help="Comprovante importado pelo profissional. Sem credenciais embutidas e sem portal simulado.",
    )
    if uploaded is not None:
        pressed["import_return"] = True
        pressed["imported_file"] = uploaded
    if submissions:
        st.markdown("Histórico de submissão/retorno (registros, não aceite fabricado):")
        for event in submissions:
            st.write({
                "evento": event.get("event"),
                "destinatário": event.get("recipient_id"),
                "aceite": False if not event.get("institution_acceptance") else True,
                "http_local_nao_e_aceite": event.get("local_http_200_is_not_acceptance"),
            })
    return pressed


def render_issuance_history(events: Optional[Sequence[Mapping[str, Any]]] = None) -> None:
    st.markdown("#### Histórico de emissão e revisões")
    if not events:
        st.caption("Nenhuma emissão registrada neste projeto.")
        return
    for event in events:
        stale = " (invalidada)" if event.get("stale") else ""
        st.write(f"{event.get('decision') or event.get('event') or 'evento'}{stale} — {event.get('professional_id') or ''}")
        st.caption(redact_diagnostic(str(event.get("motive") or event.get("invalidated_reason") or "")))
