# P01 — Consistência técnica, projetos reutilizáveis e dossiê reproduzível

Lote `MP-PRO-20260911`. Campanha `P01`.  
`BASE_SHA=6d54f902b85a5a37bfbf154d39f74cf854ff9b2b` (PR #17 `mp-20260911/integracao-final`, ainda draft).  
Branch exclusiva: `mp-pro-20260911/p01-nucleo-reuso`.  
Fixtures e o exemplo sanitizado são sintéticos (`SYNTHETIC P01 — not market evidence`).

## Antes (observado no HEAD de referência)

`build_frozen_project` copiava coeficientes, n/k e `feature_order`, mas **não** `residual_std` nem `xtx_inv`.  
`builtin_evaluate_fitted` precisava desses campos para IC80/predição. Sem eles: ponto sobrevivia, `mean_ci80` e `prediction_interval` iam a null, e `admissible_interval` era preenchido com a faixa arbitrada de ±15%.

Grau mínimo: a UI emitia `minimum_fundamentacao_grade`, o adapter legado `target_degree`, o ranking lia `min_fundamentacao_grade`.  
Seleção: freeze rotulava `population_model` enquanto `search_models` filtrava transformações pelo avaliando.

## Depois

Freeze extrai estado residual versionado (`xtx_inv_kind=normalized_cov_params`, `scale_convention=statsmodels.scale`) do OLS QR vivo, sem pickle. Restore/lote reaplicam o mesmo estado. Estado incompleto/malformado → limitação explícita; `admissible_interval` não é a faixa de ±15%.

Aliases de grau são normalizados em `validate_request_spec` (fronteira HTTP/contrato). Conflito → `GRADE_ALIAS_CONFLICT`. Grau 3 pedido com itens documentais pendentes **não** é `met`; ranking marca `exploratory`.

`population_model` deixa de filtrar o espaço pelo sujeito; `subject_specific` conserva a restrição. C05-A03/A05 foram ajustados para declarar `model_scope=subject_specific` quando a propriedade testada é a dependência do sujeito (a propriedade foi preservada, não relaxada).

Dossiê grava `model/residual_state.json` além do `residual_context` C12. `absence_kind` distingue `not_provided` de `lost_by_integration`. Artefato aditivo `evidence_bundle.zip`.

## Aceites

| ID | Resultado | Prova |
|----|-----------|--------|
| P01-A01 | pass | `tests/pro_workflow/p01/test_a01_ols_oracle.py` — n=36, categoria dummy, oracle `numpy.linalg.lstsq` + t 80%; ponto/IC/predição coincidem; `xtx_inv` não é σ²(X′X)⁻¹ |
| P01-A02 | pass | freeze JSON → processo 1 POST `/projects/{id}/revisions` → processo 2 GET e avalia dois sujeitos; matriz 3×3 `status=malformed` não gera IC; log sem IC de média monetária |
| P01-A03 | pass | aliases canônico / `target_degree` / `min_fundamentacao_grade` / UI `build_request_spec` / adapter legado; conflito 400; grau 3 pendente ≠ `met` |
| P01-A04 | pass | sujeito que invalida ln altera o espaço só em `subject_specific`; `population_model` idêntico entre sujeitos |
| P01-A05 | pass | dossiê com `subject_x` do freeze; `reproduce.py` recupera ponto e intervalos; GET `/jobs/{id}/artifacts/evidence_bundle.zip` com `application/zip`; tamper invalida integridade/reprodução |
| P01-A06 | pass | `workflow_context` MP-PRO/1; séries = `used_row_ids`; exemplo sanitizado em `sanitized_snapshot_context.example.json` |

## Comandos

```text
PYTHONPATH=. python3 -m pytest tests/pro_workflow/p01 -q
# 18 passed, exit 0 (duas execuções, mesma contagem)

PYTHONPATH=. python3 -m pytest tests/c05_search tests/c12_evidence tests/c14_batch tests/c10_pipeline -q
# exit 0 no recorte atribuído exercitado
```

Oracle A01 (síntese): ponto 590134.5411130369 vs shipped 590134.5411130373 (diff 3.5e-10). IC80 média e intervalo de predição distintos; predição mais larga.

## Handoff para P02/P03

- P02: emitir apenas `search_policy.minimum_fundamentacao_grade`. Download opcional `GET /jobs/{id}/artifacts/evidence_bundle.zip`. Não recalcular `grade_requirement_status`.
- P03: consumir `report_context.fitted_values/residuals/observed_values/series_row_ids` e `series_scale`/`series_unit`. Sem série → gráfico indisponível. `model.formula` é display; coeficientes integrais continuam no dossiê.

HEAD da PR é registrado no corpo/comentário **depois** do commit, para não circular o hash dentro do próprio commit.
