# C13 — Diagnóstico acionável para concluir a avaliação

## Identidade

- Campanha: C13
- Lote: MP-20260911
- Branch: `mp-20260911/c13-acoes_para_concluir`
- Base de referência: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`
- HEAD: `33a6ef72bfce99e3bb06dd81d24b798ba482f587`
- Contrato: MP/1
- Função publicada: `modules.decision_support.recommend_next_actions(snapshot, feature_schema=None)`

## O que foi entregue

Biblioteca determinística que lê um rascunho de `ResultSnapshot` (mapeamento MP/1, completo ou parcial) e devolve `list[Action]` com `code`, `priority`, `reason`, `next_step`, `evidence_refs` e `limitations`.

Não há API de língua, não há reclassificação normativa (C03) e o snapshot de entrada não é mutado. Avisos originais permanecem no snapshot; as ações apenas os referenciam.

Prioridade (menor = mais urgente): integridade (unidade/parse, preço imputado/ambíguo, artefato falho, data-base) antes de sugestão de ajuste (R²). Observação influente gera revisão/investigação, nunca remoção automática.

Déficit amostral é `requirement - n` somente quando `n`, `k` e a regra verificada (ex.: `6(k+1)`) estão disponíveis. O exemplo `k=4`, `n=26` produz déficit 4 **para esse item**, com ressalva de que isso não garante o grau global.

## Comandos

```
python3 -m pytest tests/c13_decisions/ -q
# 15 passed, exit 0
# Python 3.12.3 / pytest 9.1.1
```

Consumidor fresco (duas vezes, mesmo snapshot `k=4,n=26` com regra `6(k+1)` verificada):

```
python3 -c "from modules.decision_support import recommend_next_actions; ..."
# ambas as execuções: LAUNCH_OK, listas iguais
# reason: Déficit de 4 para este item (n=26, k=4, requisito 6(k+1)=30).
#         Este déficit refere-se somente a este item e não garante o grau global de fundamentação.
```

Saídas capturadas na sessão (não versionadas): `c13_pytest.txt`, `c13_launch_1.txt`, `c13_launch_2.txt`.

## Revisão adversarial (autor)

- Códigos de issue não reconhecidos não geram ação; C10 deve emitir os literais documentados em `handoff.json` ou os campos estruturais (`validation.precisao.status`, `validation.documentary.status`, `artifact_states`).
- Snapshot MP/1 sem `reference_date` gera `define_reference_date`. Omitir o campo e passá-lo como `null` têm o mesmo efeito; isso é pendência explícita, não imputação de data atual.
- Comparação de alternativas exige unidade, data-base e estimand presentes e iguais; caso contrário não há comparação numérica.
- Integração com C10/C08/C09 não está nesta PR (propriedade alheia). Status: `INTEGRATION_PENDING`.

## Arquivos

- `modules/decision_support.py`
- `tests/c13_decisions/`
- `docs/campaigns/MP-20260911/C13/`
