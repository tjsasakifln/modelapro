"""MP/1 HTTP surface (C10).

Routes use JobStore / ProjectStore / LocalTaskRunner from C11 when those
classes are importable. If they are missing, endpoints fail closed with a
structured 503 — this module does not ship an unlabeled in-process fake
store. Tests bind labeled contract doubles via bind_runtime().

CPU-bound composition is submitted to LocalTaskRunner; the event loop only
validates, reads a size-capped upload, and returns 202.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
from typing import Any, Callable, Dict, List, Mapping, Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .websocket import router as websocket_router
from .document_routes import router as document_router
from .recipient_routes import router as recipient_router
from .worker import (
    Worker,
    compose_preview,
    current_code_sha,
    missing_peers,
    peer_kind,
    resolve_peers,
    run_job,
    sha256_bytes,
)
from modules.config_manager import config
from modules.logging_manager import logger
from modules.result_contract import (
    ALLOWED_ARTIFACT_NAMES,
    DEGREE_MAX,
    DEGREE_MIN,
    JOB_STATES,
    MAX_UPLOAD_BYTES_DEFAULT,
    SCHEMA_VERSION,
    ContractError,
    RequestSpecError,
    dumps_strict,
    make_issue,
    request_spec_for_peers,
    subject_numeric_values_finite,
    validate_job_status_progress,
    validate_request_spec,
    fill_preview_spec,
)

try:
    import uvicorn
except ImportError:  # pragma: no cover - packaged separately
    uvicorn = None


class RuntimeBindings:
    """Process-local injection point. Production leaves these None."""

    job_store = None
    project_store = None
    task_runner = None
    peers = None
    loop = None
    submission_index: Dict[str, str] = {}


def bind_runtime(
    *,
    job_store=None,
    project_store=None,
    task_runner=None,
    peers=None,
    loop=None,
    reset_submissions: bool = True,
) -> None:
    if job_store is not None:
        RuntimeBindings.job_store = job_store
    if project_store is not None:
        RuntimeBindings.project_store = project_store
    if task_runner is not None:
        RuntimeBindings.task_runner = task_runner
    if peers is not None:
        RuntimeBindings.peers = dict(peers)
    if loop is not None:
        RuntimeBindings.loop = loop
    if reset_submissions:
        RuntimeBindings.submission_index = {}


def reset_runtime() -> None:
    RuntimeBindings.job_store = None
    RuntimeBindings.project_store = None
    RuntimeBindings.task_runner = None
    RuntimeBindings.peers = None
    RuntimeBindings.loop = None
    RuntimeBindings.submission_index = {}


def _cors_origins() -> List[str]:
    """C15 owns CORS_ORIGINS; C10 consumes the validated explicit list (never '*')."""
    return list(config.cors_origin_list())


def _max_upload_bytes() -> int:
    raw = os.getenv("MP_MAX_UPLOAD_BYTES")
    if not raw:
        return MAX_UPLOAD_BYTES_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        return MAX_UPLOAD_BYTES_DEFAULT
    return value if value > 0 else MAX_UPLOAD_BYTES_DEFAULT


def _issues_response(status_code: int, message: str, issues: List[dict], extra: Optional[dict] = None) -> JSONResponse:
    body = {
        "schema_version": SCHEMA_VERSION,
        "error": message,
        "issues": issues,
    }
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status_code, content=body)


def _import_c11():
    stores = {"JobStore": None, "ProjectStore": None, "LocalTaskRunner": None}
    errors = []
    try:
        from modules.job_store import JobStore

        stores["JobStore"] = JobStore
    except Exception as exc:
        errors.append(("modules.job_store.JobStore", str(exc)))
    try:
        from modules.project_store import ProjectStore

        stores["ProjectStore"] = ProjectStore
    except Exception as exc:
        errors.append(("modules.project_store.ProjectStore", str(exc)))
    try:
        from modules.local_task_runner import LocalTaskRunner

        stores["LocalTaskRunner"] = LocalTaskRunner
    except Exception as exc:
        errors.append(("modules.local_task_runner.LocalTaskRunner", str(exc)))
    return stores, errors


def _instantiate(cls, *args, **kwargs):
    if cls is None:
        return None
    try:
        return cls(*args, **kwargs)
    except TypeError:
        try:
            return cls()
        except TypeError:
            return None


def get_job_store():
    if RuntimeBindings.job_store is not None:
        return RuntimeBindings.job_store
    stores, _ = _import_c11()
    from modules.operacao_local.runtime import active_store_root
    root = active_store_root()
    instance = _instantiate(stores["JobStore"], root) if root else _instantiate(stores["JobStore"])
    if instance is None:
        return None
    RuntimeBindings.job_store = instance
    return instance


def get_project_store():
    if RuntimeBindings.project_store is not None:
        return RuntimeBindings.project_store
    stores, _ = _import_c11()
    from modules.operacao_local.runtime import active_store_root
    root = active_store_root()
    instance = _instantiate(stores["ProjectStore"], root) if root else _instantiate(stores["ProjectStore"])
    if instance is None:
        return None
    RuntimeBindings.project_store = instance
    return instance


def get_task_runner():
    if RuntimeBindings.task_runner is not None:
        return RuntimeBindings.task_runner
    stores, _ = _import_c11()
    cls = stores["LocalTaskRunner"]
    if cls is None:
        return None
    store = get_job_store()
    instance = _instantiate(cls, store) if store is not None else _instantiate(cls)
    if instance is None or not callable(getattr(instance, "submit", None)):
        return None
    RuntimeBindings.task_runner = instance
    return instance


def get_peers() -> Dict[str, Any]:
    if RuntimeBindings.peers is not None:
        return dict(RuntimeBindings.peers)
    return resolve_peers()


def c11_unavailable_issues() -> List[dict]:
    _, errors = _import_c11()
    issues = []
    for path, msg in errors:
        issues.append(
            make_issue(
                "PEER_UNAVAILABLE",
                f"{path} is not importable ({msg})",
                origin="c10.api",
                evidence={"path": path, "integration": "INTEGRATION_PENDING"},
            )
        )
    if not issues:
        issues.append(
            make_issue(
                "PEER_UNAVAILABLE",
                "C11 JobStore/ProjectStore/LocalTaskRunner unavailable",
                origin="c10.api",
            )
        )
    return issues


def recover_interrupted_jobs(job_store=None) -> int:
    """Jobs left 'running' across process restart become 'interrupted'."""
    store = job_store if job_store is not None else get_job_store()
    if store is None:
        return 0
    interrupt = getattr(store, "interrupt_stale_running", None) or getattr(
        store, "recover_abandoned", None
    )
    if callable(interrupt):
        result = interrupt()
        try:
            return int(len(result) if not isinstance(result, (int, float)) else result or 0)
        except (TypeError, ValueError):
            return 0
    lister = getattr(store, "list_by_state", None)
    if not callable(lister):
        return 0
    count = 0
    try:
        running = lister("running") or []
    except Exception:
        return 0
    for job in running:
        job_id = job.get("job_id") if isinstance(job, Mapping) else None
        if not job_id:
            continue
        try:
            store.update_transition(
                job_id,
                "running",
                "interrupted",
                patch={
                    "stage": "interrupted",
                    "result_available": False,
                    "issues": [
                        make_issue(
                            "INTERRUPTED_ON_RESTART",
                            "Job was running when the process restarted",
                            origin="c10.api",
                        )
                    ],
                },
            )
            count += 1
        except Exception:
            logger.warning("could not mark job %s interrupted", job_id)
    return count


def _safe_artifact_name(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise HTTPException(status_code=400, detail="artifact name required")
    if name != os.path.basename(name):
        raise HTTPException(status_code=400, detail="artifact path traversal rejected")
    if ".." in name or "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="artifact path traversal rejected")
    if name not in ALLOWED_ARTIFACT_NAMES:
        raise HTTPException(status_code=400, detail="artifact name is not on the local allow-list")
    return name


async def read_upload_limited(upload: UploadFile, max_bytes: int) -> bytes:
    chunks: List[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail={
                    "schema_version": SCHEMA_VERSION,
                    "error": "file too large",
                    "issues": [
                        make_issue(
                            "FILE_TOO_LARGE",
                            f"Upload exceeds {max_bytes} bytes",
                            origin="c10.api",
                            evidence={"max_bytes": max_bytes, "read": total},
                        )
                    ],
                },
            )
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(
            status_code=400,
            detail={
                "schema_version": SCHEMA_VERSION,
                "error": "empty file",
                "issues": [make_issue("EMPTY_FILE", "Uploaded file is empty", origin="c10.api")],
            },
        )
    from modules.operacao_local.security import UploadPolicy, validate_upload
    try:
        validate_upload(upload.filename or "", data, UploadPolicy(max_bytes=max_bytes))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": "INVALID_UPLOAD", "message": str(exc)}) from exc
    return data


def _parse_json_field(raw: Optional[str], *, field: str, allow_null: bool = False) -> Any:
    if raw is None or raw == "":
        if allow_null:
            return None
        raise HTTPException(
            status_code=400,
            detail={
                "schema_version": SCHEMA_VERSION,
                "error": f"{field} is required",
                "issues": [make_issue("MISSING_FIELD", f"{field} is required", origin="c10.api")],
            },
        )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "schema_version": SCHEMA_VERSION,
                "error": f"{field} is not valid JSON",
                "issues": [
                    make_issue(
                        "INVALID_JSON",
                        f"{field} JSON decode failed: {exc}",
                        origin="c10.api",
                        evidence={"field": field},
                    )
                ],
            },
        ) from exc


def _validate_spec_or_400(payload: Any) -> dict:
    try:
        return validate_request_spec(payload)
    except RequestSpecError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "schema_version": SCHEMA_VERSION,
                "error": str(exc),
                "issues": exc.issues,
            },
        ) from exc
    except ContractError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "schema_version": SCHEMA_VERSION,
                "error": str(exc),
                "issues": exc.issues,
            },
        ) from exc


def _require_c11():
    job_store = get_job_store()
    runner = get_task_runner()
    if job_store is None or runner is None:
        raise HTTPException(
            status_code=503,
            detail={
                "schema_version": SCHEMA_VERSION,
                "error": "C11 JobStore/LocalTaskRunner unavailable",
                "issues": c11_unavailable_issues(),
                "integration": "INTEGRATION_PENDING",
            },
        )
    return job_store, runner


def submission_key(file_bytes: bytes, request_spec: Mapping[str, Any], subject: Any) -> str:
    h = hashlib.sha256()
    h.update(file_bytes)
    h.update(b"\0")
    h.update(dumps_strict(request_spec_for_peers(request_spec)).encode("utf-8"))
    h.update(b"\0")
    h.update(dumps_strict(subject if subject is not None else {}).encode("utf-8"))
    h.update(b"\0")
    h.update(str(current_code_sha() or "").encode("utf-8"))
    try:
        from modules.pro_workflow.residual_state import CALCULATION_VERSION

        h.update(b"\0")
        h.update(str(CALCULATION_VERSION).encode("utf-8"))
    except Exception:
        pass
    return h.hexdigest()


def request_spec_from_upload_form(
    *,
    degree: int,
    target_col: str,
    candidate_cols: Any,
    solicitante: str,
    finalidade: str,
    grau_item1: Optional[int],
    grau_item3: Optional[int],
) -> dict:
    """Compatibility adapter from the legacy /upload form into RequestSpec."""
    if not isinstance(degree, int) or isinstance(degree, bool) or degree < DEGREE_MIN or degree > DEGREE_MAX:
        raise HTTPException(
            status_code=400,
            detail={
                "schema_version": SCHEMA_VERSION,
                "error": "degree out of range",
                "issues": [
                    make_issue(
                        "DEGREE_OUT_OF_RANGE",
                        f"degree={degree} is outside {DEGREE_MIN}..{DEGREE_MAX}",
                        origin="c10.api",
                        evidence={"degree": degree},
                    )
                ],
            },
        )
    for label, value in (("grau_item1", grau_item1), ("grau_item3", grau_item3)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > DEGREE_MAX):
            raise HTTPException(
                status_code=400,
                detail={
                    "schema_version": SCHEMA_VERSION,
                    "error": f"{label} out of range",
                    "issues": [
                        make_issue(
                            "DEGREE_OUT_OF_RANGE",
                            f"{label}={value} is outside {DEGREE_MIN}..{DEGREE_MAX}",
                            origin="c10.api",
                        )
                    ],
                },
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "target_col": target_col,
        "candidate_cols": candidate_cols,
        "roles": {target_col: "target"},
        "units": {},
        "import_options": {"locale": "auto", "delimiter": None, "encoding": None},
        "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
        "outlier_policy": {"mode": "report_only", "reviewed_exclusions": []},
        "search_policy": {
            "mode": "legacy_upload_adapter",
            "budget": None,
            "objective": "target_degree",
            "seed": None,
            "target_degree": degree,
            "minimum_fundamentacao_grade": degree,
        },
        "evaluation_policy": {
            "method": "none",
            "partitions": None,
            "groups": None,
            "seed": None,
        },
        "reference_date": None,
        "inspection_date": None,
        "target_unit": "",
        "applicant": solicitante or "",
        "purpose": finalidade or "",
        "declared_documentary": {
            "item1_grade": grau_item1,
            "item3_grade": grau_item3,
        },
    }


def _create_job_record(store, *, idempotency_key: str, project_id: Optional[str], payload: dict) -> dict:
    existing = RuntimeBindings.submission_index.get(idempotency_key)
    if existing:
        current = store.get(existing)
        if current is not None:
            return {"job_id": existing, "state": current.get("state"), "created": False}

    finder = getattr(store, "get_by_idempotency_key", None)
    if callable(finder):
        found = finder(idempotency_key)
        if found:
            job_id = found.get("job_id") if isinstance(found, Mapping) else None
            if job_id:
                RuntimeBindings.submission_index[idempotency_key] = job_id
                return {"job_id": job_id, "state": found.get("state"), "created": False}

    kwargs = {
        "idempotency_key": idempotency_key,
        "project_id": project_id,
        "payload": payload,
        "request_spec": (payload or {}).get("request_spec"),
        "input_sha256": (payload or {}).get("input_sha256"),
        "code_sha": (payload or {}).get("code_sha"),
        "revision_id": (payload or {}).get("revision_id"),
    }
    try:
        signature = inspect.signature(store.create)
        if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()):
            kwargs = {k: v for k, v in kwargs.items() if k in signature.parameters}
    except (TypeError, ValueError):
        pass
    created = store.create(**kwargs)
    if not isinstance(created, Mapping) or "job_id" not in created:
        raise HTTPException(status_code=500, detail="JobStore.create did not return job_id")
    job_id = created["job_id"]
    if created.get("created") is False:
        is_new = False
    elif job_id in RuntimeBindings.submission_index.values():
        is_new = False
    elif created.get("result_available"):
        is_new = False
    elif created.get("state") not in (None, "queued"):
        is_new = False
    else:
        is_new = True
    RuntimeBindings.submission_index[idempotency_key] = job_id
    return {
        "job_id": job_id,
        "state": created.get("state") or "queued",
        "created": is_new,
        # A newly created job has no other authenticated way for its caller to
        # learn this capability.  Replays deliberately use the guarded token
        # recovery endpoint instead of returning the stored secret again.
        "access_token": created.get("access_token") if is_new else None,
    }


def _cancel_flag(job_store, runner, job_id: str) -> Callable[[], bool]:
    def cancel_requested() -> bool:
        if runner is not None:
            cancelled = getattr(runner, "cancelled_ids", None)
            if callable(cancelled) and job_id in (cancelled() or []):
                return True
            flag = getattr(runner, "is_cancelled", None)
            if callable(flag) and flag(job_id):
                return True
            cr = getattr(runner, "cancel_requested", None)
            if callable(cr) and cr(job_id):
                return True
        if job_store is not None:
            job = job_store.get(job_id)
            if isinstance(job, Mapping) and job.get("state") == "cancelled":
                return True
        return False

    return cancel_requested


def _submit_valuation(
    *,
    job_id: str,
    file_bytes: bytes,
    filename: str,
    request_spec: dict,
    subject_raw: Optional[dict],
    project_id: Optional[str],
    job_store,
    runner,
) -> None:
    peers = get_peers()
    loop = RuntimeBindings.loop

    def callable_job(cancel_requested=None):
        flag = cancel_requested or _cancel_flag(job_store, runner, job_id)
        return run_job(
            job_id=job_id,
            file_bytes=file_bytes,
            filename=filename,
            request_spec=request_spec,
            subject_raw=subject_raw,
            project_id=project_id,
            peers=peers,
            job_store=job_store,
            cancel_requested=flag,
            loop=loop,
        )

    runner.submit(job_id, callable_job)


def _job_status_body(job: Mapping[str, Any]) -> dict:
    progress = job.get("progress")
    try:
        progress = validate_job_status_progress(progress)
    except ContractError:
        progress = None
    state = job.get("state")
    if state not in JOB_STATES:
        # Do not invent a state; surface whatever C11 stored plus an issue.
        pass
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": job.get("job_id"),
        "project_id": job.get("project_id"),
        "state": state,
        "stage": job.get("stage"),
        "progress": progress,
        "result_available": bool(job.get("result_available")),
        "artifact_states": job.get("artifact_states") or {},
        "issues": job.get("issues") or [],
        "calculation_state": job.get("calculation_state"),
    }


app = FastAPI(
    title=config.APP_NAME,
    description="API for CONFENGE MODELA PRO (MP/1)",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=os.getenv("MP_CORS_ALLOW_CREDENTIALS", "true").lower() == "true",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(websocket_router)
app.include_router(document_router)
app.include_router(recipient_router)

from .local_guard import LocalRequestGuard
app.add_middleware(LocalRequestGuard)

worker = Worker()


@app.on_event("startup")
async def _on_startup():
    RuntimeBindings.loop = asyncio.get_running_loop()
    recover_interrupted_jobs()


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/operations/license")
async def current_license():
    from modules.operacao_local.runtime import license_decision
    from modules.commercial_license import trust_anchor_metadata
    decision = license_decision()
    return {"signature_valid": decision.valid_signature, "expired": decision.expired,
            "calculate": decision.permits("calculate"), "reason": decision.reason,
            "artifact_trust": trust_anchor_metadata()}


@app.post("/operations/license")
async def import_buyer_license(request: Request):
    from modules.commercial_license import install_license, trusted_vendor_public_key
    from modules.operacao_local.runtime import runtime_root
    body = await request.body()
    if len(body) > 65536:
        raise HTTPException(413, "license envelope exceeds limit")
    try:
        install_license(json.loads(body), trusted_vendor_public_key(),
                        os.environ.get("MODELA_LICENSE_PATH") or runtime_root() / "entitlement.json")
    except (ValueError, TypeError, OSError) as exc:
        raise HTTPException(400, "invalid buyer entitlement") from exc
    return await current_license()


@app.get("/operations/backup")
async def export_workspace_backup():
    import io
    from pathlib import Path
    import tempfile
    import zipfile
    store = get_job_store()
    if store is None:
        raise HTTPException(503, "store unavailable")
    def export():
        with tempfile.TemporaryDirectory(prefix="modelapro-backup-") as temporary:
            backup = store.export_backup(Path(temporary) / "backup")
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(backup.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(backup).as_posix())
            return output.getvalue()
    payload = await asyncio.to_thread(export)
    return Response(payload, media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="modelapro-backup.zip"'})


@app.post("/operations/restore")
async def restore_workspace_backup(file: UploadFile = File(...)):
    import io
    from pathlib import Path
    import secrets
    import tempfile
    import zipfile
    from modules.job_store import JobStore, atomic_write_json
    from modules.project_store import ProjectStore
    from modules.operacao_local.runtime import runtime_root
    from modules.operacao_local.security import UploadPolicy, validate_upload
    store = get_job_store()
    if store is None or store.list_jobs():
        raise HTTPException(409, "restore requires an empty workspace; existing evidence is preserved")
    content = await file.read(100 * 1024 * 1024 + 1)
    try:
        validate_upload(file.filename or "", content, UploadPolicy(
            allowed_extensions=frozenset({".zip"}), max_bytes=100 * 1024 * 1024,
            max_zip_members=10000, max_uncompressed_bytes=500 * 1024 * 1024,
            max_compression_ratio=1000))
        relative = "restored-stores/" + secrets.token_hex(16)
        destination = runtime_root() / relative
        with tempfile.TemporaryDirectory(prefix="modelapro-restore-") as temporary:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                archive.extractall(temporary)  # Every member was checked above, before extraction.
            restored = JobStore.restore_backup(Path(temporary), destination)
        atomic_write_json(runtime_root() / "restored-store.json", {"relative_path": relative})
        JobStore.configure_default(destination, recover_abandoned=False)
        bind_runtime(job_store=restored, project_store=ProjectStore(destination))
        RuntimeBindings.task_runner = None
    except (ValueError, OSError) as exc:
        raise HTTPException(400, "backup integrity verification failed") from exc
    return {"status": "restored", "job_count": len(restored.list_jobs())}


@app.post("/preview")
async def preview(
    file: UploadFile = File(...),
    request_json: str = Form(...),
    subject_json: Optional[str] = Form(None),
):
    """Ingest-only. Does not search, fit candidates, or write project revisions."""
    spec_payload = _parse_json_field(request_json, field="request_json")
    try:
        spec = fill_preview_spec(spec_payload)
    except (RequestSpecError, ContractError) as exc:
        return _issues_response(400, str(exc), getattr(exc, "issues", None) or [
            make_issue("INVALID_SPEC", str(exc), origin="c10.api")
        ])
    subject = _parse_json_field(subject_json, field="subject_json", allow_null=True) if subject_json else None
    ok, issues = subject_numeric_values_finite(subject)
    if not ok:
        return _issues_response(400, "subject contains non-finite numbers", issues)
    file_bytes = await read_upload_limited(file, _max_upload_bytes())
    filename = file.filename or "upload.bin"
    peers = get_peers()
    missing = missing_peers(peers, ("ingest_market",))
    if missing:
        return _issues_response(
            503,
            "ingest_market unavailable",
            [
                make_issue(
                    "PEER_UNAVAILABLE",
                    "preview requires modules.data_loader.ingest_market",
                    origin="c10.api",
                    evidence={"missing": missing, "integration": "INTEGRATION_PENDING"},
                )
            ],
            extra={"integration": "INTEGRATION_PENDING"},
        )

    def _run():
        return compose_preview(
            file_bytes=file_bytes,
            filename=filename,
            request_spec=spec,
            subject_raw=subject,
            peers=peers,
        )

    try:
        result = await asyncio.to_thread(_run)
    except Exception as exc:
        issues = getattr(exc, "issues", None) or [
            make_issue("PREVIEW_FAILED", str(exc), origin="c10.api")
        ]
        return _issues_response(422, "preview failed", list(issues))
    return JSONResponse(status_code=200, content=result)


@app.post("/jobs")
async def create_job(
    file: Optional[UploadFile] = File(None),
    request_json: str = Form(...),
    subject_json: Optional[str] = Form(None),
    project_id: Optional[str] = Form(None),
):
    spec_payload = _parse_json_field(request_json, field="request_json")
    spec = _validate_spec_or_400(spec_payload)
    subject = _parse_json_field(subject_json, field="subject_json", allow_null=True) if subject_json else None
    ok, issues = subject_numeric_values_finite(subject)
    if not ok:
        return _issues_response(400, "subject contains non-finite numbers", issues)
    is_cost = (spec.get("qualification_profile") or {}).get("id") == "abnt-14653-2-custo-reedicao"
    if file is None:
        if not is_cost or not isinstance(spec.get("cost_bom"), Mapping):
            raise HTTPException(400, "market sample is required outside the cost workflow")
        file_bytes, filename = b"", "cost-bom.json"
    else:
        if is_cost:
            raise HTTPException(400, "cost inputs belong in cost_bom, not a regression sample")
        file_bytes = await read_upload_limited(file, _max_upload_bytes())
        filename = file.filename or "upload.bin"
    job_store, runner = _require_c11()
    key = submission_key(file_bytes, spec, subject)
    payload = {
        "filename": filename,
        "project_id": project_id,
        "input_sha256": sha256_bytes(file_bytes),
        "code_sha": current_code_sha(),
        "request_spec": request_spec_for_peers(spec),
    }
    record = _create_job_record(
        job_store, idempotency_key=key, project_id=project_id, payload=payload
    )
    job_id = record["job_id"]
    if record.get("created"):
        _submit_valuation(
            job_id=job_id,
            file_bytes=file_bytes,
            filename=filename,
            request_spec=spec,
            subject_raw=subject,
            project_id=project_id,
            job_store=job_store,
            runner=runner,
        )
    return JSONResponse(
        status_code=202,
        content={
            "schema_version": SCHEMA_VERSION,
            "job_id": job_id,
            "status_url": f"/jobs/{job_id}",
            "result_url": f"/jobs/{job_id}/result",
            "state": record.get("state") or "queued",
            "idempotent_replay": not record.get("created"),
            "access_token": record.get("access_token"),
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job_store, _runner = _require_c11()
    job = job_store.get(job_id)
    if job is None:
        return _issues_response(
            404,
            "job not found",
            [make_issue("JOB_NOT_FOUND", f"job {job_id} not found", origin="c10.api")],
        )
    return JSONResponse(status_code=200, content=_job_status_body(job))


@app.get("/jobs/{job_id}/result")
async def get_job_result(
    job_id: str,
    access_token: Optional[str] = Header(None, alias="X-Job-Token"),
    expected_fingerprint: Optional[str] = None,
):
    job_store, _runner = _require_c11()
    job = job_store.get(job_id)
    if job is None:
        return _issues_response(
            404,
            "job not found",
            [make_issue("JOB_NOT_FOUND", f"job {job_id} not found", origin="c10.api")],
        )
    if access_token:
        verify = getattr(job_store, "verify_access", None)
        if callable(verify) and not verify(job_id, access_token):
            return _issues_response(
                403,
                "invalid access token",
                [make_issue(
                    "INVALID_ACCESS_TOKEN",
                    "access_token does not match the job",
                    origin="c10.api",
                    evidence={"job_id": job_id},
                )],
            )
    snapshot = job_store.get_snapshot(job_id)
    if snapshot is None:
        return _issues_response(
            409,
            "result not available",
            job.get("issues")
            or [
                make_issue(
                    "RESULT_NOT_AVAILABLE",
                    f"job {job_id} has no frozen snapshot (state={job.get('state')})",
                    origin="c10.api",
                    evidence={"state": job.get("state"), "stage": job.get("stage")},
                )
            ],
            extra={
                "job_id": job_id,
                "state": job.get("state"),
                "result_available": False,
            },
        )
    if expected_fingerprint:
        qc = ((snapshot.get("provenance") or {}).get("qualification_context") or {})
        fp = qc.get("result_fingerprint")
        if not fp or fp != expected_fingerprint:
            return _issues_response(
                409,
                "fingerprint mismatch",
                [make_issue(
                    "FINGERPRINT_MISMATCH",
                    "expected_fingerprint does not match the frozen result",
                    origin="c10.api",
                    evidence={
                        "job_id": job_id,
                        "expected": expected_fingerprint,
                        "observed": fp,
                    },
                )],
                extra={"job_id": job_id, "result_fingerprint": fp},
            )
    return JSONResponse(status_code=200, content=snapshot)


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    job_store, runner = _require_c11()
    job = job_store.get(job_id)
    if job is None:
        return _issues_response(
            404,
            "job not found",
            [make_issue("JOB_NOT_FOUND", f"job {job_id} not found", origin="c10.api")],
        )
    cancel = getattr(runner, "cancel", None)
    if callable(cancel):
        cancel(job_id)
    expected = job.get("state") or "running"
    try:
        job_store.update_transition(
            job_id,
            expected,
            "cancelled",
            patch={"stage": "cancelled"},
        )
    except Exception as exc:
        logger.warning("cancel transition failed for %s: %s", job_id, exc)
        # Runner cancel still stands so C05 cancel_requested can observe it.
    return JSONResponse(
        status_code=200,
        content={"schema_version": SCHEMA_VERSION, "job_id": job_id, "state": "cancelled"},
    )


@app.post("/jobs/{job_id}/access-token")
async def recover_job_access_token(job_id: str):
    # LocalGuard authenticates the workspace bearer + Origin + CSRF before this
    # endpoint. Recovery never places a credential in an URL or access log.
    store, _runner = _require_c11()
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return JSONResponse({"access_token": job["access_token"]},
                        headers={"Cache-Control": "no-store"})


@app.get("/jobs/{job_id}/artifacts/{name}")
async def get_job_artifact(job_id: str, name: str):
    try:
        safe = _safe_artifact_name(name)
    except HTTPException:
        raise
    job_store, _runner = _require_c11()
    job = job_store.get(job_id)
    if job is None:
        return _issues_response(
            404,
            "job not found",
            [make_issue("JOB_NOT_FOUND", f"job {job_id} not found", origin="c10.api")],
        )
    getter = getattr(job_store, "get_artifact", None)
    try:
        data = getter(job_id, safe) if callable(getter) else None
    except Exception as exc:
        if exc.__class__.__name__ in {"PathEscapeError", "HTTPException"}:
            return _issues_response(
                400,
                "artifact path traversal rejected",
                [make_issue("PATH_TRAVERSAL", str(exc), origin="c10.api")],
            )
        raise
    if not data:
        return _issues_response(
            404,
            "artifact not found",
            [make_issue("ARTIFACT_NOT_FOUND", f"{safe} is not available", origin="c10.api")],
        )
    if safe.endswith(".pdf"):
        media = "application/pdf"
    elif safe.endswith(".zip"):
        media = "application/zip"
    elif safe.endswith(".docx"):
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        media = "application/json"
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{safe}"', "Cache-Control": "no-store"})


@app.get("/projects")
async def list_projects():
    store = get_project_store()
    if store is None:
        return _issues_response(
            503,
            "ProjectStore unavailable",
            c11_unavailable_issues(),
            extra={"integration": "INTEGRATION_PENDING"},
        )
    lister = getattr(store, "list", None)
    items = lister() if callable(lister) else []
    return {"schema_version": SCHEMA_VERSION, "projects": items or []}


@app.get("/projects/{project_id}")
async def get_project(project_id: str):
    store = get_project_store()
    if store is None:
        return _issues_response(
            503,
            "ProjectStore unavailable",
            c11_unavailable_issues(),
            extra={"integration": "INTEGRATION_PENDING"},
        )
    loader = getattr(store, "load_revision", None)
    if not callable(loader):
        return _issues_response(
            503,
            "ProjectStore.load_revision unavailable",
            [make_issue("PEER_UNAVAILABLE", "load_revision missing", origin="c10.api")],
        )
    try:
        revision = loader(project_id, None)
    except Exception as exc:
        if exc.__class__.__name__ in {"ProjectNotFound", "RevisionNotFound"}:
            return _issues_response(
                404,
                "project not found",
                [make_issue("PROJECT_NOT_FOUND", str(exc), origin="c10.api")],
            )
        raise
    if revision is None:
        return _issues_response(
            404,
            "project not found",
            [make_issue("PROJECT_NOT_FOUND", f"project {project_id} not found", origin="c10.api")],
        )
    return {"schema_version": SCHEMA_VERSION, "project_id": project_id, "revision": revision}


@app.post("/projects/{project_id}/revisions")
async def save_project_revision(project_id: str, request: Request):
    store = get_project_store()
    if store is None:
        return _issues_response(
            503,
            "ProjectStore unavailable",
            c11_unavailable_issues(),
            extra={"integration": "INTEGRATION_PENDING"},
        )
    try:
        payload = await request.json()
    except Exception:
        return _issues_response(
            400,
            "invalid JSON body",
            [make_issue("INVALID_JSON", "revision payload is not valid JSON", origin="c10.api")],
        )
    if not isinstance(payload, Mapping):
        return _issues_response(
            400,
            "revision payload must be a mapping",
            [make_issue("TYPE_ERROR", "revision payload must be a mapping", origin="c10.api")],
        )
    payload = dict(payload)
    snapshot_ref = payload.get("snapshot_ref") or {}
    if not isinstance(snapshot_ref, Mapping):
        raise HTTPException(400, "snapshot_ref must be an object")
    linked_job = payload.get("job_id") or snapshot_ref.get("job_id")
    if payload.get("job_id") and snapshot_ref.get("job_id") not in (None, payload["job_id"]):
        raise HTTPException(409, "revision refers to different jobs")
    if linked_job:
        jobs = get_job_store()
        record = jobs.get(linked_job) if jobs is not None else None
        frozen_bytes = jobs.get_artifact(linked_job, "frozen_project.json") if record else None
        snapshot = jobs.get_snapshot(linked_job) if record else None
        if frozen_bytes is None or snapshot is None:
            raise HTTPException(409, "linked job needs a persisted snapshot and frozen project")
        frozen = json.loads(frozen_bytes)
        canonical = dict(frozen)
        canonical["job_id"] = linked_job
        canonical["snapshot_ref"] = {"job_id": linked_job}
        canonical["frozen_project_sha256"] = sha256_bytes(frozen_bytes)
        canonical["snapshot_sha256"] = sha256_bytes(dumps_strict(snapshot).encode("utf-8"))
        canonical["document_snapshot"] = snapshot
        canonical["document_artifact_inventory"] = {
            name: {"sha256": sha256_bytes(raw), "size": len(raw)}
            for name in ("report.pdf", "report.docx", "evidence_bundle.zip", "signed_report.pdf", "submission.zip")
            if (raw := jobs.get_artifact(linked_job, name)) is not None
        }
        for key in ("request_spec", "model_state", "encoder_state", "feature_schema", "provenance", "value"):
            if key in payload and payload[key] != canonical.get(key):
                raise HTTPException(409, f"revision {key} differs from the linked calculation")
        for key in ("note", "revision_id", "project_id"):
            if key in payload:
                canonical[key] = payload[key]
        payload = canonical
    saver = getattr(store, "save_revision", None)
    if not callable(saver):
        return _issues_response(
            503,
            "ProjectStore.save_revision unavailable",
            [make_issue("PEER_UNAVAILABLE", "save_revision missing", origin="c10.api")],
        )
    try:
        revision_id = saver(project_id, dict(payload))
    except Exception as exc:
        from modules.job_store import PersistenceError, SchemaVersionError, UnsafePayloadError, PathEscapeError
        from modules.project_store import RevisionImmutableError

        if isinstance(
            exc,
            (PersistenceError, SchemaVersionError, UnsafePayloadError, PathEscapeError, RevisionImmutableError),
        ):
            return _issues_response(
                400,
                "revision payload rejected",
                [make_issue("UNSAFE_PAYLOAD", str(exc), origin="c10.api")],
            )
        raise
    return JSONResponse(
        status_code=201,
        content={
            "schema_version": SCHEMA_VERSION,
            "project_id": project_id,
            "revision_id": revision_id,
        },
    )


@app.post("/projects/{project_id}/batch")
async def project_batch(project_id: str, request: Request):
    """Submit C14 evaluate_batch; not an unbounded local gather loop."""
    job_store, runner = _require_c11()
    project_store = get_project_store()
    if project_store is None:
        return _issues_response(
            503,
            "ProjectStore unavailable",
            c11_unavailable_issues(),
            extra={"integration": "INTEGRATION_PENDING"},
        )
    try:
        body = await request.json()
    except Exception:
        return _issues_response(
            400,
            "invalid JSON body",
            [make_issue("INVALID_JSON", "batch payload is not valid JSON", origin="c10.api")],
        )
    if not isinstance(body, Mapping):
        return _issues_response(
            400,
            "batch payload must be a mapping",
            [make_issue("TYPE_ERROR", "batch payload must be a mapping", origin="c10.api")],
        )
    subjects = body.get("subjects")
    if not isinstance(subjects, list):
        return _issues_response(
            400,
            "subjects must be a list",
            [make_issue("TYPE_ERROR", "subjects must be a list", origin="c10.api")],
        )
    spec_payload = body.get("request_spec")
    spec = _validate_spec_or_400(spec_payload) if spec_payload is not None else None
    revision_id = body.get("revision_id")
    frozen = project_store.load_revision(project_id, revision_id)
    if frozen is None:
        return _issues_response(
            404,
            "frozen project revision not found",
            [make_issue("PROJECT_NOT_FOUND", "load_revision returned nothing", origin="c10.api")],
        )
    if spec is None:
        spec = _validate_spec_or_400(frozen.get("request_spec"))
    peers = get_peers()
    evaluate_batch = peers.get("evaluate_batch")
    if not callable(evaluate_batch):
        return _issues_response(
            503,
            "evaluate_batch unavailable",
            [
                make_issue(
                    "PEER_UNAVAILABLE",
                    "POST /projects/{id}/batch requires modules.valuation_batch.evaluate_batch",
                    origin="c10.api",
                    evidence={"integration": "INTEGRATION_PENDING"},
                )
            ],
            extra={"integration": "INTEGRATION_PENDING"},
        )
    payload = {
        "project_id": project_id,
        "kind": "batch",
        "n_subjects": len(subjects),
        "code_sha": current_code_sha(),
    }
    try:
        key_material = dumps_strict(
            {
                "project_id": project_id,
                "revision_id": revision_id,
                "subjects": subjects,
                "request_spec": request_spec_for_peers(spec) if spec is not None else None,
            }
        )
    except (TypeError, ValueError) as exc:
        return _issues_response(
            400,
            "batch subjects are not strict JSON",
            [
                make_issue(
                    "INVALID_JSON",
                    f"cannot canonicalize subjects for idempotency: {exc}",
                    origin="c10.api",
                )
            ],
        )
    key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    record = _create_job_record(
        job_store, idempotency_key="batch:" + key, project_id=project_id, payload=payload
    )
    job_id = record["job_id"]
    if record.get("created"):
        cancel_requested = _cancel_flag(job_store, runner, job_id)

        def callable_job():
            try:
                job_store.update_transition(job_id, "queued", "running", patch={"stage": "batch"})
            except Exception:
                pass
            try:
                result = evaluate_batch(frozen, subjects, spec, None, cancel_requested)
                snapshot_like = {
                    "schema_version": SCHEMA_VERSION,
                    "job_id": job_id,
                    "project_id": project_id,
                    "batch": True,
                    "result": result if isinstance(result, Mapping) else {"value": result},
                }
                # Batch results are C14's BatchResult, not a single ResultSnapshot.
                saver = getattr(job_store, "save_snapshot", None)
                if callable(saver):
                    # Store as a job snapshot-like record without claiming MP/1 valuation freeze.
                    try:
                        dumps_strict(snapshot_like)
                        saver(job_id, snapshot_like)
                    except Exception:
                        saver(job_id, {"schema_version": SCHEMA_VERSION, "job_id": job_id, "batch": True})
                job_store.update_transition(
                    job_id,
                    "running",
                    "succeeded",
                    patch={"result_available": True, "stage": "batch", "calculation_state": "succeeded"},
                )
            except Exception as exc:
                logger.error("batch job %s failed: %s", job_id, exc)
                job_store.update_transition(
                    job_id,
                    "running",
                    "failed",
                    patch={
                        "issues": [make_issue("BATCH_FAILED", str(exc), origin="c10.api")],
                        "calculation_state": "failed",
                    },
                )

        runner.submit(job_id, callable_job)
    return JSONResponse(
        status_code=202,
        content={
            "schema_version": SCHEMA_VERSION,
            "job_id": job_id,
            "status_url": f"/jobs/{job_id}",
            "state": record.get("state") or "queued",
            "idempotent_replay": not record.get("created"),
        },
    )


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    degree: int = Form(...),
    target_col: str = Form(...),
    avaliando_json: Optional[str] = Form(None),
    grau_item1: Optional[int] = Form(None),
    grau_item3: Optional[int] = Form(None),
    item1_provenance: Optional[str] = Form(None),
    item3_provenance: Optional[str] = Form(None),
    candidate_cols_json: Optional[str] = Form(None),
    solicitante: str = Form(""),
    finalidade: str = Form(""),
):
    """Compatibility adapter onto POST /jobs. Invalid payloads are 4xx, not 200."""
    candidate_cols = None
    if candidate_cols_json not in (None, ""):
        parsed = _parse_json_field(candidate_cols_json, field="candidate_cols_json")
        if parsed is not None and not isinstance(parsed, list):
            return _issues_response(
                400,
                "candidate_cols_json must be a list or omitted",
                [make_issue("TYPE_ERROR", "candidate_cols_json must be a list", origin="c10.api")],
            )
        candidate_cols = parsed
    subject = None
    if avaliando_json not in (None, ""):
        subject = _parse_json_field(avaliando_json, field="avaliando_json")
        if subject is not None and not isinstance(subject, Mapping):
            return _issues_response(
                400,
                "avaliando_json must decode to a mapping",
                [make_issue("TYPE_ERROR", "avaliando_json must be a mapping", origin="c10.api")],
            )
        ok, issues = subject_numeric_values_finite(subject)
        if not ok:
            return _issues_response(400, "avaliando contains non-finite numbers", issues)
    spec_payload = request_spec_from_upload_form(
        degree=degree,
        target_col=target_col,
        candidate_cols=candidate_cols,
        solicitante=solicitante,
        finalidade=finalidade,
        grau_item1=grau_item1,
        grau_item3=grau_item3,
    )
    for name, raw in (("item1_provenance", item1_provenance), ("item3_provenance", item3_provenance)):
        if raw is not None:
            spec_payload["declared_documentary"][name] = _parse_json_field(raw, field=name)
    spec = _validate_spec_or_400(spec_payload)
    file_bytes = await read_upload_limited(file, _max_upload_bytes())
    filename = file.filename or "upload.bin"
    job_store, runner = _require_c11()
    key = submission_key(file_bytes, spec, subject)
    payload = {
        "filename": filename,
        "input_sha256": sha256_bytes(file_bytes),
        "adapter": "upload",
        "request_spec": request_spec_for_peers(spec),
    }
    record = _create_job_record(job_store, idempotency_key=key, project_id=None, payload=payload)
    job_id = record["job_id"]
    if record.get("created"):
        _submit_valuation(
            job_id=job_id,
            file_bytes=file_bytes,
            filename=filename,
            request_spec=spec,
            subject_raw=subject,
            project_id=None,
            job_store=job_store,
            runner=runner,
        )
    return JSONResponse(
        status_code=202,
        content={
            "schema_version": SCHEMA_VERSION,
            "message": "File accepted. Processing started.",
            "filename": filename,
            "job_id": job_id,
            "status_url": f"/jobs/{job_id}",
            "state": record.get("state") or "queued",
        },
    )


def main():
    if uvicorn is None:
        raise RuntimeError("uvicorn is required to serve backend.api")
    uvicorn.run(
        "backend.api:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=config.DEBUG,
    )


if __name__ == "__main__":
    main()
