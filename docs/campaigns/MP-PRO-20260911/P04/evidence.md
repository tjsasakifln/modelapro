# P04 evidence

`BASE_SHA=6d54f902b85a5a37bfbf154d39f74cf854ff9b2b`
PR #17 (`mp-20260911/integracao-final`) remained open/draft against `main` `c92949e4`. Worktree: branch `mp-pro-20260911/p04-referencia-consolidacao`. PR de consolidação: [#20](https://github.com/tjsasakifln/modelapro/pull/20).

HEAD deste texto é gravado no comentário da PR **depois** do commit.

## What the evaluator can already do better

- Compare a pinned identity OLS against an independent QR + Student-t 80% mean CI and prediction interval that does not import the product helper.
- Replay eight labelled synthetic situations (missing target, locale/Excel, unit/date pending, holdout, influence exclusion, extrapolation probe, save/restore/batch, 210-row PDF/dossiê).
- Reuse P01 residual/grade canonical field, P02 four-step routine, P03 technical minute — on one consolidating branch.
- See CI on PRs against `integracao-final` and this consolidation branch.

## Cycle problems closed

- P04-A01: independent numeric reference on BASE_SHA (43 passed × 2).
- P04-A02: metrics distinguish machine time, robot actions, and unrun human time.
- P04-A03: previous incorporation of P01 `18a2dc0` / P02 `a0b4b4a` / P03 `4cb6937` **invalidated** (REOPENED). Current SEALED merged `--no-ff`: P01 `ec691bd`, P03 `ec7b8db`, P02 `b8e846c`. No writes to main/#17/producer branches.
- P04-A04: HTTP/worker/PDF/mutation/restore/batch (104 passed × 2 on `200816f`). Playwright+Chromium installed locally; composed browser path passed in `tests/pro_workflow/p04` (29 passed including browser). Screenshot: combined-browser.png.
- P04-A05: C18 triggers fire. GHA on `f4842ca2c187608df23666bd66a8f36a22142ad5` (contains current SEALED P01 `ec691bd`, P02 `b8e846c`, P03 `ec7b8db`) runs [34660498699](https://github.com/tjsasakifln/modelapro/actions/runs/34660498699) (pull_request) and [34660495596](https://github.com/tjsasakifln/modelapro/actions/runs/34660495596) (push) **success**. Wide suite **704 passed / 1 skipped**. Local combined 113 passed; wheel_eval_ok ~735000 from site-packages. Prior COMBINED on `b0391bd` does not count (REOPENED producer HEADs).

## What remains

- Human pilot 5–10 authorized real cases: **not run**.
- Absolute readiness / full NBR / Windows PDF: **not claimed**.
- STATUS=`COMBINED_INCREMENT_VERIFIED` on the current-SEALED composition (GHA-green `f4842ca`). Prior COMBINED on `b0391bd` stays invalidated. This status does **not** authorize merge or laudo.

## Commands and exit codes

Empty `PYTHONPATH` throughout.

| when | sha | command | exit | passed |
| --- | --- | --- | --- | --- |
| BASE_SHA diagnosis pass 1 | `6d54f90` product + P04 tests | `python3 -m pytest tests/pro_workflow/p04 tests/c15_packaging/test_ci_aggregator.py tests/c15_packaging/test_workflow_triggers.py -q --tb=line` | 0 | 43 |
| BASE_SHA diagnosis pass 2 | same | same | 0 | 43 |
| P01+P02 candidate | `ea84d18db27b1ff639e965bd66b7705e1d001385` | `python3 -m pytest tests/pro_workflow/p04 tests/pro_workflow/p01 tests/pro_workflow/p02 tests/c15_packaging/test_ci_aggregator.py tests/c15_packaging/test_workflow_triggers.py -q --tb=line` | 0 | 86 |
| combined pass 1 | `200816f363661b9fcc46f34cb7e5660571a4d441` | `python3 -m pytest tests/pro_workflow/p04 tests/pro_workflow/p01 tests/pro_workflow/p02 tests/pro_workflow/p03 tests/c15_packaging/test_ci_aggregator.py tests/c15_packaging/test_workflow_triggers.py -q --tb=line` | 0 | 104 |
| combined pass 2 | `200816f363661b9fcc46f34cb7e5660571a4d441` | same | 0 | 104 |
| wheel | composed tree | `python3 scripts/pro_workflow/wheel_eval.py --output DIR/wheel-eval-combined.log` | 0 | point 735000 in site-packages |

CI trigger (first increment SHA `079b05d`): GHA runs `34650664816` (pull_request) and `34650605102` (push) **success**.

GHA combined increment SHA `32bd871`: runs `34656286986` (pull_request) and `34656279956` (push) **success**. Wide suite 696 passed, 1 skipped in 506.70s.

Playwright local (empty PYTHONPATH): `test_e2e_ui` + P02 A01 + `test_browser_composed` 3 passed in 68.98s after PDF-wait / server-side `/jobs` fix.

## Composition matrix

See `composition_matrix.json`.

| ID | PR | HEAD | SEALED | incorporated |
| --- | --- | --- | --- | --- |
| P01 | #19 | `ec691bd8d1cf05f2da31105f59a94bedfa80757f` | yes (prior `18a2dc0` REOPENED) | `--no-ff` |
| P02 | #18 | `b8e846c73e8d1ae5d9b3e83f377033e31ab6b618` | yes (prior `a0b4b4a` REOPENED) | `--no-ff` |
| P03 | #21 | `ec7b8dba2b4a0ff575a1933251f03801ffeea0a5` | yes (prior `4cb6937` REOPENED) | `--no-ff` |

## Metrics

Machine compute time is wall time of HTTP jobs. Automated actions are scripted. `human_active_time_s` is null. Robot clicks are not evaluator-hour savings.

## Next human act

Review PR #20 and decide use/merge. No extra planning campaign.
