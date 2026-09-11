# CONFENGE MODELA PRO

Sistema local de avaliação imobiliária por dados de mercado. O lote MP-20260911
compõe o contrato MP/1: ingestão → esquema → busca → snapshot → persistência →
PDF/dossiê. O grau de fundamentação/precisão é **calculado e rastreado**, não
uma certificação automática da NBR 14653 nem autorização de emissão de laudo.

## Início local (Linux; Windows não verificado neste lote)

```text
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate (não executado aqui)
pip install -U pip
pip install -c constraints/linux-py3.txt -e ".[dev]"
cp .env.example .env               # opcional; não commitar .env
modelapro                          # API 127.0.0.1:8000 + Streamlit 127.0.0.1:8501
```

Somente API: `modelapro-api`. Somente UI: `modelapro-frontend`.

Redis **não** é necessário. O bind padrão é `127.0.0.1`, não `0.0.0.0`.
CORS é uma lista explícita de origens localhost; `*` é recusado.

## Fluxo

1. A UI (C09) monta `RequestSpec` e envia o arquivo + JSON para `POST /preview` e `POST /jobs`.
2. C10 compõe C01 `ingest_market` → C02 `fit_dataset` / `transform_subject` → C05 `search_models` → C04 `evaluate_fitted` → C03 `assess_normative` → C13 `recommend_next_actions` → `freeze_result_snapshot`.
3. C11 persiste o job. O resultado é `GET /jobs/{id}/result`, não o WebSocket.
4. C08 gera o PDF a partir do snapshot (sem recalcular o modelo). C12 gera o dossiê com hashes.
5. C14 avalia lote sobre um `FrozenProject`; não copia grau entre imóveis.

`candidate_cols=[]` autoriza **nenhuma** variável (erro explícito). `null` é seleção automática por papel. Alvo ausente não é imputado. Unidade/data desconhecidas ficam pendentes (não se presume BRL nem a data de hoje).

## Testes

```text
python scripts/c17_acceptance/run.py --output /tmp/c17-out
pytest tests/c17_integration -q
```

Testes por campanha: `tests/c01_input` … `tests/c15_packaging`. Corpus independente: `python scripts/c16_acceptance/run_harness.py`.

## Recuperação

- Job `queued|running|succeeded|failed|cancelled|interrupted`. Cálculo bem-sucedido é separado de artefato PDF/dossiê `failed`.
- Reinício: jobs `running` viram `interrupted`. Resultado já congelado permanece em `GET /jobs/{id}/result`.
- Cancelamento: `POST /jobs/{id}/cancel`.
- Dois jobs no mesmo processo não compartilham snapshot.

## Limitações reais

- Não emite laudo profissional nem aprova conformidade integral da NBR 14653.
- Regras não verificadas: `docs/campaigns/MP-20260911/C03/unverified_rules.md`.
- Busca `exact` só garante ótimo no espaço enumerado com o critério de ranking completo; modo limitado divulga cobertura.
- PDF exige WeasyPrint + bibliotecas nativas (Pango/cairo/GTK). `pip install weasyprint` sozinho não prova renderização.
- Instalação e E2E deste lote foram executados em Linux; Windows permanece `NOT_RUN`.

Integração do lote: `docs/campaigns/MP-20260911/INTEGRATION.md`.

## Estrutura

- `frontend/`: Interface Streamlit (C09)
- `backend/`: API FastAPI e composição (C10)
- `modules/`: Núcleo MP/1 (C01–C08, C11–C14)
- `scripts/c15_local/`: launcher e probes de instalação
- `scripts/c17_acceptance/`: aceite consolidado
- `tests/`: testes originais e por campanha

