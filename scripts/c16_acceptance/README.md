# C16 harness (for C17)

Run from the repository root against the SHA under test:

```bash
python scripts/c16_acceptance/run_harness.py --output c16_summary.json
```

Optional: `--sha <composite>` records the SHA C17 is certifying. The harness
invokes pytest on `tests/test_audit_fixes.py`, `tests/test_full_flow.py` and
`tests/acceptance/`.

Stdout always includes disjoint counts:

- `aprovados`
- `reprovados`
- `nao_executados` (assertion message contains `UNMET_DEPENDENCY:` or `NOT_RUN:`)
- `violacoes_a04_skip_xfail` (must stay 0 — skip/xfail is forbidden as fake green)

`contract-sim` tests are labeled in `tests/acceptance/classification.json` and
are not E2E evidence. READY_COMPONENT for C16 means this harness is executable
and the corpus/oracles are honest, not that F01–F16 production defects are gone.

PASS_E2E is C17's certificate against the same composite SHA.
