"""Entrada Streamlit da avaliação (campanha P02).

Fluxo: preparação da amostra → imóvel avaliando → resultado e revisão
→ projeto salvo.

O resultado é recuperado por GET /jobs/{id}; o WebSocket é notificação
opcional e nunca a única via. Importável em testes sem disparar a UI.
"""

from __future__ import annotations

import json
import os
from typing import Optional


def _import_components():
    try:
        from components.cost import cost_form
        from components.documents import render_document_workflow
        from components.charts import render_charts, render_snapshot_charts
        from components.forms import (
            DEFAULT_API_URL,
            DEFAULT_TIMEOUT,
            PREVIEW_CONNECTION_ERROR,
            ApiConnectionError,
            ApiResponseError,
            DuplicateExecutionError,
            JobClient,
            persist_client_to_session,
            restore_client_from_session,
            upload_form,
        )
        from components.layout import (
            FIXTURE_SCREEN_NOTICE,
            WORK_FLOW_HEADINGS,
            header,
            load_css,
            load_visual_fixture,
            present_artifacts,
            present_job_status,
            present_snapshot,
            render_artifact_panel,
            render_issuance_history,
            render_job_panel,
            render_project_panel,
            render_recipient_panel,
            render_review_panel,
            render_snapshot_panel,
            sidebar,
        )
        from components.professional import (
            build_profile_checklist,
            declared_fingerprint_from_imported,
            export_recipient_package_manifest,
            gate_ready_for_professional_signoff,
            invalidate_review_events,
            record_institution_submission,
            record_review_event,
            redact_diagnostic,
            verify_imported_signature_link,
        )
        from components.workflow import (
            apply_invalidation,
            merge_invalidation,
            present_batch_items,
            present_delivery_state,
            revision_recovery_plan,
            should_block_duplicate_submit,
        )
        return locals()
    except ImportError:
        from frontend.components.cost import cost_form
        from frontend.components.documents import render_document_workflow
        from frontend.components.charts import render_charts, render_snapshot_charts
        from frontend.components.forms import (
            DEFAULT_API_URL,
            DEFAULT_TIMEOUT,
            PREVIEW_CONNECTION_ERROR,
            ApiConnectionError,
            ApiResponseError,
            DuplicateExecutionError,
            JobClient,
            persist_client_to_session,
            restore_client_from_session,
            upload_form,
        )
        from frontend.components.layout import (
            FIXTURE_SCREEN_NOTICE,
            WORK_FLOW_HEADINGS,
            header,
            load_css,
            load_visual_fixture,
            present_artifacts,
            present_job_status,
            present_snapshot,
            render_artifact_panel,
            render_issuance_history,
            render_job_panel,
            render_project_panel,
            render_recipient_panel,
            render_review_panel,
            render_snapshot_panel,
            sidebar,
        )
        from frontend.components.professional import (
            build_profile_checklist,
            declared_fingerprint_from_imported,
            export_recipient_package_manifest,
            gate_ready_for_professional_signoff,
            invalidate_review_events,
            record_institution_submission,
            record_review_event,
            redact_diagnostic,
            verify_imported_signature_link,
        )
        from frontend.components.workflow import (
            apply_invalidation,
            merge_invalidation,
            present_batch_items,
            present_delivery_state,
            revision_recovery_plan,
            should_block_duplicate_submit,
        )
        return locals()


