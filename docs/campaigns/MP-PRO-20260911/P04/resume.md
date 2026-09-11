# Retomada da consolidação P04

Usar quando P01/P02/P03 publicarem HEADs `SEALED` e esta campanha tiver
encerrado em `LOCAL_READY_COMPOSITION_PENDING`.

```text
cd /path/to/modela-pro-p04   # worktree de mp-pro-20260911/p04-referencia-consolidacao
git fetch origin
python scripts/pro_workflow/discover_prs.py --output docs/campaigns/MP-PRO-20260911/P04/composition_matrix.json
# Incorporar somente HEADs SEALED, ordem sugerida P01 → P03 → P02, na branch P04.
# Não escrever em main, mp-20260911/integracao-final, nem nas branches produtoras.
python scripts/pro_workflow/run.py --mode accept-candidate --output artifacts/p04-accept
python scripts/pro_workflow/wheel_eval.py --output artifacts/p04-accept/wheel-eval.log
```

Não há promessa de monitoramento contínuo. O trabalho independente
(corpus, oracle, runner, CI) permanece válido sem as três PRs.
