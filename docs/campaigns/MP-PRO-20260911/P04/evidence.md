# P04 evidence

`BASE_SHA=6d54f902b85a5a37bfbf154d39f74cf854ff9b2b`
PR #17 (`mp-20260911/integracao-final`) remained open/draft against `main` `c92949e4` at the start of this increment. Worktree: `/home/tjsasakifln/code/modela-pro-p04` on `mp-pro-20260911/p04-referencia-consolidacao`.

## What the evaluator can already do better on this increment

- Compare a pinned identity OLS (area) against an independent QR + Student-t 80% mean CI and prediction interval that does not import the product helper.
- Replay eight labelled synthetic situations (missing target, locale/Excel, unit/date pending, holdout partition, influence exclusion, extrapolation probe, save/restore/batch, 210-row PDF/dossiê) with a runner that records SHA and command.
- See CI on PRs against `integracao-final` and the P04 consolidation branch, with an aggregator that fails missing jobs.

## Cycle problems closed here

- Independent numeric reference for OLS identity (P04-A01).
- Measurement protocol that does not convert robot clicks into evaluator hours (P04-A02).
- C18 `pull_request` filter no longer limited to `main` (P04-A05 trigger).

## What remains

- P01/P02/P03 not published → P04-A03 composition pending.
- Combined browser + restore + mutation path on a composed candidate (P04-A04) pending SEALED HEADs.
- Human pilot 5–10 authorized real cases: **not run**.
- Absolute readiness: **not claimed**.

## Commands

```text
PYTHONPATH= python3 -m pytest tests/pro_workflow/p04 tests/c15_packaging/test_ci_aggregator.py tests/c15_packaging/test_workflow_triggers.py -q --tb=line
python scripts/pro_workflow/run.py --mode diagnose-base --output DIR
python scripts/pro_workflow/discover_prs.py --output docs/campaigns/MP-PRO-20260911/P04/composition_matrix.json
```

Two independent pytest passes on the BASE_SHA product tree (empty `PYTHONPATH`):

| pass | command | exit | passed |
| --- | --- | --- | --- |
| 1 | `PYTHONPATH= python3 -m pytest tests/pro_workflow/p04 tests/c15_packaging/test_ci_aggregator.py tests/c15_packaging/test_workflow_triggers.py -q --tb=line` | 0 | 43 |
| 2 | same | 0 | 43 |

SHA of the product code: `6d54f902b85a5a37bfbf154d39f74cf854ff9b2b`. The P04-owned tests/scripts sit on top of that tree. No skip/xfail. Extension tests wrote findings (`minimum_grade`, `formula`, `alias_conflict`) as absent on this SHA.

The git HEAD of the P04 commit is recorded in the PR comment after push, not inside that same commit.

## Composition matrix

See `composition_matrix.json`. At first discover: P01=P02=P03=`null`, `sealed=false`.

## Resume

`docs/campaigns/MP-PRO-20260911/P04/resume.md`
