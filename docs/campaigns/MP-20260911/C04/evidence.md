# C04 — Ajuste consistente e exclusões justificadas

## Identidade

- Campanha: C04
- Lote: MP-20260911
- Branch: `mp-20260911/c04-ajuste_amostra_influencia`
- Base auditada: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`
- Contrato: MP/1

## Reprodução dos achados na base

No SHA auditado, `ModelBuilder.build_model(..., remove_outliers=True)` (default True):

1. Ajusta OLS, chama `detect_outliers` (Cook > 1.0 ou |resíduo studentizado| > 2.5) e **refaz o ajuste sem esses índices** se restar >50% da amostra. C05 chama esse caminho para cada candidato — a amostra deixa de ser comum.
2. `sm.OLS(...).fit()` usa `method='pinv'` por default: posto deficiente produz coeficientes sem rejeição.
3. `add_precision_and_extrapolation` mistura predição do avaliando com interpretação NBR (item 4 / Tabela 5) no mesmo método.
4. `sm.add_constant` na versão local já usa `has_constant='skip'`, mas o builder não diagnosticava constante pré-existente nem k duplicado.

## O que foi implementado

- `modules.model_builder.fit_candidate` / `evaluate_fitted`
- Tipos `CandidateSpec`, `CandidateFit`, `CandidateAssessment`
- `modules.influence_policy`: `report_only` (default), `reviewed_exclusions`, regras pré-ajuste com evidência, cenário exploratório separado
- Adapter `ModelBuilder.build_model`: **não dropa** com `remove_outliers=True`; emite aviso; influência relatada
- OLS interno via `method='qr'` depois de checar posto com `np.linalg.matrix_rank` (sem pinv)
- Ponto em `value.point` direto; `mean_ci80` ≠ `prediction_interval`; campos não calculados ficam `null`
- C06/C03/C02 por import preguiçoso; ausência = issue + pendência, sem substituto de produção

## Comandos

Semente dos casos: `20260911`.

```
python3 -m pytest tests/c04_fitting tests/test_model_builder.py -q
# 29 passed, duas vezes, exit 0
python3 tests/c04_fitting/consumer_launch.py
# OK status fitted point 798.8934116584857 n 30 sha 45eaf92fe642 (duas vezes, idêntico)
```

Versões: Python 3.12.3, pytest 9.1.1, statsmodels 0.15.0, pandas 3.0.5, numpy 2.5.2.

## Impacto em testes de outros donos (não editados)

Na árvore C04, estes testes alheios falham porque o drop silencioso acabou (handoff, não correção furtiva):

- `tests/test_verification.py::TestVerification::test_outlier_detection` (C16) — espera R² maior após `remove_outliers=True`
- `tests/test_nbr14653.py::...test_extrapolation_range_uses_data_effectively_used_after_outlier_removal` (C03) — espera `outliers_removed` não vazio

## Pares reais em outras branches (não commitados aqui)

- C02 `fit_dataset` / `transform_subject` — worktree `modela-pro-c02`
- C03 `assess_normative` — worktree `modela-pro-c03`
- C06 `fit_target_transform` / `inverse_target_prediction` — worktree `modela-pro-c06` (nomes `identity`|`log`; C04 mapeia `ln`→`log`)

C04 os chama se o módulo existir no processo; esta PR não copia esses arquivos.

## Revisão

Autorrevisão: ver `acceptance.json` → `review_findings`. Não houve revisor independente nesta sessão.
