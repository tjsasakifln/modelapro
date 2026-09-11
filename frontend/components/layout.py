import streamlit as st
import os

def load_css():
    """
    Loads the custom CSS file.
    """
    css_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'styles.css')
    if os.path.exists(css_path):
        with open(css_path, 'r') as f:
            st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

def header():
    """
    Renders the application header.
    """
    st.title("CONFENGE MODELA PRO")
    st.markdown("### Sistema Avançado de Avaliação Imobiliária com IA")
    st.markdown("---")

def sidebar():
    """
    Renders the sidebar.
    """
    with st.sidebar:
        st.image("https://via.placeholder.com/150", caption="CONFENGE") # Placeholder logo
        st.header("Configurações")
        st.info("Configure os parâmetros da avaliação.")