_COMP = _import_components()
DEFAULT_API_URL = _COMP["DEFAULT_API_URL"]
DEFAULT_TIMEOUT = _COMP["DEFAULT_TIMEOUT"]
PREVIEW_CONNECTION_ERROR = _COMP["PREVIEW_CONNECTION_ERROR"]
ApiConnectionError = _COMP["ApiConnectionError"]
ApiResponseError = _COMP["ApiResponseError"]
DuplicateExecutionError = _COMP["DuplicateExecutionError"]
JobClient = _COMP["JobClient"]
persist_client_to_session = _COMP["persist_client_to_session"]
restore_client_from_session = _COMP["restore_client_from_session"]
upload_form = _COMP["upload_form"]
FIXTURE_SCREEN_NOTICE = _COMP["FIXTURE_SCREEN_NOTICE"]
WORK_FLOW_HEADINGS = _COMP["WORK_FLOW_HEADINGS"]
header = _COMP["header"]
load_css = _COMP["load_css"]
load_visual_fixture = _COMP["load_visual_fixture"]
present_artifacts = _COMP["present_artifacts"]
present_job_status = _COMP["present_job_status"]
present_snapshot = _COMP["present_snapshot"]
render_artifact_panel = _COMP["render_artifact_panel"]
render_issuance_history = _COMP["render_issuance_history"]
render_job_panel = _COMP["render_job_panel"]
render_project_panel = _COMP["render_project_panel"]
render_recipient_panel = _COMP["render_recipient_panel"]
render_review_panel = _COMP["render_review_panel"]
render_snapshot_panel = _COMP["render_snapshot_panel"]
sidebar = _COMP["sidebar"]
build_profile_checklist = _COMP["build_profile_checklist"]
declared_fingerprint_from_imported = _COMP["declared_fingerprint_from_imported"]
export_recipient_package_manifest = _COMP["export_recipient_package_manifest"]
gate_ready_for_professional_signoff = _COMP["gate_ready_for_professional_signoff"]
invalidate_review_events = _COMP["invalidate_review_events"]
record_institution_submission = _COMP["record_institution_submission"]
record_review_event = _COMP["record_review_event"]
redact_diagnostic = _COMP["redact_diagnostic"]
verify_imported_signature_link = _COMP["verify_imported_signature_link"]
apply_invalidation = _COMP["apply_invalidation"]
merge_invalidation = _COMP["merge_invalidation"]
render_charts = _COMP["render_charts"]
render_snapshot_charts = _COMP["render_snapshot_charts"]
present_batch_items = _COMP["present_batch_items"]
present_delivery_state = _COMP["present_delivery_state"]
revision_recovery_plan = _COMP["revision_recovery_plan"]
should_block_duplicate_submit = _COMP["should_block_duplicate_submit"]


def _should_run_ui() -> bool:
    if __name__ == "__main__":
        return True
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


def _preview_provider_for(client: JobClient):
    def _preview(file_bytes, filename, request_spec, subject=None):
        return client.preview(file_bytes, filename, request_spec, subject=subject)
    return _preview


def _maybe_listen_websocket(job_id: str, ws_url: str, access_token: Optional[str] = None) -> dict:
    """Notificação opcional. Falha aqui NÃO descarta job_id nem substitui o GET."""
    if os.environ.get("MODELA_DISABLE_WS", "").lower() in {"1", "true", "yes"}:
        return {"status": "disabled", "fallback": "GET"}
    from urllib.parse import urlsplit
    destination = urlsplit(ws_url)
    if destination.scheme != "ws" or destination.hostname not in {"localhost", "127.0.0.1", "::1"} or destination.query:
        return {"status": "rejected_destination", "fallback": "GET"}
    if not access_token:
        return {"status": "missing_job_token", "fallback": "GET"}
    try:
        import asyncio
        import websockets
    except ImportError:
        return {"status": "unavailable", "fallback": "GET"}

    async def _once():
        try:
            from modules.operacao_local.runtime import local_client_headers
            async with websockets.connect(ws_url, additional_headers=local_client_headers(),
                                          max_size=10 * 1024 * 1024, open_timeout=2) as websocket:
                await websocket.send(json.dumps({"job_id": job_id, "token": access_token}))
                event = json.loads(await asyncio.wait_for(websocket.recv(), timeout=1.0))
                if event.get("job_id") != job_id or event.get("status") == "error":
                    return {"status": "rejected_job", "fallback": "GET"}
                return {"status": "connected", "job_id": job_id}
        except (OSError, TimeoutError, ValueError, websockets.exceptions.WebSocketException):
            return {"status": "connection_failed", "fallback": "GET"}

    try:
        return asyncio.run(_once())
    except RuntimeError:
        return {"status": "event_loop_unavailable", "fallback": "GET"}


