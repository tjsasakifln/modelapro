# C15 — Instalação reproduzível, configuração local e CI

Instruções locais desta campanha. O README global é propriedade da C17.

## Instalação (clone)

```text
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip
pip install -c constraints/linux-py3.txt -e ".[dev]"
```

Instalação a partir do artefato (fora da árvore):

```text
python -m build
pip install -c constraints/linux-py3.txt dist/modelapro-*.whl
```

## Início local

Um comando (API FastAPI em loopback + Streamlit como processo próprio):

```text
modelapro
```

Equivalente a partir do checkout:

```text
python scripts/c15_local/launcher.py
```

Somente API / somente UI:

```text
modelapro-api
modelapro-frontend
```

URLs padrão: `http://127.0.0.1:8000/health` e `http://127.0.0.1:8501`.
Redis **não** é necessário. O bind padrão é `127.0.0.1`, não `0.0.0.0`.

Copie `.env.example` para `.env` se quiser ajustar portas. Não commite `.env`.

## Teste

```text
pytest tests/c15_packaging/ -q
```

Smoke de instalação em venv limpo (lento):

```text
C15_INSTALL_SMOKE=1 pytest tests/c15_packaging/test_wheel_install_smoke.py -q
```

Diagnóstico PDF (WeasyPrint + bibliotecas nativas):

```text
modelapro --check-pdf
```

`pip install weasyprint` **não** prova geração de PDF. Faltando Pango/cairo/GTK o probe devolve instrução por SO.

## Atualizar o lock

Ver `constraints/README.md`.
