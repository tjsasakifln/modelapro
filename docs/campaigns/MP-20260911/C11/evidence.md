# C11 evidence — projetos e execuções recuperáveis com isolamento local

Campaign: C11  
Contract: MP/1  
Base: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`  
Head (implementation): `16778f2382a2fc5b1e2cecbd6f15ade9ebf5f5b3`  
PR: https://github.com/tjsasakifln/modelapro/pull/12  
Branch: `mp-20260911/c11-persistencia_execucoes`  
Python: 3.12.3  
Store: stdlib `sqlite3` + atomic JSON/bytes under an injectable root (default `MODELA_STORE_ROOT` or `~/.local/share/modelapro/store`). Tests use `tmp_path` only.

## What shipped

- `modules.job_store.JobStore`: `create` / `get` / `update_transition` / `save_snapshot` / `get_snapshot`
- `modules.project_store.ProjectStore`: `save_revision` / `load_revision`
- `modules.local_task_runner.LocalTaskRunner`: `submit(job_id, callable)` / `cancel(job_id)`
- `/ws` scoped to `job_id` + local `access_token`; light progress only; dead sockets pruned
- Global result/PDF broadcast removed from `WebSocketNotifier.send_notification`
- `_json_safe` preserved

Additive adapters used by C10 (do not change frozen names): `payload=` on `create`, `created` flag, `get_by_idempotency_key`, `interrupt_stale_running`, `list_by_state`, `save_artifact` / `get_artifact`, `patch_record`, `LocalTaskRunner()` defaulting to `JobStore.default()`, `is_cancelled` / `cancelled_ids`, `ProjectStore.list`, `load_revision` returns `None` when missing.

## Commands

| command | exit |
|---|---|
| `python3 -m pytest tests/c11_persistence/ -q` (run 1) | 0 (39 passed) |
| `python3 -m pytest tests/c11_persistence/ -q` (run 2) | 0 (39 passed) |
| fresh-process import of JobStore/ProjectStore/LocalTaskRunner | 0 |
| `python3 -m pytest tests/c11_persistence/test_a04_ws_isolation.py -q` | 0 (6 passed) |
| `python3 -m pytest tests/test_audit_fixes.py tests/test_api.py -q` | 1 (see C16) |

Scratch logs (session, not committed): `c11-pytest-1.log`, `c11-pytest-2.log`, `c11-fresh-import.log`, `c11-ws-isolation.log`, `c11-legacy-suite.log`.

## Acceptance mapping

- **C11-A01.** `create` persists identity; `save_snapshot`/`get`/`get_snapshot` work with no WebSocket. Terminal jobs remain queryable after store reopen. Snapshot lives at `jobs/<id>/snapshot.json`, not a second `result.json`.
- **C11-A02.** Reopening the store reloads immutable revisions. Abandoned `running` becomes `interrupted` and never `succeeded` without a stored snapshot. Complete idempotency key reuses; incomplete keys create a new job. No `resume_search`. First `JobStore()` in the process is `JobStore.default()`; `recover_on_open` runs once per root so `/ws` does not interrupt a live running job.
- **C11-A03.** CAS `update_transition` rejects illegal/stale changes. Cancel queued never starts the callable. Cancel running sets a cooperative flag the callable observes. Concurrent cancel vs complete yields one legal terminal state and no live worker. Calculation `state` is distinct from `artifact_states`. Progress is `null` or `[0, 1]`. Runner `max_workers` default 1; `shutdown` refuses new submits.
- **C11-A04.** Two connections for different jobs never cross. Light payloads omit PDF/snapshot/model_metrics. Dead `send_text` removes the socket and does not raise into the runner. Unscoped `send_notification` is dropped. `/ws` requires local token (not a cloud account). `tests/c11_persistence/test_a02_a04_live_ws_does_not_interrupt.py` constructs `JobStore()` (not `configure_default`), leaves a job `running`, then hits `JobStore.default()` and TestClient `/ws` and asserts the job stays `running`.
- **C11-A05.** Truncated sidecar does not clobber snapshot. Unknown storage schema refuses to open and leaves rows intact. Path traversal and `model_object` / pickle bytes are rejected; `get_snapshot` returns `None` for a pickle file (never `pickle.loads`). Tests run in a temporary directory.

## Known integration gaps (not C11 write-scope)

- C10 `POST /jobs` 202 does not yet return `access_token` / `ws_url` (C09 needs them).
- C09 still opens `ws://127.0.0.1:8000/ws` without credentials.
- C16 `test_send_notification_delivers_realistic_completed_payload` asserts global broadcast to `active_connections`. C11 must not restore that broadcast. `_json_safe` still round-trips datetime/numpy/non-finite floats.

## Self-review

- Identity transition `running -> running` is a patch (C10 ingest stage). `queued -> failed` is allowed so a job that never starts can fail without fabricating success.
- `JobStore()` now adopts as process default; automatic abandoned recovery is once per root. Explicit `recover_abandoned` / `interrupt_stale_running` still always run (process restart).
- No mid-search resume: abandoned running is interrupted even if a snapshot already exists (snapshot remains queryable).
- Default store is outside the repo. Tests never delete user data.
- New pip dependencies: none (`sqlite3` / `json` / `threading` stdlib).
