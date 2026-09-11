# C17 — comando único de aceite

Registra o SHA **antes** de qualquer execução. Não injeta os simuladores
rotulados de `tests/c10_pipeline/doubles.py`.

```text
python scripts/c17_acceptance/run.py --output DIR
```

O script:

1. grava `git rev-parse HEAD` em `DIR/INTEGRATION_HEAD_SHA.txt`
2. corre `pytest tests/c17_integration -q` duas vezes
3. opcionalmente (`--full`) corre os testes por campanha e o harness C16

Ambiente esperado: venv C15 com `PYTHONPATH` vazio.

```text
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -c constraints/linux-py3.txt -e ".[dev]"
python scripts/c17_acceptance/run.py --output /tmp/c17-out
```
