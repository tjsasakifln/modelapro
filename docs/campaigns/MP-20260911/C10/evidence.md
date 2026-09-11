# C10 evidence — Contrato de resultado e composição real do processamento

Campaign: `C10`
Branch: `mp-20260911/c10-api_pipeline_contrato`
Base SHA: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`
Contract: `MP/1`

Synthetic fixtures only. No client PDFs, tokens, or real market spreadsheets.

## What shipped

- `modules/result_contract.py` — `validate_request_spec` / `freeze_result_snapshot` / RFC-8259 `dumps_strict`.
- `modules/results.py` — additive adapters for `DataLoadResult` / `ModelResult` / `ValidationResult` / `OptimalCombinationResult`, with explicit `LEGACY_CAPABILITY_GAPS`.
- `backend/worker.py` — composed path C01→C02→C05/C04/C03→C07→C13→C08/C12→C11. No `DataLoader.load_data` / `find_best_model` fallback. Per-job context. PDF failure does not unwind a frozen snapshot. Optional WS payload is job_id/state/stage/progress only.
- `backend/api.py` — MP/1 routes on JobStore/ProjectStore/LocalTaskRunner; fail-closed 503 when C11 is not importable; labeled doubles only in tests.

## Commands

```
python3 -m pytest tests/c10_pipeline/test_a01_contract.py -q
python3 -m pytest tests/c10_pipeline/test_a02_compose.py -q   # run twice
python3 -m pytest tests/c10_pipeline/test_a03_http.py -q      # run twice
python3 -m pytest tests/c10_pipeline/test_a04_isolation.py -q
python3 -m pytest tests/c10_pipeline/test_a05_security_peers.py -q
python3 -m pytest tests/test_api.py tests/c10_pipeline/ -q
C10_REPO=. python3 /tmp/grok-goal-76b230f431bd/implementer/c10_consumer.py
```

## Results (local)

| Command | Exit |
| --- | --- |
| A01 contract | 0 (16 passed) |
| A02 compose (run 1 and 2) | 0 (9 passed × 2) |
| A03 HTTP (run 1 and 2) | 0 (10 passed × 2) |
| A04 isolation | 0 (3 passed) |
| A05 security/peers | 0 (8 passed) |
| Full C10 selection | 0 (49 passed) |
| Fresh consumer import | 0 (`CONSUMER_OK 150000.0 preco`) |

Python: 3.12.3. pytest: 9.1.1.

A02 and A03 were executed twice; both runs exited 0.

## Observations that hold

- Valid freeze emits `schema_version` `"MP/1"` and RFC-8259 JSON (no NaN/Infinity/model objects).
- Non-finite / pandas values become Issue + JSON null, never 0.
- `value.point` is independent of `arbitration_interval`.
- Roles/target are visible on the first `ingest_market` call; categorical subject and `sample_ledger` survive the composed path.
- Calculation `succeeded` can coexist with `artifact_states["report.pdf"].state == "failed"`.
- POST `/jobs` returns 202; GET `/jobs/{id}/result` returns a snapshot or 409, never empty JSON as success.
- POST `/preview` does not call `search_models` / `evaluate_fitted` and does not write revisions.
- Idempotent resubmit does not call `search_models` a second time.
- Cancel uses the runner cancel path; search is not invoked after cancel.
- Two jobs on one store keep distinct snapshots and `frozen_project.json` bytes.
- Path traversal names are rejected by `_safe_artifact_name` (HTTP 400) or fail to match the artifact route (HTTP 404). Oversized uploads are 413. `candidate_cols=[]` is 400.
- Production modules do not define `JobStore` / `ingest_market` bodies. Labeled simulators carry `contract_simulator = True`.

## Unmet peers at audited SHA

`ingest_market`, `fit_dataset`, `transform_subject`, `search_models`, `evaluate_fitted`, `assess_normative`, `evaluate_procedure`, `render_report` (MP/1 signature), `build_evidence_bundle`, `recommend_next_actions`, `evaluate_batch` are not exported from main at `c92949e`. A C11 `JobStore` may exist in a parallel worktree; this PR does not vendor it. Production binds the frozen import paths and returns structured `PEER_UNAVAILABLE` / HTTP 503 when they are missing.

Status: `INTEGRATION_PENDING`. Not `PASS_E2E`.
