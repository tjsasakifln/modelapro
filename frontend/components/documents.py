"""Persistent C03 document workflow; UI never grants qualification or signature status."""
from __future__ import annotations

import json
from typing import Any, Mapping

import streamlit as st

from .forms import (
    ApiConnectionError,
    ApiResponseError,
    JobClient,
    _context_text,
    _restore_text_shape,
    render_professional_report_fields,
    render_sample_evidence_column_mapping,
)


def _document_sample_rows(context: Mapping[str, Any]) -> list[dict]:
    rows = []
    seen = set()
    for field in ("used_rows", "excluded_rows"):
        value = context.get(field) or []
        if not isinstance(value, list):
            continue
        for raw in value:
            if not isinstance(raw, Mapping) or raw.get("row_id") is None:
                continue
            row_id = str(raw["row_id"])
            if row_id in seen:
                continue
            seen.add(row_id)
            rows.append(dict(raw))
    evidence = context.get("sample_evidence") or {}
    if isinstance(evidence, Mapping):
        for row_id in evidence:
            if str(row_id) not in seen:
                rows.append({"row_id": str(row_id), "values": {}})
                seen.add(str(row_id))
    return rows


def _document_column_map(context: Mapping[str, Any], sample_rows: list[dict]) -> dict:
    names = set()
    for row in sample_rows:
        values = row.get("values") or {}
        if isinstance(values, Mapping):
            names.update(str(name) for name in values)
    existing = context.get("sample_evidence_columns") or {}
    if isinstance(existing, Mapping):
        names.update(str(name) for name in existing.values() if name)
    return {name: {"original_name": name} for name in sorted(names)}


def _document_variables(client: JobClient, context: Mapping[str, Any]) -> list[str]:
    spec = client.last_request_spec or {}
    roles = spec.get("roles") or {}
    candidates = spec.get("candidate_cols")
    if isinstance(candidates, list):
        names = [
            str(name) for name in candidates
            if not roles or roles.get(name) in (None, "predictor")
        ]
    else:
        names = [str(name) for name, role in roles.items() if role == "predictor"]
    if not names:
        classification = context.get("variable_classification") or {}
        if isinstance(classification, Mapping):
            names = [str(name) for name in classification]
    documentary = context.get("sample_evidence_columns") or {}
    excluded = set(documentary.values()) if isinstance(documentary, Mapping) else set()
    return [name for name in names if name not in excluded]


def _render_general_report_fields(namespace: str, context: Mapping[str, Any]) -> dict:
    fields = {}
    for key, label in (
        ("asset_identification", "Identificação do bem"),
        ("region_characterization", "Caracterização da região"),
        ("property_characterization", "Caracterização do imóvel"),
        ("methodology_justification", "Justificativa do método"),
        ("assumptions", "Pressupostos, ressalvas e limitações"),
    ):
        original = context.get(key)
        if isinstance(original, Mapping):
            display = "\n".join(
                f"{name}: {_context_text(value)}"
                for name, value in original.items()
                if _context_text(value)
            )
            edited = st.text_area(label, value=display, key=f"{namespace}_{key}")
            fields[key] = dict(original) if edited == display else edited.strip() or None
            st.caption(f"{label}: a estrutura vinculada é preservada enquanto o texto não for alterado.")
            continue
        edited = st.text_area(
            label,
            value=_context_text(original),
            key=f"{namespace}_{key}",
        )
        fields[key] = _restore_text_shape(edited, original)
    return fields


