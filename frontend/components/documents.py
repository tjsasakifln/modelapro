"""Persistent C03 document workflow; UI never grants qualification or signature status."""
from __future__ import annotations

import json
from typing import Mapping

import streamlit as st

from .forms import ApiConnectionError, ApiResponseError, JobClient


def render_document_workflow(client: JobClient, snapshot: Mapping | None) -> dict:
    st.markdown("#### Conteúdo do laudo, revisão e assinatura")
    if not client.job_id or snapshot is None:
        st.info("Calcule ou reabra um trabalho para preparar os documentos.")
        return {}
    st.caption("As decisões são persistidas no trabalho e vinculadas ao cálculo e ao conteúdo. Nenhum ato institucional é executado aqui.")
    namespace = f"documents_{client.job_id}"
    try:
        status = client.documents()
        state = status.get("state") or status
        st.write("Estado documental:", state.get("case_release_status") or state.get("document_state") or "Ainda não preparado")
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
            authorized = st.checkbox("Tenho autorização para incluir estes bytes no laudo e dossiê", key=f"{namespace}_authorized")
            if st.form_submit_button("Anexar arquivo autorizado"):
                if attachment is None or not authorized or not source.strip():
                    st.warning("Informe arquivo, procedência e autorização. Não inclua materiais protegidos sem direito de uso.")
                else:
                    stored = client.documents("/attachments", method="POST",
                                              files={"file": (attachment.name, attachment.getvalue())},
                                              data={"source": source, "category": category, "description": description,
                                                    "authorized_for_report": "true",
                                                    "requirement_ids": json.dumps(requirement_ids)})
                    st.session_state.pop(f"{namespace}_signing_request", None)
                    st.json(stored)
                    st.info("Bytes arquivados com hash. Gere novamente os documentos para incorporar o conteúdo e revalidar revisões.")
        with st.expander("Completar conteúdo e anexos do laudo"), st.form(f"{namespace}_content_form"):
            fields = {}
            for key, label in (
                ("asset_identification", "Identificação do bem"),
                ("region_characterization", "Caracterização da região"),
                ("property_characterization", "Caracterização do imóvel"),
                ("methodology_justification", "Justificativa do método"),
                ("assumptions", "Pressupostos, ressalvas e limitações"),
            ):
                fields[key] = st.text_area(label, value=str(context.get(key) or ""), key=f"{namespace}_{key}")
            st.caption("Arquivos integrais são incorporados pelo registro de anexos acima. Evidências estruturadas não substituem seus bytes.")
            documentary_json = st.text_area(
                "Evidências de requisitos de saída (JSON)",
                value=json.dumps({"output_evidence": context.get("output_evidence") or {}}, ensure_ascii=False, indent=2),
                key=f"{namespace}_evidence",
            )
            if st.form_submit_button("Gerar PDF, DOCX e dossiê"):
                evidence = json.loads(documentary_json)
                if not isinstance(evidence, dict) or set(evidence) - {"output_evidence"}:
                    raise ValueError("Use somente output_evidence no objeto JSON; arquivos são enviados pelo registro de anexos.")
                state = client.documents(method="POST", json={"report_context": {**fields, **evidence}})
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
                st.info("Verificação concluída pelo serviço. Consulte o resultado; integridade não é aprovação técnica.")
        st.json(state)
        for artifact in state.get("artifacts") or []:
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
