# CONFENGE MODELA PRO

Sistema avançado e modular para modelagem estatística e análise de variáveis conforme NBR 14653-2.

Dado um conjunto de dados de mercado (CSV/Excel, qualquer número e tipo de variáveis), o sistema busca
automaticamente a combinação de variáveis e transformações que melhor explica o valor do imóvel avaliando,
sem exigir iteração manual do usuário, substituindo o processo tipicamente feito em planilha ou em
softwares como o SisDEA.

## Funcionalidades

- Busca exaustiva (ou, quando o espaço de busca é combinatoriamente grande, poda documentada e transparente)
  sobre transformações de variável × inclusão, respeitando o tamanho mínimo de amostra da norma.
- Classificação automática do **Grau de Fundamentação** (I/II/III) pelo sistema oficial de pontuação da
  Tabela 1/Tabela 2 da NBR 14653-2, e do **Grau de Precisão** (Tabela 5) a partir do imóvel avaliando.
- Verificação de extrapolação (item 4) e cálculo do campo de arbítrio (±15%, Anexo A.10).
- Seleção livre de variáveis candidatas — nenhuma coluna é pré-fixada em número ou natureza; colunas que não
  puderem tecnicamente virar variável (texto livre de alta cardinalidade, coluna vazia) nunca são descartadas
  em silêncio, e ficam disponíveis como dado de identificação no laudo.
- Geração de laudo em PDF (NBR 14653-2 §10.1/10.2), com gráficos, tabela de itens e classificação.

## Instalação

1. Crie um ambiente virtual:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   venv\Scripts\activate     # Windows
   ```

2. Instale as dependências:
   ```bash
   pip install -e .[dev]
   ```

## Execução

### Backend
```bash
uvicorn backend.api:app --reload
```

### Frontend
```bash
streamlit run frontend/app.py
```

## Estrutura

- `frontend/`: Interface do usuário (Streamlit)
- `backend/`: API e processamento (FastAPI)
- `modules/`: Núcleo analítico e estatístico
- `tests/`: Testes automatizados
