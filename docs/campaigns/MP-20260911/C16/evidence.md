# C16 evidence — oráculos independentes e aceitação adversarial

Campaign: C16  
Contract: MP/1  
Base: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`  
Branch: `mp-20260911/c16-oraculos_aceite_independente`  
Status: READY_COMPONENT (corpus/harness honest and executable; production defects F01–F16 are **not** claimed fixed).  
PASS_E2E: not claimed (C17 only, composite SHA).

## What C16 owns

Independent synthetic corpus, adversarial tests that import/call the real modules, HTTP/UI/PDF/project/lote acceptances, and a C17-runnable harness. No production files were edited.

## Corpus (C16-A01)

`tests/fixtures/independent/mapping.json` maps cenário → achado → observação esperada → critério → proprietário for F01–F16. All fixtures are synthetic (`SYNTHETIC.md`). Oracles live in `oracles.py` and never import production code.

Independent literals used as expected values:

- F01: 30 received rows, 25 observed `preco`; observed mean 127000 (1000 × mean of non-empty areas).
- F02: `R$ 1.234,56` → 1234.56 (pt-BR); `1,234.56` → 1234.56 (en-US); `1.234` is ambiguous without locale.
- F04: area 90 / 150 / 250 against sample [50, 100] → in_sample / extended / outside_extended; prices 90000 / 150000 / 250000 → in-sample vs outside-sample. The two axes are distinct. NBR 14653-2:2011 citation for the 0.5–2 band is **pending** (PDF not text-extractable in this tree).
- F12: `math.sqrt(0) == 0`. `ln(0)` remains undefined.
- F16: `candidate_cols=[]` authorizes no predictors.

## A02 transversal tests

`tests/test_audit_fixes.py::TestSqrtZeroIsDefined` now expects sqrt(0)=0 and keeps sqrt in the search space when the avaliando is 0. `tests/test_full_flow.py` observes exact raw observed-target n and rejects empty `candidate_cols` as “all columns”. These tests **fail** against `c92949e` — that is the baseline, not a reason to change the oracle.

## Harness (C16-A05)

```bash
python scripts/c16_acceptance/run_harness.py --output c16_summary.json
```

Two runs against this branch agreed:

| bucket | count |
| --- | --- |
| aprovados | 22 |
| reprovados | 21 |
| nao_executados | 16 |
| violacoes_a04 (skip/xfail) | 0 |
| total | 59 (disjoint) |

pytest twice: `37 failed, 22 passed` both times, exit 1. No skip/xfail.

Reprovados include the audited defects F01 (mean-imputed target, n=30 not 25), F02 (en-US parse), F04 (item 4 reports faixa only), F05 (auto-remove default), F12 (`sqrt` rejected at 0), F16 (`[]` treated as all columns), F13 (no GET `/jobs/{id}/result`).

Não executados are `UNMET_DEPENDENCY` / `NOT_RUN` (C10/C11/C12/C14/C15 exports, Python Playwright missing). They are not counted as aprovados.

Contract-sim tests are labeled `contract-sim` and are not E2E evidence.

## Live API (twice)

`uvicorn backend.api:app` on 18016 and 18017:

- GET `/health` → `{"status":"healthy"}`
- POST `/upload` with `market_minimal.csv` → 200 `Processing started` (no `job_id`)
- GET `/jobs/x/result` → 404

Consistent primary observable: ack-only upload; result is not recoverable without WebSocket.

UI E2E: `NOT_RUN:playwright import failed` (Node `npx playwright` exists; the Python package does not). No synthetic screenshot.

## Adversarial review of other lote artifacts

GitHub `tjsasakifln/modelapro` had **no published PRs** at review time. Local branches C01–C05, C07–C11, C13, C15 sit at the same SHA as the audited base (no extra commits). C06 worktree has unpublished edits to `modules/transformations.py` (not a PR): tests expect `failure_code` on `apply_transformation` while MP/1 keeps the 2-tuple seam; C06’s sqrt(0) success oracle **agrees** with C16-A02.

New discovery with owner (no extra C16 scope): `WebSocketNotifier` is a process-wide singleton and `send_notification` returns immediately when `active_connections` is empty, so a completed job is discarded unless a socket is live — owner **C11** (F13).

## READY_COMPONENT meaning

C16 is ready as an independent corpus and harness. It does not certify the product. C17 must execute this same harness against the composite SHA.
