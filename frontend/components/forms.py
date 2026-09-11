import streamlit as st
import pandas as pd
import re


def _looks_like_identification(col_name: str, series: pd.Series) -> bool:
    """
    Simple heuristic used ONLY to pre-select the default state of the
    "Variáveis candidatas para o modelo" multiselect below. It never
    restricts what the user can pick - it just tries to guess which
    columns are pure identification data (nome, endereço, telefone...)
    so they start unchecked, while every other column (any dtype, any
    number of unique values) starts checked and can be freely
    added/removed by the user regardless of this guess.

    Per spec, this only applies to dtype object/string columns whose text
    is clearly non-numeric - a numeric column (e.g. "idade") must never be
    caught by this, regardless of its name. The dtype check runs first, and
    the keyword check below uses whole-token matching (split on
    non-alphanumeric boundaries) so e.g. "id" never matches inside "idade",
    "cidade", "unidade" etc. "bairro" is intentionally NOT a keyword here -
    it is a legitimate categorical model variable, not identification data.

    Uses pd.api.types.is_string_dtype instead of `series.dtype == object`:
    pandas 2.x/3.x can read text columns as the dedicated StringDtype
    ("string"/"str") instead of legacy `object`, depending on version and
    settings (confirmed happening here with pandas 3.0 + pd.read_excel) - an
    `== object` check silently never matches those columns, disabling this
    entire heuristic for every text column without any error or warning.
    """
    if not pd.api.types.is_string_dtype(series):
        return False

    keywords = {
        'nome', 'endereco', 'endereço', 'telefone', 'fone', 'celular',
        'email', 'e-mail', 'cpf', 'cnpj', 'rg', 'contato', 'informante',
        'id', 'matricula', 'matrícula', 'observacao', 'observação', 'obs',
    }
    name_tokens = [t for t in re.split(r'[^a-z0-9]+', str(col_name).lower()) if t]
    if any(t in keywords for t in name_tokens):
        return True

    non_null = series.dropna().astype(str)
    if len(non_null) == 0:
        return False

    def _is_numeric_like(s: str) -> bool:
        cleaned = s.replace('R$', '').replace('.', '').replace(',', '.').strip()
        try:
            float(cleaned)
            return True
        except ValueError:
            return False

    numeric_ratio = non_null.apply(_is_numeric_like).mean()
    if numeric_ratio >= 0.5:
        return False

    avg_words = non_null.apply(lambda s: len(s.split())).mean()
    return avg_words >= 2


def upload_form():
    """
    Renders the file upload and configuration form.
    """
    st.subheader("Carregar Dados")

    uploaded_file = st.file_uploader("Escolha um arquivo CSV ou Excel", type=['csv', 'xlsx', 'xls'])

    degree = st.selectbox(
        "Grau Mínimo Desejado (NBR 14653-2)",
        options=[1, 2, 3],
        index=0,
        help=(
            "Grau de fundamentação MÍNIMO que a avaliação deve atingir. O sistema busca "
            "automaticamente, entre as variáveis disponíveis, a combinação que resulte no "
            "melhor modelo possível para alcançar este grau (em vez de apenas validar um "
            "modelo fixo contra ele)."
        )
    )

    target_col = None
    avaliando_dict = None
    grau_item1 = 1
    grau_item3 = 1
    candidate_cols = None
    solicitante = ""
    finalidade = ""

    if uploaded_file:
        try:
            # Read just columns to let user select target
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)

            cols = df.columns.tolist()
            target_col = st.selectbox(
                "Variável Dependente (Valor)",
                options=cols,
                help="Selecione a coluna que representa o valor do imóvel."
            )

            other_cols = [c for c in cols if c != target_col]
            default_candidates = [
                c for c in other_cols if not _looks_like_identification(c, df[c])
            ]
            candidate_cols = st.multiselect(
                "Variáveis candidatas para o modelo",
                options=other_cols,
                default=default_candidates,
                help=(
                    "Todas as colunas da planilha (exceto a variável dependente) estão "
                    "disponíveis para entrar como variável candidata, sem limite de "
                    "quantidade ou tipo. Por padrão, colunas que parecem ser apenas dados "
                    "de identificação (nome, endereço, telefone...) vêm desmarcadas, mas "
                    "você pode adicionar ou remover qualquer coluna livremente."
                ),
            )
            if not candidate_cols:
                st.warning(
                    "Nenhuma variável candidata selecionada: por padrão, o sistema "
                    "considerará TODAS as colunas restantes (exceto a variável "
                    "dependente) como candidatas."
                )

            col_sol, col_fin = st.columns(2)
            with col_sol:
                solicitante = st.text_input(
                    "Solicitante", value="",
                    help="Nome do solicitante da avaliação (opcional, para o laudo).",
                )
            with col_fin:
                finalidade = st.text_input(
                    "Finalidade da Avaliação", value="",
                    help="Finalidade da avaliação (opcional, para o laudo).",
                )

            with st.expander(
                "Imóvel avaliando (opcional — necessário para grau de precisão e "
                "verificação de extrapolação)"
            ):
                numeric_cols = [
                    c for c in df.select_dtypes(include="number").columns.tolist()
                    if c != target_col
                ]

                if numeric_cols:
                    st.caption(
                        "Preencha as características do imóvel que está sendo avaliado. "
                        "Isso permite calcular o grau de precisão (Tabela 5) e verificar "
                        "extrapolação (item 4) em relação aos dados de mercado."
                    )
                    empty_row = pd.DataFrame([{c: None for c in numeric_cols}])
                    avaliando_df = st.data_editor(
                        empty_row,
                        num_rows="fixed",
                        hide_index=True,
                        key="avaliando_editor",
                    )

                    row = avaliando_df.iloc[0]
                    if row.notna().any():
                        avaliando_dict = {c: v for c, v in row.items() if pd.notna(v)}
                else:
                    st.info(
                        "Não há colunas numéricas disponíveis (além da variável-alvo) para "
                        "caracterizar o imóvel avaliando."
                    )

                grau_item1 = st.selectbox(
                    "Grau de caracterização do imóvel avaliando (item 1)",
                    options=[1, 2, 3],
                    index=0,
                    help=(
                        "Item documental da norma (fotos, plantas, memorial descritivo do "
                        "imóvel avaliando). O sistema não consegue verificar isso sozinho a "
                        "partir da planilha de dados — informe manualmente."
                    ),
                )
                grau_item3 = st.selectbox(
                    "Grau de identificação dos dados de mercado (item 3)",
                    options=[1, 2, 3],
                    index=0,
                    help=(
                        "Item documental da norma (endereços, fontes e identificação dos "
                        "dados de mercado coletados). O sistema não consegue verificar isso "
                        "sozinho a partir da planilha de dados — informe manualmente."
                    ),
                )

        except Exception as e:
            st.error(f"Erro ao ler arquivo: {e}")

    return (
        uploaded_file, degree, target_col, avaliando_dict, grau_item1, grau_item3,
        candidate_cols, solicitante, finalidade,
    )