def render_document_workflow(client: JobClient, snapshot: Mapping | None) -> dict:
    st.markdown("#### Conteúdo do laudo, revisão e assinatura")
    if not client.job_id or snapshot is None:
        st.info("Calcule ou reabra um trabalho para preparar os documentos.")
        return {}
    dossier_state = (
        ((client.last_status or {}).get("artifact_states") or {}).get("evidence_bundle.zip")
        or {}
    )
    if dossier_state.get("state") in {"pending", "running"}:
        st.info("O cálculo está disponível; a preparação do dossiê ainda está em andamento. Use Atualizar estado.")
        return {}
    st.caption(
        "As decisões são persistidas no trabalho e vinculadas ao cálculo e ao conteúdo. "
        "Nenhum ato institucional é executado aqui."
    )
    namespace = f"documents_{client.job_id}"
    try:
        status = client.documents()
        state = status.get("state") or status
        st.write(
            "Estado documental:",
            state.get("case_release_status")
            or state.get("document_state")
            or "Ainda não preparado",
        )
        context = json.loads(client.get_artifact("report_context.json"))
        with st.expander("Arquivos integrais e procedência"), st.form(f"{namespace}_attachment_form"):
            attachment = st.file_uploader("Documento ou anexo integral", key=f"{namespace}_attachment")
            category = st.selectbox("Categoria do arquivo", ["document", "annex"], key=f"{namespace}_category")
            source = st.text_input("Fonte e autorização de acesso ao arquivo", key=f"{namespace}_source")
            description = st.text_input("Descrição do documento/anexo", key=f"{namespace}_description")
            from modules.qualification_profile import resolve_profile
            profile_ref = ((snapshot.get("provenance") or {}).get("qualification_context") or {}).get("profile") or {}
            profile = resolve_profile(profile_ref)
            requirement_ids = st.multiselect("Requisitos comprovados pelo arquivo",
                                             options=[item["id"] for item in profile.get("requirements") or []],
                                             key=f"{namespace}_requirements")
            authorized = st.checkbox(
                "Tenho autorização para incluir estes bytes no laudo e dossiê",
                key=f"{namespace}_authorized",
            )
            if st.form_submit_button("Anexar arquivo autorizado"):
                if attachment is None or not authorized or not source.strip():
                    st.warning(
                        "Informe arquivo, procedência e autorização. "
                        "Não inclua materiais protegidos sem direito de uso."
                    )
                else:
                    stored = client.documents("/attachments", method="POST",
                                              files={"file": (attachment.name, attachment.getvalue())},
                                              data={"source": source, "category": category, "description": description,
                                                    "authorized_for_report": "true",
                                                    "requirement_ids": json.dumps(requirement_ids)})
                    st.session_state.pop(f"{namespace}_signing_request", None)
                    client.get_result()
                    st.json(stored)
                    st.info(
                        "Bytes arquivados com hash. Gere novamente os documentos para "
                        "incorporar o conteúdo e revalidar revisões."
                    )
        with st.expander("Completar conteúdo e anexos do laudo"), st.form(f"{namespace}_content_form"):
            fields = _render_general_report_fields(namespace, context)
            sample_rows = _document_sample_rows(context)
            column_map = _document_column_map(context, sample_rows)
            st.markdown("##### Colunas documentais da amostra")
            sample_columns, mapping_errors = render_sample_evidence_column_mapping(
                namespace=namespace,
                column_map=column_map,
                context=context,
                excluded_columns=[str(context.get("target_col") or "")],
            )
            professional_fields, field_errors = render_professional_report_fields(
                namespace=f"{namespace}_report",
                variable_names=_document_variables(
                    client, {**context, "sample_evidence_columns": sample_columns}
                ),
                sample_rows=sample_rows,
                context=context,
                sample_evidence_columns=sample_columns,
                include_professional_identity=True,
            )
            fields.update(professional_fields)
            all_errors = [*mapping_errors, *field_errors]
            for message in all_errors:
                st.error(message)
            st.caption(
                "Arquivos integrais são incorporados pelo registro de anexos acima. "
                "Os campos humanos desta tela não fabricam evidência nem aprovação."
            )
            if st.form_submit_button("Gerar PDF, DOCX e dossiê"):
                if all_errors:
                    raise ValueError("Corrija os campos do laudo antes de gerar os documentos.")
                state = client.documents(method="POST", json={"report_context": fields})
                st.session_state.pop(f"{namespace}_signing_request", None)
                client.get_result()
                st.info("Documentos gerados; consulte as pendências. Geração não é aprovação.")
        professional_id = st.text_input("Profissional responsável pela decisão", key=f"{namespace}_professional")
        motive = st.text_area("Motivo e evidências da revisão", key=f"{namespace}_motive")
        revision = st.text_input("Identificador da revisão documental", key=f"{namespace}_revision")
        if st.button("Registrar revisão (não assina o laudo)", key=f"{namespace}_review"):
            state = client.documents("/review", method="POST", json={
                "professional_id": professional_id, "motive": motive, "version": revision,
            })
            st.session_state.pop(f"{namespace}_signing_request", None)
            client.get_result()
            st.info("Revisão registrada pelo serviço; decisões e pendências permanecem no histórico.")
        if st.button("Exportar para assinador externo", key=f"{namespace}_export"):
            request = client.documents("/signature-request", method="POST", json={"revision_id": revision})
            st.session_state[f"{namespace}_signing_request"] = request
        if st.session_state.get(f"{namespace}_signing_request"):
            st.download_button("Baixar vínculo de assinatura", json.dumps(
                st.session_state[f"{namespace}_signing_request"], ensure_ascii=False, indent=2),
                "signature_request.json", "application/json")
            st.download_button("Baixar os bytes PDF para assinatura", client.get_artifact("report.pdf"),
                               "report.pdf", "application/pdf")
            st.caption("Assine estes bytes fora do produto e importe o PDF original. Não forneça chave privada.")
        signed = st.file_uploader("Arquivo PDF assinado original", type=["pdf"], key=f"{namespace}_signed")
        if st.button("Verificar arquivo assinado importado", key=f"{namespace}_verify"):
            if signed is None:
                st.warning("Selecione o PDF assinado original.")
            else:
                state = client.documents("/signature", method="POST", files={
                    "file": (signed.name, signed.getvalue(), "application/pdf"),
                })
                client.get_result()
                st.info(
                    "Verificação concluída pelo serviço. Consulte o resultado; "
                    "integridade não é aprovação técnica."
                )
        st.json(state)
        artifact_names = set(status.get("artifacts") or {}) | set(state.get("artifacts") or {})
        for artifact in sorted(artifact_names):
            name = artifact.get("name") if isinstance(artifact, dict) else str(artifact)
            if name and st.button(f"Preparar download: {name}", key=f"{namespace}_prepare_{name}"):
                st.download_button(f"Baixar {name}", client.get_artifact(name), name,
                                   key=f"{namespace}_download_{name}")
        return state
    except (ApiConnectionError, ApiResponseError, ValueError) as exc:
        st.error(str(exc))
        if isinstance(exc, ApiResponseError) and getattr(exc, "payload", None):
            st.json(exc.payload)
        return {}
