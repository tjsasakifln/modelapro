import streamlit as st
import asyncio
import base64
import requests
import json
import websockets
from components.layout import load_css, header, sidebar
from components.forms import upload_form
from components.charts import render_charts

# Configuration
API_URL = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/ws"

st.set_page_config(
    page_title="CONFENGE MODELA PRO",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

load_css()
header()
sidebar()

# Session State
if 'processing' not in st.session_state:
    st.session_state.processing = False
if 'results' not in st.session_state:
    st.session_state.results = None
if 'progress' not in st.session_state:
    st.session_state.progress = 0.0
if 'status_message' not in st.session_state:
    st.session_state.status_message = ""

async def listen_websocket():
    # max_size raised above the websockets library default (1 MiB): the
    # completed-analysis payload now carries several base64-encoded chart
    # PNGs plus the base64 PDF report (report_pdf_base64) and can exceed 1 MiB
    # for larger datasets/models. Without this, the connection closes
    # silently mid-analysis (swallowed by ConnectionClosed below).
    async with websockets.connect(WS_URL, max_size=10 * 1024 * 1024) as websocket:
        while st.session_state.processing:
            try:
                msg = await websocket.recv()
                data = json.loads(msg)
                
                if 'progress' in data:
                    st.session_state.progress = data['progress']
                
                if 'status' in data:
                    st.session_state.status_message = data.get('message', data['status'])
                    
                if data.get('status') == 'completed':
                    st.session_state.results = data
                    st.session_state.processing = False
                    st.rerun()
                    
                if data.get('status') == 'error':
                    st.error(data.get('message'))
                    st.session_state.processing = False
                    st.rerun()
                    
            except websockets.exceptions.ConnectionClosed:
                break

def main():
    (
        uploaded_file, degree, target_col, avaliando_dict, grau_item1, grau_item3,
        candidate_cols, solicitante, finalidade,
    ) = upload_form()

    if uploaded_file and target_col:
        if st.button("Iniciar Análise", disabled=st.session_state.processing):
            st.session_state.processing = True
            st.session_state.progress = 0.0
            st.session_state.results = None

            # Send to API
            files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
            data = {
                "degree": degree,
                "target_col": target_col,
                "grau_item1": grau_item1,
                "grau_item3": grau_item3,
                "solicitante": solicitante or "",
                "finalidade": finalidade or "",
            }
            if avaliando_dict:
                data["avaliando_json"] = json.dumps(avaliando_dict)
            if candidate_cols is not None:
                # Sent even when the user deselected every candidate, so the
                # backend receives the user's actual (possibly empty)
                # choice rather than silently falling back to "all columns"
                # without the user having explicitly seen that outcome (see
                # the warning shown in the form for the empty case).
                data["candidate_cols_json"] = json.dumps(candidate_cols)

            try:
                response = requests.post(f"{API_URL}/upload", files=files, data=data)
            except Exception as e:
                st.error(f"Erro de conexão: {e}")
                st.session_state.processing = False
                response = None

            if response is not None:
                if response.status_code == 200:
                    # listen_websocket() blocks until the backend sends
                    # 'completed'/'error' (or the socket closes), then calls
                    # st.rerun() itself. It is intentionally NOT inside the
                    # try/except above: st.rerun() raises a control-flow
                    # exception that Streamlit's own script runner must
                    # catch at the top level - wrapping it in `except
                    # Exception` here would swallow it and silently break
                    # the rerun (this is a single local user per the
                    # project's scope, so a blocking wait is an acceptable
                    # trade-off for correctness over a live progress bar).
                    with st.spinner(
                        "Processando análise (busca de variáveis, validação NBR 14653-2, "
                        "geração do laudo)... pode levar de segundos a poucos minutos, "
                        "dependendo do tamanho da busca."
                    ):
                        asyncio.run(listen_websocket())
                else:
                    st.error(f"Erro no envio: {response.text}")
                    st.session_state.processing = False

    # Progress Area
    if st.session_state.processing:
        st.progress(st.session_state.progress)
        st.info(f"Status: {st.session_state.status_message}")
        
        # NOTE: Real-time WS in Streamlit usually requires st.empty() loops or custom components
        # For this implementation plan, we acknowledge this limitation. 
        # We would need to run the async loop.
        
    # Results Area
    if st.session_state.results:
        st.success("Análise Concluída!")
        
        res = st.session_state.results
        metrics = res.get('model_metrics', {})
        
        # Metrics Row
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("R²", f"{metrics.get('r2', 0):.4f}")
        c2.metric("R² Ajustado", f"{metrics.get('r2_adjusted', 0):.4f}")
        c3.metric("Estatística F", f"{metrics.get('f_statistic', 0):.2f}")
        c4.metric("Durbin-Watson", f"{metrics.get('autocorrelation_durbin_watson', 0):.2f}")
        
        st.markdown("### Fórmula do Modelo")
        st.code(res.get('formula', 'N/A'))

        # Classificação NBR 14653-2
        val = res.get('validation', {}) or {}
        grau_labels = {3: "Grau III", 2: "Grau II", 1: "Grau I"}

        st.markdown("### Classificação NBR 14653-2")

        grau_fund = val.get('grau_fundamentacao')
        grau_fund_label = grau_labels.get(grau_fund, "Não classificado")

        target_achieved = res.get('target_achieved')
        best_grau_reached = res.get('best_grau_reached')
        target_degree = val.get('target_degree')

        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("Grau de Fundamentação Atingido", grau_fund_label)
        with col_b:
            grau_prec = val.get('grau_precisao')
            if grau_prec is not None:
                st.metric("Grau de Precisão", grau_labels.get(grau_prec, "Não classificado"))
            else:
                st.metric("Grau de Precisão", "Não calculado")
                st.caption("Não calculado — informe o imóvel avaliando para obter o grau de precisão.")

        if target_achieved:
            st.success(
                f"O grau mínimo solicitado ({grau_labels.get(target_degree, target_degree)}) foi atingido."
            )
        else:
            best_label = grau_labels.get(best_grau_reached, "Não classificado")
            st.warning(
                f"O grau mínimo solicitado ({grau_labels.get(target_degree, target_degree)}) NÃO foi "
                f"alcançado. Melhor grau de fundamentação alcançado pelo sistema: {best_label}."
            )

        item_scores = val.get('item_scores', [])
        if item_scores:
            st.markdown("#### Detalhamento por Item (Tabela 1)")
            table_rows = [
                {
                    "Item": it.get("item"),
                    "Descrição": it.get("description"),
                    "Grau Atingido": it.get("grau_achieved"),
                    "Detalhe": it.get("detail"),
                }
                for it in item_scores
            ]
            st.dataframe(table_rows, use_container_width=True, hide_index=True)

        # Colunas da planilha que não puderam tecnicamente virar variável de
        # modelo (ex.: texto livre com muitos valores únicos, coluna 100%
        # vazia), uma por uma com o motivo - o usuário precisa saber sempre
        # que uma coluna trazida por ele não pôde ser usada, e por quê.
        excluded_columns = res.get('excluded_columns', {}) or {}
        if excluded_columns:
            st.subheader("Colunas não utilizadas como variável")
            for col, reason in excluded_columns.items():
                st.info(f"**{col}**: {reason}")

        # Colunas que o usuário explicitamente pediu como candidatas mas que
        # não puderam ser localizadas/usadas (nome incorreto, etc.).
        candidate_warnings = res.get('candidate_warnings', [])
        for w in candidate_warnings:
            st.warning(w)

        # Observações da própria busca de variáveis/transformações (ex.:
        # fallback por correlação, amostragem do histórico, ou variável(is)
        # candidata(s) excluída(s) da busca por falta de valor do imóvel
        # avaliando - ver OptimalCombinationFinder.find_best_model). Nunca
        # deixar isso visível apenas nos logs do servidor ou só no PDF.
        search_message = res.get('search_message')
        if search_message:
            st.warning(f"Observações da busca: {search_message}")

        # Avisos gerais de validação dos dados (ex.: tamanho de amostra).
        data_warnings = res.get('data_warnings', [])
        if data_warnings:
            st.subheader("Avisos sobre os dados")
            for w in data_warnings:
                st.warning(w)

        # Charts
        render_charts(res.get('charts', {}))

        # Validation (mensagens e avisos gerais)
        if val:
            st.subheader("Validação NBR 14653-2")
            if val.get('is_valid'):
                st.success("Modelo Atende aos Critérios Normativos")
            else:
                st.error("Modelo Não Atende a Todos os Critérios")

            for msg in val.get('messages', []):
                st.warning(msg)

        # Laudo PDF (NBR 14653-2 §10.2)
        if res.get('report_pdf_base64'):
            st.download_button(
                "Baixar Laudo (PDF)",
                data=base64.b64decode(res['report_pdf_base64']),
                file_name="laudo_avaliacao.pdf",
                mime="application/pdf",
            )

if __name__ == "__main__":
    main()
