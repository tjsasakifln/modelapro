import streamlit as st
import base64

def render_charts(charts_data: dict):
    """
    Renders charts from base64 strings.
    """
    if not charts_data:
        return

    st.subheader("Análise Gráfica")

    col1, col2, col3 = st.columns(3)

    with col1:
        if 'residuals_vs_fitted' in charts_data:
            st.image(
                base64.b64decode(charts_data['residuals_vs_fitted']),
                caption="Resíduos vs Valores Ajustados",
                use_container_width=True
            )

    with col2:
        if 'residuals_hist' in charts_data:
            st.image(
                base64.b64decode(charts_data['residuals_hist']),
                caption="Histograma de Resíduos",
                use_container_width=True
            )

    with col3:
        if 'observed_vs_estimated' in charts_data:
            st.image(
                base64.b64decode(charts_data['observed_vs_estimated']),
                caption="Preços Observados vs. Valores Estimados",
                use_container_width=True
            )
