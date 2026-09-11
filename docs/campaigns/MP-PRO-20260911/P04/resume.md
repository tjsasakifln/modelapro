# Retomada da consolidação P04

Incorporação anterior (`18a2dc0` / `a0b4b4a` / `4cb6937`) foi invalidada
porque os produtores declararam REOPENED. Current SEALED já fundidos
`--no-ff` na branch P04:

- P01 #19 `ec691bd8d1cf05f2da31105f59a94bedfa80757f`
- P03 #21 `ec7b8dba2b4a0ff575a1933251f03801ffeea0a5`
- P02 #18 `b8e846c73e8d1ae5d9b3e83f377033e31ab6b618`

Se um produtor declarar REOPENED de novo, invalidar e repetir:

```text
git fetch origin
python scripts/pro_workflow/discover_prs.py --output docs/campaigns/MP-PRO-20260911/P04/composition_matrix.json
# Incorporar somente o novo HEAD SEALED na branch P04. Sem force-push nas produtoras.
PYTHONPATH= python3 -m pytest tests/pro_workflow/p04 tests/pro_workflow/p01 tests/pro_workflow/p02 tests/pro_workflow/p03 tests/c15_packaging/test_ci_aggregator.py tests/c15_packaging/test_workflow_triggers.py -q --tb=line
python scripts/pro_workflow/wheel_eval.py --output DIR/wheel-eval.log
```

Não há promessa de monitoramento contínuo. COMBINED só depois de A03–A05
no candidato que contém os HEADs SEALED vigentes.
