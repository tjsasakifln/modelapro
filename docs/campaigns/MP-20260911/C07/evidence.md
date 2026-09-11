# C07 — Validação independente e estabilidade da avaliação

Campanha: **C07**  
Lote: **MP-20260911**  
Contrato: **MP/1**  
Base de referência: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`  
Implementação: `b1a574592fa8c594d8a0c8e3e2b6a737914b24be`  
Branch: `mp-20260911/c07-validacao_estabilidade`

## Achados F05 / F06 no HEAD de referência

Reproduzidos por leitura do código em `c92949e`, não por README.

**F05 — busca sem holdout.** `OptimalCombinationFinder.find_best_model` ajusta e ranqueia candidatos no DataFrame inteiro (`df`, `y = df[target_col]`). Não há partição externa. Reavaliar o vencedor na mesma base não seria avaliação independente.

**F06 — imputação no frame inteiro.** `DataLoader.load_data` preenche numéricos com `fillna(self.df[numeric_cols].mean())` sobre todas as linhas, antes de qualquer reserva. Categorias one-hot também usam `nunique` do arquivo completo.

Neste HEAD **não existiam** `modules.model_evaluation.evaluate_procedure` nem `modules.model_stability`. C07 acrescenta esses módulos sem reimplementar os motores C01/C02/C04/C05.

## O que foi entregue

- `evaluate_procedure(input_bundle, request_spec, fit_select_predictor, seed)` avalia o procedimento encapsulado no callback. Só ids de treino vão ao callback. O reservado não é filtrado por residual e não escolhe imputação/categoria/seleção.
- Partição externa `random` / `group` / `temporal` (e k-fold / janela temporal expansiva quando `n_splits>1`). Grupos e datas só quando o metadado existe; nada é inventado.
- Métricas MAE/RMSE na unidade original, erro relativo só com denominador válido, referência `train_mean`, cobertura com falhas no denominador.
- `analyze_stability` com nomes distintos: `pipeline_bootstrap` ≠ `fixed_model_sensitivity`; também frequência de seleção, dispersão de candidatos e sensibilidade a revisões justificadas.
- Resultado mapping Python JSON-serializável, sem DataFrame/modelo, sem grau normativo, sem garantia pós-seleção.
- Testes sentinela em `tests/c07_validation/` com simuladores de par **rotulados** (`contract-simulator-not-production`).
- Custo/limites em `benchmarks/c07_validation/cost_limits.json`.

## Comandos

Ambiente: Python 3.12.3, pytest 9.1.1, numpy 2.5.2, pandas 3.0.5. Semente dos testes: ver cada arquivo (ex. 7, 3, 11, 21, 13, 42).

```
python3 -m pytest tests/c07_validation/ -q
```

Exit code: **0** (16 passed). Log: scratch `c07_pytest.log`.

Launch consumidor fresco (não o módulo pytest), duas vezes, seed 42:

```
python3 {SCRATCH}/c07_launch_consumer.py
```

Ambas: exit **0**, `LAUNCH_OK`, MAE/RMSE na escala original, cobertura 1.0, ids de treino disjuntos do reservado, `reserved_filtered_by_error=false`. Logs consistentes (`c07_launch_1.log`, `c07_launch_2.log`).

```
python3 benchmarks/c07_validation/run_cost.py
```

Exit **0**. Fast ~0.09s / full ~0.13s nesta amostra sintética; `executed_steps` e `stability_executed_analyses` gravados em `cost_limits.json`.

## Critérios

| ID | Status local | Evidência |
|----|--------------|-----------|
| C07-A01 | pass | `test_a01_leak_sentinel.py`: callback só vê treino; encoder correto não inclui `LEAK_CAT`; sentinela `detect_preprocessing_leak` pega imputação/categoria/ids do reservado no callback vazado. |
| C07-A02 | pass | `test_a02_noise_and_signal.py`: sinal conhecido MAE << referência em 2 seeds; ruído MAE na ordem da referência + limitação explícita; sem garantia por um seed. |
| C07-A03 | pass | `test_a03_unseen_category.py`: `c07.unseen_category` na cobertura; `n_reserved` não encolhe; `y_pred` das falhas é `null`, não zero. |
| C07-A04 | pass | `test_a04_group_temporal.py`: duplicatas de `property_id` não cruzam; temporal `max(train) <= min(test)`; mesma semente reproduz; sem metadado não inventa grupo. |
| C07-A05 | pass | `test_a05_provenance_budget.py`: proveniência, escala original, `normative_label.applied=false`, orçamento lista o executado, nomes distintos bootstrap vs modelo fixo, JSON sem não-finitos. |

## Integração

Pares C01/C02/C04/C05/C10 ainda não exportam as interfaces MP/1 neste HEAD. C07 testa contra fixtures de contrato rotulados. **Não é PASS_E2E.** Status do componente: ver `acceptance.json`.

A validação externa **não** retorna ao loop de escolha (`usable_for_model_selection: false`).
