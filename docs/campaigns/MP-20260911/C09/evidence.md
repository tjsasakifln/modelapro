# C09 — Interface centrada no valor e na conclusão do trabalho

## Identidade

- Campanha: C09
- Lote: MP-20260911
- Branch: `mp-20260911/c09-interface_avaliador`
- Base auditada: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`
- HEAD da implementação: `081dc4c6590bbfef2ad3c2893efbc8e7ae67e596`
- Contrato: MP/1
- `origin/main` no momento da implementação: ainda em `c92949e` (sem reconciliação adicional)

## O que mudou no código enviado

A UI Streamlit deixa de disparar `POST /upload` e de esperar o primeiro evento WebSocket. O percurso visível é:

1. Importar e revisar a interpretação devolvida por `POST /preview`
2. Definir papéis, unidades e alvo (`RequestSpec` MP/1)
3. Informar o avaliando com variáveis-base do esquema (sem dummies)
4. Executar (`POST /jobs` → 202 com `job_id`)
5. Revisar valor, faixas e pendências a partir do `ResultSnapshot`
6. Salvar revisão, reabrir pelo `job_id` e baixar evidências

Regras locais comprovadas por teste (funções enviadas, não reimplementadas no teste):

- `bairro` entra como preditor categórico; número originalmente formatado (`1.234,56`) permanece em `raw_values`
- `candidate_cols=[]` significa nenhuma variável autorizada e bloqueia o disparo
- Ponto nulo não vira zero nem passa por `:.4f`; estados de precisão `not_computed` / `classified` / `unclassified` / `error` são rótulos distintos
- Após 202, `job_id` sobrevive a GET fechado/timeout; recuperação é `GET /jobs/{id}` e `GET /jobs/{id}/result`
- Segunda execução enquanto `queued`/`running` não gera outro POST
- Tela estreita e tabela longa preservam avisos; fixture visual está rotulada como não-caso-real

## Comandos e versões

```
python: Python 3.12.3
pytest: 9.1.1
streamlit: 1.63.0
httpx: 0.28.1
pandas: 3.0.5
```

```
python3 -m pytest tests/test_forms_heuristics.py tests/c09_frontend/test_request_spec.py -q
# 14 passed, exit 0

python3 -m pytest tests/c09_frontend/test_snapshot_presenter.py -q
# 9 passed, exit 0

python3 -m pytest tests/c09_frontend/test_job_client.py -q
# 7 passed, exit 0

python3 -m pytest tests/c09_frontend/test_layout_states.py tests/c09_frontend/test_app_launch.py -q
# 7 passed, exit 0

python3 -m pytest tests/test_forms_heuristics.py tests/c09_frontend/ -q
# 37 passed, exit 0
```

Lançamento in-process (duas vezes) via `streamlit.testing.v1.AppTest.from_file("frontend/app.py")`:

- sem traceback
- título `MODELA PRO`
- percurso em português (importar → papéis → avaliando → executar → valor/pendências → evidências)
- ausência da linha legado de métricas R² como conclusão principal

Semente: nenhuma. Dados de fixture são sintéticos e rotulados.

## Dependências não publicadas

Rotas C10/C11 ainda inexistentes em `backend/api.py` na base auditada (`/health`, `/upload`, `/ws` apenas):

- `POST /preview`
- `POST /jobs`
- `GET /jobs/{id}`
- `GET /jobs/{id}/result`
- `POST /jobs/{id}/cancel`
- `GET /jobs/{id}/artifacts/{name}`
- `GET /projects`, `GET /projects/{id}`
- `POST /projects/{id}/revisions`
- `POST /projects/{id}/batch`

A UI mostra erro de conexão ou HTTP explícito; não inventa prévia local incompatível nem arquivo paralelo de projeto.

`frontend/__init__.py` e `frontend/components/__init__.py` pertencem à C15. Esta campanha usa importação dupla (`components.*` / `frontend.components.*`) dentro de `frontend/app.py`.

## Revisão adversarial (autor)

- Confirmado no código legado: `[]` era anunciado como “todas as colunas”; WS era a via de resultado; `metrics.get('r2', 0):.4f` substituía nulo por zero; banner `is_valid` → “atende à norma”.
- Correções exercitadas pelos testes C09-A01…A05 no código enviado.
- E2E contra API publicada fica para C17.
- Simuladores HTTP nos testes são rotulados e não são evidência de integração real.

## Status

`INTEGRATION_PENDING` — aceites locais A01–A05 passaram; pares C10/C11 ainda não publicados.
