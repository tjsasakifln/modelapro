# Retomada da consolidação P04

P01 #19, P02 #18 e P03 #21 já foram incorporados com `merge --no-ff`
após comentários SEALED. O próximo ato é humano: revisar PR #20.

Se um produtor declarar REOPENED, invalidar a incorporação anterior e
repetir:

```text
git fetch origin
python scripts/pro_workflow/discover_prs.py --output docs/campaigns/MP-PRO-20260911/P04/composition_matrix.json
# Incorporar somente o novo HEAD SEALED na branch P04. Sem force-push nas produtoras.
PYTHONPATH= python3 -m pytest tests/pro_workflow/p04 tests/pro_workflow/p01 tests/pro_workflow/p02 tests/pro_workflow/p03 -q --tb=line
python scripts/pro_workflow/wheel_eval.py --output DIR/wheel-eval.log
```

Não há promessa de monitoramento contínuo.
