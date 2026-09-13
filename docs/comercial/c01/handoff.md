# Handoff C01 — motor tecnicamente comprovado

## Destino

- Branch: `mp-com-20260912/c01-motor-comprovado`
- Base: `8d66c7973c659174e06d7223c9a9a8181e8eeabf` (`mp-pro-20260911/p04-referencia-consolidacao`, PR #20)
- PR incremental contra `mp-pro-20260911/p04-referencia-consolidacao`
- SHA de produto: **comentado após o commit**, não gravado aqui.

## O que mudou

1. **R20-B.** `search_models` devolve o melhor ajuste **numérico** mesmo quando o grau pedido não é framing. O worker não promove isso a `NO_WINNER`. O pedido fica em `requested_minimum_grade` / `grade_requirement_status` ∈ {not_met, pending} e `case_release_status=analysis_only`.
2. **R20-C.** `valuation_batch` deixou de escrever ±15% em `arbitration_interval`. Intervalos estatísticos vêm do residual; arbitragem/admissível só com regra C05. Sem C05, ficam null + `arbitration_rule_unverified`.
3. **Amostra.** Identidade, oferta/transação, recusa de área/preço ambíguos, grupos dependentes de fonte, estágios raw/interpreted/eligible/fitted, linhagem de features.
4. **Seleção.** Objetivo declarado = métrica de ranking (`aic` ou `original_scale_error`). Holdout não escolhe o vencedor.
5. **MP-QUAL/1** aditivo em `provenance.qualification_context`. Fingerprint. Revisão invalidada em mudança material.
6. **Custo.** `modules/cost_valuation/` BOM explícito. Terreno só com flag. Sem BOM, perfil de reconstrução não é emitido.
7. **API.** Token inválido 403, fingerprint divergente 409, perfil/candidate_cols inválidos 400. `access_token` no 202.

## Dependências de outras frentes

| Frente | Precisa | Estado neste HEAD |
| --- | --- | --- |
| C05 | `modules/qualification_profile.assess_qualification`, catálogo, regra de arbitragem, grau normativo único | Ausente → regras decisivas `unverified`. Pedido de contrato: ver `docs/comercial/c01/requests/c05.md`. |
| C04 | Pin de statsmodels/scipy no constraint global se a versão observada divergir | Sem nova dependência. `reuse.json` registrou versões observadas. |
| C02 | Emitir só `qualification_profile` conhecido; não recalcular grau | Consumidor. |
| C03 (lote) | Ler `qualification_context` / `value.basis`; não reconstruir matemática do PDF | Consumidor. |
| C06 | Compor esta PR na #20 depois do HEAD estabilizado | Não misturar com H01–H06. |

## Limitações

- Sem fonte CUB/ABNT licenciada: custo é sintético rotulado.
- Sem C05, `ready_for_professional_signoff` institucional não é marcado `passed`.
- Não há certificação NIST/ABNT/CAIXA/SUSEP.
- `COMMERCIAL_RELEASE_READY` não.

## Retomada

```text
git fetch origin
git checkout mp-com-20260912/c01-motor-comprovado
PYTHONPATH= python3 -m pytest tests/comercial/c01 tests/c01_input tests/c05_search tests/c14_batch tests/pro_workflow/p01 -q --tb=line
```

R20-B/C: script de reprodução na scratch da sessão (`r20_before.log`, `r20_after.log`).
