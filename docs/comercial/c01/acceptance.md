# C01 — oito aceites

Estados: `IMPLEMENTED_VERIFIED` | `IMPLEMENTED_PARTIAL` | `WAITING_FOR_COMPONENTS` | `BLOCKED_EXTERNAL_EVIDENCE`.

| ID | Critério | Estado | Evidência |
| --- | --- | --- | --- |
| C01-A01 | Dados íntegros e representatividade | IMPLEMENTED_VERIFIED | `tests/comercial/c01/test_a01_ingest.py` dirige `ingest_market` / `fit_dataset`. Preço ausente permanece ausente; `1.234` em locale `auto` não vira 1234; duplicata conserva dois `row_id`; oferta/transação não colapsam; ledger received/observed/prepared/used; linhagem em `feature_schema.feature_lineage`. |
| C01-A02 | Referência numérica e diagnósticos | IMPLEMENTED_VERIFIED | `tests/comercial/c01/test_a02_a05_fit_selection.py` compara `fit_candidate` + `builtin_evaluate_fitted` ao oráculo `numpy.linalg.lstsq` de P01. Log invertido por `exp` via `inverse_target_prediction`. Singular/rank_deficient → `rejected`, não `fitted`. |
| C01-A03 | Grau pedido sem perda ou falso aceite | IMPLEMENTED_VERIFIED | Grau 3 com ajuste válido devolve análise (`grade_requirement_status=not_met/pending`, `case_release_status=analysis_only`), não `NO_WINNER`. Grau 1 tem caminho `met` → `review_required`. Conflito de aliases → `GRADE_ALIAS_CONFLICT`. Input corrompido → `CompositionError` com código estável. |
| C01-A04 | Paridade após persistir e reproduzir | IMPLEMENTED_VERIFIED | Compose, `evaluate_batch` e subprocesso `restore_candidate_fit` compartilham ponto/IC/predição/arbitragem. Arbitragem ±15% inventada foi removida do lote. Mutação de coeficiente altera o ponto. |
| C01-A05 | Seleção e validação consistentes | IMPLEMENTED_VERIFIED | `search_audit.objective.name` = métrica usada (`aic` ou `original_scale_error`). Holdout no `evaluation_policy` não muda o vencedor da busca. `model_scope=subject_specific` fica no audit. Orçamento não é ótimo global (`budget_is_not_global_optimum`). |
| C01-A06 | Finalidade de seguro / custo | IMPLEMENTED_PARTIAL | Rota BOM em `modules/cost_valuation/` soma quantidades×custo, não inclui terreno sem `include_land`, não é k×mercado. Sem BOM, perfil `reconstruction_cost` permanece `analysis_only`. Catálogo C05/`assess_qualification` ausente neste HEAD → `WAITING_FOR_COMPONENTS` para o perfil institucional. Não declarar bancos/seguradoras concluídos. |
| C01-A07 | Contexto normativo e revisão | IMPLEMENTED_PARTIAL | `provenance.qualification_context` MP-QUAL/1 com RuleResult mínimo, fingerprint, `case_release_status`, invalidação de revisão em mudança material. C05 não importável: regras decisivas `unverified`, nunca `passed`. |
| C01-A08 | API ouro e recusa | IMPLEMENTED_VERIFIED | TestClient FastAPI, peers reais (proibido `tests/c10_pipeline/doubles.py`). POST/GET duas vezes ouro (ponto igual, snapshot MP/1). Inapto `candidate_cols=[]` → 400 `CANDIDATE_COLS_EMPTY`. Token inválido → 403. Fingerprint divergente → 409. Perfil estruturalmente inválido → 400. |

## Produto vs componente

- Componente motor comparativo urbano: `IMPLEMENTED_VERIFIED` no recorte anunciado (imóvel urbano, regressão, análise + bloqueio de emissão quando grau/perfil falha).
- Oferta bancos/seguradoras: **não concluída**. Falta C05 catálogo/regra conferida, fonte de custo licenciada e aceite institucional real (`BLOCKED_EXTERNAL_EVIDENCE` / `WAITING_FOR_COMPONENTS`).
- `COMMERCIAL_RELEASE_READY`: não.

## Comandos

```text
PYTHONPATH= python3 -m pytest tests/comercial/c01 -q --tb=line
```

Duas passagens, exit 0. Artefatos de HTTP em scratch da sessão (`a08_gold_*.json`, `a08_reject_*.json`, `a08_http.log`). SHA de produto no comentário da PR, não neste arquivo.