def main() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="MODELA PRO — avaliação para revisão profissional",
        page_icon="🏢",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    load_css()
    header()
    side = sidebar()

    api_url = side.get("api_url") or DEFAULT_API_URL
    timeout = DEFAULT_TIMEOUT
    client: JobClient = restore_client_from_session(
        st.session_state,
        base_url=api_url,
        timeout=timeout,
    )

    if "c09_status_message" not in st.session_state:
        st.session_state.c09_status_message = ""

    if side.get("reopen_job") and side["reopen_job"] != client.job_id:
        try:
            client.recover(side["reopen_job"])
            persist_client_to_session(st.session_state, client)
            st.success(f"Trabalho {client.job_id} retomado pelo identificador.")
        except ApiConnectionError as exc:
            st.error(str(exc))
            st.session_state["c09_job_id"] = side["reopen_job"]
            client.job_id = side["reopen_job"]
        except ApiResponseError as exc:
            st.error(str(exc))
            st.session_state["c09_job_id"] = side["reopen_job"]
            client.job_id = side["reopen_job"]

    fixture_mode = bool(side.get("visual_fixture"))
    if fixture_mode:
        st.warning(FIXTURE_SCREEN_NOTICE)
        fixture = load_visual_fixture()
        view = present_snapshot(fixture, viewport_width=720)
        render_snapshot_panel(view, fixture=True)
        render_snapshot_charts(fixture)
        st.caption(FIXTURE_SCREEN_NOTICE)
        persist_client_to_session(st.session_state, client)
        return

    cost_mode = st.radio("Percurso de cálculo", ["Amostra de mercado", "Quantificação de custo"],
                         horizontal=True, key="c06_calculation_path") == "Quantificação de custo"
    form = _COMP["cost_form"]() if cost_mode else upload_form(preview_provider=_preview_provider_for(client))
    persist_client_to_session(st.session_state, client)
    if form.get("stale_reason"):
        st.session_state["p02_result_stale_reason"] = form["stale_reason"]
    current_fp = form.get("fingerprint")
    last_fp = st.session_state.get("p02_form_fingerprint")
    if current_fp and last_fp and current_fp != last_fp:
        change = "subject"
        if form.get("stale_reason") and "arquivo" in str(form.get("stale_reason")).lower():
            change = "file"
        flags, dropped = merge_invalidation(dict(st.session_state), change)
        for key, value in flags.items():
            st.session_state[key] = value
        for key in dropped:
            st.session_state.pop(key, None)
    if current_fp:
        st.session_state["p02_form_fingerprint"] = current_fp

    job_view = present_job_status(client.last_status if client.last_status else {
        "job_id": client.job_id,
        "state": None,
        "result_available": client.last_snapshot is not None,
    })
    if client.job_id and not job_view.get("job_id"):
        job_view["job_id"] = client.job_id

    actions = render_job_panel(job_view)
    if form.get("execute"):
        actions["execute"] = True

    if actions.get("refresh") and client.job_id:
        try:
            client.recover(client.job_id)
            persist_client_to_session(st.session_state, client)
        except ApiConnectionError as exc:
            st.error(str(exc))
            st.info(f"Identificador preservado: {client.job_id}")
        except ApiResponseError as exc:
            st.error(str(exc))
            st.info(f"Identificador preservado: {client.job_id}")

    if actions.get("cancel") and client.job_id:
        try:
            client.cancel(client.job_id)
            client.recover(client.job_id)
            persist_client_to_session(st.session_state, client)
            st.warning("Cancelamento solicitado.")
        except (ApiConnectionError, ApiResponseError) as exc:
            st.error(str(exc))
            st.info(f"Identificador preservado: {client.job_id}")

    if actions.get("execute"):
        dispatch = form.get("dispatch") or {"ok": False, "blocking": [{"message": "Formulário incompleto."}]}
        uploaded = form.get("uploaded_file")
        spec = form.get("request_spec")
        subject = form.get("subject")
        if form.get("connection_error"):
            st.error(form["connection_error"])
        elif not dispatch.get("ok"):
            for item in dispatch.get("blocking") or []:
                st.error(item.get("message") or "Disparo recusado.")
        elif (uploaded is None and not form.get("cost_mode")) or spec is None:
            st.error("Arquivo e especificação são necessários para executar.")
        elif should_block_duplicate_submit(
            current_fingerprint=form.get("fingerprint"),
            last_fingerprint=client.last_submit_fingerprint,
            job_status=client.last_status,
            last_job_id=client.job_id,
        ):
            st.info("Pedido equivalente já enviado. Recuperando o trabalho existente, sem novo POST.")
            if client.job_id:
                try:
                    client.recover(client.job_id)
                    persist_client_to_session(st.session_state, client)
                except (ApiConnectionError, ApiResponseError) as exc:
                    st.warning(str(exc))
        else:
            try:
                response = client.submit_job(
                    uploaded.getvalue() if uploaded is not None else None,
                    uploaded.name if uploaded is not None else "",
                    spec,
                    subject=subject,
                    content_type=getattr(uploaded, "type", None) or "application/octet-stream",
                    project_id=side.get("project_id"),
                    input_sha256=(form.get("preview") or {}).get("input_sha256"),
                )
                st.session_state["p02_result_stale"] = False
                st.session_state.pop("p02_result_stale_reason", None)
                st.session_state["p02_last_request_spec"] = spec
                persist_client_to_session(st.session_state, client)
                st.info(f"Trabalho aceito: {response.get('job_id')}. Recuperação pelo identificador, não pelo WebSocket.")
                ws_url = os.environ.get("MODELA_WS_URL", client.base_url.replace("http://", "ws://", 1) + "/ws")
                websocket_state = _maybe_listen_websocket(client.job_id, ws_url, client.access_token)
                if websocket_state.get("status") != "connected":
                    st.caption("Canal de progresso indisponível; estado e resultado serão consultados por GET.")
                try:
                    client.recover(client.job_id)
                except (ApiConnectionError, ApiResponseError) as exc:
                    st.warning(str(exc))
                    st.info(f"Identificador preservado: {client.job_id}. Use Atualizar estado.")
                persist_client_to_session(st.session_state, client)
            except DuplicateExecutionError as exc:
                st.error(str(exc))
            except ApiConnectionError as exc:
                st.error(str(exc))
                if client.job_id:
                    st.info(f"Identificador preservado: {client.job_id}")
            except ApiResponseError as exc:
                st.error(str(exc))
                if client.job_id:
                    st.info(f"Identificador preservado: {client.job_id}")

    if client.job_id and client.last_status is None:
        try:
            client.recover(client.job_id)
            persist_client_to_session(st.session_state, client)
        except (ApiConnectionError, ApiResponseError):
            pass

    snapshot = client.last_snapshot
    if snapshot is None and client.last_status and client.last_status.get("result_available") and client.job_id:
        try:
            snapshot = client.get_result(client.job_id)
            persist_client_to_session(st.session_state, client)
        except (ApiConnectionError, ApiResponseError) as exc:
            st.error(str(exc))

    stale_reason = st.session_state.get("p02_result_stale_reason") if st.session_state.get("p02_result_stale") else None
    view = present_snapshot(
        snapshot,
        viewport_width=1366,
        request_spec=form.get("request_spec") or st.session_state.get("p02_last_request_spec") or client.last_request_spec,
        stale_reason=stale_reason,
    )
    render_snapshot_panel(view, fixture=False)
    if snapshot:
        with st.expander("Gráficos e equação (segundo nível)", expanded=False):
            render_snapshot_charts(snapshot)
            legacy_charts = snapshot.get("charts") or {}
            if legacy_charts and not (snapshot.get("model") or {}).get("charts"):
                render_charts(legacy_charts)
            report_ctx = snapshot.get("report_context")
            if not report_ctx:
                st.caption("Séries gráficas de resíduos/ajustes dependem de P03 (report_context) — indisponíveis neste resultado.")

    artifact_states = (client.last_status or {}).get("artifact_states") or {}
    artifact_view = present_artifacts(artifact_states)
    job_view = present_job_status(client.last_status if client.last_status else {
        "job_id": client.job_id,
        "state": None,
        "result_available": snapshot is not None,
    })
    delivery = present_delivery_state(job_view, artifact_view)
    art_actions = render_artifact_panel(artifact_view, job_view, snapshot=snapshot, delivery=delivery)

    if art_actions.get("download_named") and client.job_id:
        try:
            payload = client.get_artifact(art_actions["download_named"])
            st.download_button(
                f"Transferência de {art_actions['download_named']}",
                data=payload,
                file_name=art_actions["download_named"],
            )
        except (ApiConnectionError, ApiResponseError) as exc:
            st.error(str(exc))

    if "p02_projects" not in st.session_state:
        st.session_state.p02_projects = []
    if "p02_selected_project" not in st.session_state:
        st.session_state.p02_selected_project = None
    if "p02_revisions" not in st.session_state:
        st.session_state.p02_revisions = None
    if "p02_batch_rows" not in st.session_state:
        st.session_state.p02_batch_rows = []
    if "p02_revisions_handoff" not in st.session_state:
        st.session_state.p02_revisions_handoff = None

    project_actions = render_project_panel(
        projects=st.session_state.p02_projects,
        selected_project=st.session_state.p02_selected_project,
        revisions=st.session_state.p02_revisions,
        batch_rows=st.session_state.p02_batch_rows,
        revisions_handoff=st.session_state.p02_revisions_handoff,
    )

    if project_actions.get("refresh_projects"):
        try:
            st.session_state.p02_projects = client.list_projects() or []
        except (ApiConnectionError, ApiResponseError) as exc:
            st.error(str(exc))

    open_id = project_actions.get("open_project_id") or None
    if open_id:
        try:
            loaded = client.get_project(open_id)
            st.session_state.p02_selected_project = loaded
            plan = revision_recovery_plan(loaded)
            st.caption(f"Recuperação canônica via {plan['recover_via']} — não pelo texto da tela.")
            if plan.get("job_id"):
                client.recover(plan["job_id"])
                persist_client_to_session(st.session_state, client)
            revs = client.list_revisions(open_id)
            st.session_state.p02_revisions = revs
            st.session_state.p02_revisions_handoff = revs.get("handoff") if revs.get("list_route_available") is False else None
        except (ApiConnectionError, ApiResponseError) as exc:
            st.error(str(exc))

    open_rev = project_actions.get("open_revision_id") or None
    if open_rev:
        project_id = (
            (st.session_state.p02_selected_project or {}).get("project_id")
            or side.get("project_id")
            or project_actions.get("create_project_id")
        )
        if not project_id:
            st.error("Selecione um projeto antes de reabrir a revisão.")
        else:
            try:
                outcome = client.reopen_revision(
                    project_id,
                    open_rev,
                    st.session_state.p02_revisions,
                )
                if not outcome.get("recovered"):
                    st.info(outcome.get("reason") or "Revisão histórica indisponível nesta BASE_SHA.")
                    if outcome.get("handoff"):
                        st.session_state.p02_revisions_handoff = outcome["handoff"]
                else:
                    st.caption(
                        f"Revisão {outcome.get('revision_id')} recuperada via {outcome.get('via')} "
                        "— não pelo texto da tela."
                    )
                    persist_client_to_session(st.session_state, client)
            except (ApiConnectionError, ApiResponseError) as exc:
                st.error(str(exc))

    save_project_id = side.get("project_id") or project_actions.get("create_project_id")
    if art_actions.get("save"):
        project_id = save_project_id
        if not project_id:
            st.error("Informe o identificador do projeto para salvar a revisão.")
        elif snapshot is None:
            st.error("Não há cálculo para salvar.")
        else:
            try:
                saved = client.save_revision(
                    project_id,
                    {
                        "schema_version": "MP/1",
                        "job_id": client.job_id,
                        "snapshot_ref": {"job_id": client.job_id},
                    },
                )
                st.success(f"Nova revisão registrada: {saved.get('revision_id') or saved} (a anterior permanece).")
                st.session_state.p02_projects = client.list_projects() or st.session_state.p02_projects
            except (ApiConnectionError, ApiResponseError) as exc:
                st.error(str(exc))
                st.caption("A interface não grava uma cópia paralela local do projeto.")

    if project_actions.get("batch_submit"):
        project_id = save_project_id or (
            (st.session_state.p02_selected_project or {}).get("project_id")
        )
        if not project_id:
            st.error("Selecione ou informe um projeto para o lote.")
        else:
            try:
                subjects = json.loads(project_actions.get("batch_subjects_text") or "[]")
            except json.JSONDecodeError:
                st.error("Sujeitos do lote precisam ser um JSON lista.")
                subjects = None
            if isinstance(subjects, list):
                try:
                    batch = client.submit_batch(
                        project_id,
                        {
                            "subjects": subjects,
                            "request_spec": form.get("request_spec") or client.last_request_spec,
                        },
                    )
                    st.info(f"Lote aceito: {batch.get('job_id')}. A consulta de estado é por GET, não por WebSocket.")
                    if batch.get("job_id"):
                        try:
                            recovered = client.recover(batch["job_id"])
                            snap = client.last_snapshot or recovered
                            st.session_state.p02_batch_rows = present_batch_items(snap if isinstance(snap, dict) else {})
                        except (ApiConnectionError, ApiResponseError):
                            st.session_state.p02_batch_rows = present_batch_items({"items": [{"status": "pending", "subject_id": i} for i, _ in enumerate(subjects)]})
                except (ApiConnectionError, ApiResponseError) as exc:
                    st.error(str(exc))

    qualification = ((snapshot or {}).get("provenance") or {}).get("qualification_context") or {}
    # A recovered job is bound to its persisted profile, never to whatever
    # profile happens to be selected in the current form.
    profile = qualification.get("profile") or form.get("qualification_profile") or {}
    document_state = _COMP["render_document_workflow"](client, snapshot)
    current_fp = document_state.get("result_fingerprint") or qualification.get("result_fingerprint")
    stored_events = list(qualification.get("review_events") or [])

    submissions = list(st.session_state.get("c02_institution_events") or [])
    recipient_status = {}
    if client.job_id and profile.get("recipient_id"):
        try:
            recipient_status = client.recipient_return()
        except (ApiConnectionError, ApiResponseError) as exc:
            st.warning(f"Registro persistido de retorno indisponível: {redact_diagnostic(str(exc))}")
    persisted_returns = list(recipient_status.get("records") or [])
    recipient_actions = render_recipient_panel(
        profile=profile, submissions=[*submissions, *persisted_returns]
    )
    if recipient_actions.get("export_package"):
        manifest = export_recipient_package_manifest(
            profile=profile,
            fingerprint=current_fp or "",
            artifact_names=[item.get("name") for item in (artifact_view.get("items") or [])],
        )
        submissions.append(
            record_institution_submission(
                recipient_id=profile.get("recipient_id") or "",
                package_name=manifest["instructions_version"],
                instructions_version=manifest["instructions_version"],
                http_status=None,
                imported_proof=False,
            )
        )
        st.session_state.c02_institution_events = submissions
        st.download_button(
            "Baixar manifesto do pacote do destinatário",
            data=json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="pacote_destinatario.json",
            mime="application/json",
        )
        st.caption("Pacote preparado localmente. Sem envio a portal e sem aceite fabricado.")
    if recipient_actions.get("import_return") and recipient_actions.get("imported_file") is not None:
        imported = recipient_actions["imported_file"]
        st.caption(
            "O registro preserva os bytes e a declaração do operador. Ele não verifica "
            "autenticidade, autoridade do emissor nem aceite institucional."
        )
        protocol = st.text_input("Protocolo informado no retorno")
        received_at = st.text_input(
            "Data/hora de recebimento com fuso (ISO-8601)",
            placeholder="2026-09-12T16:00:00-03:00",
        )
        return_source = st.text_input("Fonte/procedência declarada do comprovante")
        declared_unverified = st.checkbox(
            "Declaro que recebi este documento, sem afirmar autenticidade ou aceite institucional"
        )
        return_is_synthetic = st.checkbox(
            "Este comprovante é material sintético de TESTE",
            value=False,
        )
        authorized_for_report = st.checkbox(
            "Autorizo incorporar os bytes deste comprovante em nova geração do laudo/dossiê",
            value=False,
            help=(
                "Sem esta autorização, o comprovante permanece no arquivo local do caso, "
                "mas seus bytes não entram em nova composição documental."
            ),
        )
        if st.button(
            "Arquivar comprovante como recebido e não verificado",
            disabled=not bool(profile.get("recipient_id")),
        ):
            from modules.report_export.recipient import OPERATOR_DECLARATION

            try:
                stored_return = client.recipient_return(
                    method="POST",
                    files={
                        "file": (
                            imported.name,
                            imported.getvalue(),
                            imported.type or "application/octet-stream",
                        )
                    },
                    data={
                        "recipient_id": profile.get("recipient_id") or "",
                        "protocol": protocol,
                        "received_at": received_at,
                        "source": return_source,
                        "operator_declaration": (
                            OPERATOR_DECLARATION if declared_unverified else ""
                        ),
                        "synthetic_test_only": str(return_is_synthetic).lower(),
                        "authorized_for_report": str(authorized_for_report).lower(),
                    },
                )
                recipient_status = client.recipient_return()
                persisted_returns = list(recipient_status.get("records") or [])
                st.info(
                    "Comprovante arquivado com bytes e SHA-256. Estado: recebido/declarado, "
                    "autenticidade e aceite institucional não verificados."
                )
                st.json(stored_return)
            except (ApiConnectionError, ApiResponseError) as exc:
                st.error(redact_diagnostic(str(exc)))

    latest_return = recipient_status.get("latest") or {}
    if latest_return:
        st.write(
            {
                "retorno_persistido": latest_return.get("status"),
                "destinatário": latest_return.get("recipient_id"),
                "protocolo": latest_return.get("protocol"),
                "sha256": latest_return.get("proof_sha256"),
                "integridade_dos_bytes": latest_return.get("bytes_integrity"),
                "aceite_institucional": False,
            }
        )
        st.caption(
            "Documento recebido/declarado pelo operador; não autenticado e não interpretado como aceite. "
            "A associação à versão efetivamente enviada também não foi verificada."
        )
        if st.button("Preparar download do comprovante arquivado"):
            try:
                st.download_button(
                    "Baixar bytes originais do comprovante",
                    data=client.get_recipient_return_file(latest_return["record_id"]),
                    file_name=latest_return.get("filename") or "recipient-return.bin",
                    mime=latest_return.get("media_type") or "application/octet-stream",
                )
            except (ApiConnectionError, ApiResponseError) as exc:
                st.error(redact_diagnostic(str(exc)))

    history = list(stored_events) + list(submissions) + list(persisted_returns)
    render_issuance_history(history)

    persist_client_to_session(st.session_state, client)


if _should_run_ui():
    main()
