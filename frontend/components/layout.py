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
    TERMINAL_JOB_STATES,
    may_start_execution,
)

WORK_FLOW_HEADINGS = [
    "1. Importar e revisar interpretação",
    "2. Definir papéis, unidades e alvo",
    "3. Informar o avaliando",
    "4. Executar",
    "5. Revisar valor, faixas e pendências",
    "6. Salvar, reabrir e evidências",
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

ISSUANCE_LABELS = {
    "draft": "Rascunho",
    "review_required": "Revisão profissional necessária",
    "ready_for_professional_review": "Pronto para revisão profissional",
}

JOB_STATE_LABELS = {
    "queued": "Na fila",
    "running": "Em execução",
    "succeeded": "Cálculo concluído",
    "failed": "Falha",
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
) -> dict:
    """Modelo de apresentação do ResultSnapshot. Testável sem Streamlit."""
    compact = viewport_width is not None and viewport_width < 768
    headings = [
        "Valor da avaliação",
        "Faixas e intervalos",
        "Fundamentação e precisão",
        "Pendências para revisão profissional",
    ]
    if not snapshot:
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
            "primary_language": "pt-BR",
            "internal_keys_exposed": False,
            "next_actions": [],
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
        intervals.append({
            "key": key,
            "label": label,
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

    return {
        "empty": False,
        "headings": headings,
        "value_block": value_block,
        "intervals": intervals,
        "precisao": precisao_view,
        "fundamentacao": {
            "grade": fundamentacao.get("grade"),
            "points": fundamentacao.get("points"),
            "items": list(fundamentacao.get("items") or []),
        },
        "issuance": {
            "status": issuance.get("status"),
            "label": ISSUANCE_LABELS.get(issuance.get("status"), issuance.get("status") or "não informado"),
            "reasons": list(issuance.get("reasons") or []),
        },
        "issues": issues,
        "issues_count": len(issues),
        "warnings_visible": True,
        "next_actions": actions_view,
        "sample": {
            **sample,
            "used_row_ids_display": used_display,
            "table_truncated": truncated,
            "used_row_ids_total": len(used_ids),
        },
        "model": model,
        "search": search,
        "alternatives": alternatives,
        "diagnostics_available": bool(
            model.get("diagnostics") or model.get("coefficients") or model.get("formula")
        ),
        "norma_banner": None,
        "compact": compact,
        "primary_language": "pt-BR",
        "internal_keys_exposed": False,
        "statistical": dict(validation.get("statistical") or {}),
        "documentary": dict(validation.get("documentary") or {}),
        "provenance": dict(snapshot.get("provenance") or {}),
        "job_id": snapshot.get("job_id"),
        "project_id": snapshot.get("project_id"),
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
    blob = json.dumps(
        {k: view.get(k) for k in ("headings", "norma_banner", "issuance", "precisao", "value_block")},
        ensure_ascii=False,
        default=str,
    ).lower()
    return NORMA_BANNER_FORBIDDEN in blob


def load_css() -> None:
    css_path = os.path.join(os.path.dirname(__file__), "..", "assets", "styles.css")
    if os.path.exists(css_path):
        with open(css_path, "r", encoding="utf-8") as handle:
            st.markdown(f"<style>{handle.read()}</style>", unsafe_allow_html=True)


def header() -> None:
    st.title("MODELA PRO")
    st.markdown(
        '<p class="mp-subtitle">Avaliação imobiliária — do arquivo ao valor para revisão profissional</p>',
        unsafe_allow_html=True,
    )


def sidebar() -> dict:
    with st.sidebar:
        st.header("Trabalho")
        st.caption("Painel progressivo. Use Tab e as setas nos controles.")
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
        project_id = st.text_input("Projeto (C11)", value="")
        return {
            "visual_fixture": visual_fixture,
            "api_url": api_url,
            "reopen_job": reopen_job.strip() or None,
            "project_id": project_id.strip() or None,
        }


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
    st.subheader("5. Revisar valor, faixas e pendências")
    if fixture:
        st.warning(FIXTURE_SCREEN_NOTICE)

    if view.get("empty"):
        st.info("Ainda não há resultado para revisar.")
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

    if view.get("compact"):
        st.markdown(f"**Fundamentação:** grau {fundamentacao.get('grade') if fundamentacao.get('grade') is not None else 'não classificado'}")
        st.markdown(f"**Precisão:** {precisao.get('label')} (grau {precisao.get('grade') if precisao.get('grade') is not None else '—'})")
        st.markdown(f"**Situação para revisão:** {issuance.get('label')}")
    else:
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            grade = fundamentacao.get("grade")
            st.metric("Fundamentação", f"Grau {grade}" if grade is not None else "Não classificada")
        with col_b:
            st.metric("Precisão", precisao.get("label") or "Não calculada")
            if precisao.get("grade") is not None:
                st.caption(f"Grau de precisão: {precisao['grade']}")
        with col_c:
            st.metric("Revisão profissional", issuance.get("label") or "não informado")

    for reason in issuance.get("reasons") or []:
        st.info(reason)

    st.markdown("#### Faixas e intervalos")
    interval_rows = [
        {
            "Intervalo": item["label"],
            "Inferior": item["lower_display"],
            "Superior": item["upper_display"],
        }
        for item in view.get("intervals") or []
    ]
    st.dataframe(interval_rows, use_container_width=True, hide_index=True)

    st.markdown("#### Pendências e avisos")
    issues = list(view.get("issues") or [])
    if not issues:
        st.caption("Nenhum aviso estruturado no resultado.")
    for issue in issues:
        text = _issue_text(issue)
        severity = (issue or {}).get("severity") if isinstance(issue, Mapping) else "warning"
        if severity == "error":
            st.error(text)
        elif severity == "info":
            st.info(text)
        else:
            st.warning(text)
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
        if model.get("coefficients"):
            st.write(model.get("coefficients"))
        if model.get("diagnostics"):
            st.write(model.get("diagnostics"))
        if not view.get("diagnostics_available"):
            st.caption("Diagnósticos não vieram neste resultado.")
        statistical = view.get("statistical") or {}
        if statistical:
            st.write(statistical)

    with st.expander("Busca, alternativas e ressalvas", expanded=False):
        search = view.get("search") or {}
        if search:
            st.write(search)
        alternatives = view.get("alternatives") or []
        if alternatives:
            st.write(alternatives)
        else:
            st.caption("Nenhuma alternativa listada neste resultado.")


def render_job_panel(view: Mapping[str, Any]) -> dict:
    st.subheader("4. Executar")
    if view.get("job_id"):
        st.caption(f"Identificador do trabalho: {view['job_id']}")
    st.write(f"Estado: **{view.get('state_label')}**")
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
        "O disparo está no passo 3, junto do avaliando, para enviar os valores preenchidos."
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
) -> dict:
    st.subheader("6. Salvar, reabrir e evidências")
    pressed = {"save": False, "download_calc": False, "download_named": None}

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
