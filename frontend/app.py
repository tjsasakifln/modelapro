"""Entrada Streamlit da avaliação (campanha C09).

Fluxo: importar e revisar interpretação → papéis/unidades/alvo → avaliando
→ executar → revisar valor/faixas/pendências → salvar/reabrir/evidências.

O resultado é recuperado por GET /jobs/{id}; o WebSocket é notificação
opcional e nunca a única via. Importável em testes sem disparar a UI.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

def _import_components():
    try:
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
            validate_dispatch,
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
            render_job_panel,
            render_snapshot_panel,
            sidebar,
        )
        return locals()
    except ImportError:
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
            validate_dispatch,
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
            render_job_panel,
            render_snapshot_panel,
            sidebar,
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
validate_dispatch = _COMP["validate_dispatch"]
FIXTURE_SCREEN_NOTICE = _COMP["FIXTURE_SCREEN_NOTICE"]
WORK_FLOW_HEADINGS = _COMP["WORK_FLOW_HEADINGS"]
header = _COMP["header"]
load_css = _COMP["load_css"]
load_visual_fixture = _COMP["load_visual_fixture"]
present_artifacts = _COMP["present_artifacts"]
present_job_status = _COMP["present_job_status"]
present_snapshot = _COMP["present_snapshot"]
render_artifact_panel = _COMP["render_artifact_panel"]
render_job_panel = _COMP["render_job_panel"]
render_snapshot_panel = _COMP["render_snapshot_panel"]
sidebar = _COMP["sidebar"]
render_charts = _COMP["render_charts"]
render_snapshot_charts = _COMP["render_snapshot_charts"]


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


def _maybe_listen_websocket(job_id: str, ws_url: str) -> None:
    """Notificação opcional. Falha aqui NÃO descarta job_id nem substitui o GET."""
    if os.environ.get("MODELA_DISABLE_WS", "").lower() in {"1", "true", "yes"}:
        return
    try:
        import asyncio
        import websockets
    except ImportError:
        return

    async def _once():
        try:
            async with websockets.connect(ws_url, max_size=10 * 1024 * 1024, open_timeout=2) as websocket:
                await websocket.send(json.dumps({"job_id": job_id}))
                try:
                    await asyncio.wait_for(websocket.recv(), timeout=1.0)
                except Exception:
                    return
        except Exception:
            return

    try:
        asyncio.run(_once())
    except Exception:
        return


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

    form = upload_form(preview_provider=_preview_provider_for(client))
    persist_client_to_session(st.session_state, client)

    job_view = present_job_status(client.last_status if client.last_status else {
        "job_id": client.job_id,
        "state": None,
        "result_available": client.last_snapshot is not None,
    })
    if client.job_id and not job_view.get("job_id"):
        job_view["job_id"] = client.job_id

    actions = render_job_panel(job_view)

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
        elif uploaded is None or spec is None:
            st.error("Arquivo e especificação são necessários para executar.")
        else:
            try:
                response = client.submit_job(
                    uploaded.getvalue(),
                    uploaded.name,
                    spec,
                    subject=subject,
                    content_type=getattr(uploaded, "type", None) or "application/octet-stream",
                )
                persist_client_to_session(st.session_state, client)
                st.info(f"Trabalho aceito: {response.get('job_id')}. Recuperação pelo identificador, não pelo WebSocket.")
                ws_url = os.environ.get("MODELA_WS_URL", "ws://127.0.0.1:8000/ws")
                _maybe_listen_websocket(client.job_id, ws_url)
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

    view = present_snapshot(snapshot, viewport_width=720)
    render_snapshot_panel(view, fixture=False)
    if snapshot:
        render_snapshot_charts(snapshot)
        legacy_charts = snapshot.get("charts") or {}
        if legacy_charts and not (snapshot.get("model") or {}).get("charts"):
            render_charts(legacy_charts)

    artifact_states = (client.last_status or {}).get("artifact_states") or {}
    artifact_view = present_artifacts(artifact_states)
    job_view = present_job_status(client.last_status if client.last_status else {
        "job_id": client.job_id,
        "state": None,
        "result_available": snapshot is not None,
    })
    art_actions = render_artifact_panel(artifact_view, job_view, snapshot=snapshot)

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

    if art_actions.get("save"):
        project_id = side.get("project_id")
        if not project_id:
            st.error("Informe o identificador do projeto na barra lateral para salvar a revisão.")
        elif snapshot is None:
            st.error("Não há cálculo para salvar.")
        else:
            try:
                saved = client.save_revision(
                    project_id,
                    {
                        "job_id": client.job_id,
                        "snapshot_ref": {"job_id": client.job_id},
                        "request_spec": form.get("request_spec"),
                    },
                )
                st.success(f"Revisão registrada: {saved.get('revision_id') or saved}")
            except (ApiConnectionError, ApiResponseError) as exc:
                st.error(str(exc))
                st.caption("A interface não grava uma cópia paralela local do projeto.")

    persist_client_to_session(st.session_state, client)


if _should_run_ui():
    main()
