"""Persisted C03 document lifecycle for an MP/1 valuation job.

This is a consumer of the calculation snapshot and the real normative
assessment persisted by the worker.  It never accepts a normative assessment
from an HTTP caller and never reclassifies a rule or a grade itself.
"""

from __future__ import annotations

import hashlib
import copy
import json
import re
import io
import zipfile
from functools import wraps
from collections.abc import Mapping
from typing import Any, Dict, Optional

from ..digital_signatures import prepare_signature_request, record_external_signature
from ..evidence_bundle import refresh_evidence_bundle_archive
from ..pro_workflow.report_context import build_output_manifest, complete_report_context, _json_value
from ..provenance import canonical_json
from ..report_presenter.qualification import (
    assess_document_state,
    report_content_fingerprint,
)
from ..report_presenter.verifier import verify_report_consistency
from ..results_generator import render_report
from .docx import build_docx, verify_docx_equivalence
from .submission import build_submission_package, verify_submission_package, _verify_dossier_archive


class DocumentWorkflowError(RuntimeError):
    """A fail-closed document operation with a stable API code."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _serialized(operation):
    """One document mutation per workspace, also excluding consistent backups."""
    @wraps(operation)
    def run(store, *args, **kwargs):
        with store._lock:
            return operation(store, *args, **kwargs)
    return run


def _archive_current_documents(store, job_id, *, retire_unsigned=False):
    """Retain a byte-exact historical generation before invalidating its names."""
    names = ["report.pdf", "report.docx", "report_context.json", "document_state.json",
             "signature_request.json", "signed_report.pdf", "submission.zip", "evidence_bundle.zip"]
    current = {name: raw for name in names if (raw := store.get_artifact(job_id, name)) is not None}
    if not current:
        return
    current["snapshot.json"] = canonical_json(store.get_snapshot(job_id)).encode("utf-8")
    generation = _sha(canonical_json({name: _sha(raw) for name, raw in current.items()}).encode())
    previous = store.get_artifact(job_id, "document_history.zip")
    output = io.BytesIO(previous or b"")
    with zipfile.ZipFile(output, "a" if previous else "w", zipfile.ZIP_DEFLATED) as history:
        existing = set(history.namelist())
        for name, raw in current.items():
            target = f"{generation}/{name}"
            if target not in existing:
                history.writestr(target, raw)
    store.save_artifact(job_id, "document_history.zip", output.getvalue())
    retired = ["signature_request.json", "signed_report.pdf", "submission.zip"]
    if retire_unsigned:
        retired += ["report.pdf", "report.docx"]
    for name in retired:
        store.retire_artifact(job_id, name)


def _load_json_artifact(store: Any, job_id: str, name: str, *, required: bool = True) -> Dict[str, Any]:
    raw = store.get_artifact(job_id, name)
    if raw is None:
        if required:
            raise DocumentWorkflowError("DOCUMENT_INPUT_MISSING", f"{name} is not available")
        return {}
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DocumentWorkflowError("DOCUMENT_INPUT_INVALID", f"{name} is not valid JSON") from exc
    if not isinstance(decoded, Mapping):
        raise DocumentWorkflowError("DOCUMENT_INPUT_INVALID", f"{name} must contain a mapping")
    return dict(decoded)


def _save_json(store: Any, job_id: str, name: str, value: Mapping[str, Any]) -> None:
    store.save_artifact(job_id, name, canonical_json(dict(value)).encode("utf-8"))


def _report_context(store: Any, job_id: str) -> Dict[str, Any]:
    context = _load_json_artifact(store, job_id, "report_context.json")
    registry = _load_json_artifact(
        store, job_id, "document_attachments.json", required=False
    )
    files = []
    for entry in registry.get("items") or []:
        if not isinstance(entry, Mapping):
            continue
        item = dict(entry)
        stored_name = str(item.pop("stored_name", ""))
        raw = store.get_artifact(job_id, stored_name) if stored_name else None
        if not item.get("authorized_for_report"):
            item["attachment_state"] = "not_authorized_for_report"
        elif raw is None or _sha(raw) != item.get("sha256"):
            item["attachment_state"] = "missing_or_hash_mismatch"
        else:
            item["bytes"] = raw
            item["attachment_state"] = "available"
        files.append(item)
    if any(item.get("synthetic_test_only") for item in files):
        context["synthetic_test_only"] = True
    context["documentary_files"] = files
    if files:
        context["documentary_files"] = files
        context["documents"] = [
            {
                "name": item.get("filename"),
                "status": "present" if item.get("attachment_state") == "available" else "pending",
                "provenance": item.get("source") or "",
            }
            for item in files
            if item.get("category") == "document"
        ]
        context["annexes"] = [
            {
                "title": item.get("description") or item.get("filename") or "Anexo",
                "kind": "documentary_attachment",
                "note": "Arquivo integral no dossiê; SHA-256 " + str(item.get("sha256") or ""),
                "columns": [],
                "rows": [],
            }
            for item in files
            if item.get("category") == "annex"
        ]
    return context


@_serialized
def store_document_attachment(
    store: Any,
    job_id: str,
    *,
    filename: str,
    media_type: str,
    content: bytes,
    source: str,
    authorized_for_report: bool,
    category: str = "document",
    description: str = "",
    synthetic_test_only: bool = False,
    requirement_ids: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """Persist exact attachment bytes and a digest-bound report registry."""
    if not store.get(job_id):
        raise DocumentWorkflowError("JOB_NOT_FOUND", f"job {job_id} not found", status_code=404)
    if not content:
        raise DocumentWorkflowError("ATTACHMENT_EMPTY", "attachment is empty", status_code=400)
    if len(content) > 20 * 1024 * 1024:
        raise DocumentWorkflowError("ATTACHMENT_TOO_LARGE", "attachment exceeds 20 MiB", status_code=413)
    if not source.strip() or not authorized_for_report:
        raise DocumentWorkflowError("ATTACHMENT_AUTHORIZATION_REQUIRED", "source and authorization are required", status_code=400)
    requirement_ids = requirement_ids or []
    if not isinstance(requirement_ids, list) or not all(isinstance(rid, str) for rid in requirement_ids):
        raise DocumentWorkflowError("ATTACHMENT_REQUIREMENTS_INVALID", "requirement_ids must be a list of IDs", status_code=400)
    from ..qualification_profile import resolve_profile
    job = store.get(job_id)
    profile = resolve_profile((job.get("request_spec") or {}).get("qualification_profile") or {})
    known_requirements = {item["id"] for item in profile.get("requirements") or []}
    if set(requirement_ids) - known_requirements:
        raise DocumentWorkflowError("ATTACHMENT_REQUIREMENTS_INVALID", "requirement does not belong to the case profile", status_code=400)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(filename or "document.bin")).strip(".-")
    safe = safe[:70] or "document.bin"
    digest = _sha(content)
    normalized_category = str(category or "document").strip().lower()
    if normalized_category not in {"document", "annex"}:
        raise DocumentWorkflowError(
            "ATTACHMENT_CATEGORY_INVALID",
            "category must be document or annex",
            status_code=400,
        )
    stored_name = f"attachment-{digest[:20]}-{safe}"
    _archive_current_documents(store, job_id, retire_unsigned=True)
    store.save_artifact(job_id, stored_name, content)
    registry = _load_json_artifact(store, job_id, "document_attachments.json", required=False)
    items = [dict(item) for item in registry.get("items") or [] if isinstance(item, Mapping)]
    entry = {
        "stored_name": stored_name,
        "filename": str(filename or safe),
        "media_type": str(media_type or "application/octet-stream"),
        "type": str(media_type or "application/octet-stream"),
        "sha256": digest,
        "size": len(content),
        "source": str(source or ""),
        "authorized_for_report": bool(authorized_for_report),
        "category": normalized_category,
        "description": str(description or ""),
        "synthetic_test_only": bool(synthetic_test_only),
        "requirement_ids": sorted(set(requirement_ids)),
    }
    items = [item for item in items if item.get("stored_name") != stored_name] + [entry]
    _save_json(
        store,
        job_id,
        "document_attachments.json",
        {"schema_version": "MP-DOCUMENT-ATTACHMENTS/1", "items": items},
    )
    job, snapshot, normative = _job_inputs(store, job_id)
    context = _report_context(store, job_id)
    manifest = build_output_manifest(snapshot, context)
    qctx = (snapshot.get("provenance") or {}).get("qualification_context") or {}
    snapshot = _reassess(snapshot, job.get("request_spec") or {}, normative,
                         report_context=context, output_manifest=manifest,
                         review_events=list(qctx.get("review_events") or []), signature=None)
    store.save_snapshot(job_id, snapshot)
    _save_json(store, job_id, "output_manifest.json", manifest)
    state = assess_document_state(snapshot, context)
    _save_json(store, job_id, "document_state.json", {
        "schema_version": "MP-DOCUMENTS/1", "job_id": job_id,
        "case_release_status": state["case_release_status"], "document_state": state,
        "regeneration_required": True,
    })
    return {"schema_version": "MP-DOCUMENT-ATTACHMENT/1", **entry}


def _job_inputs(store: Any, job_id: str) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    job = store.get(job_id)
    if not isinstance(job, Mapping):
        raise DocumentWorkflowError("JOB_NOT_FOUND", f"job {job_id} not found", status_code=404)
    snapshot = store.get_snapshot(job_id)
    if not isinstance(snapshot, Mapping):
        raise DocumentWorkflowError("RESULT_NOT_AVAILABLE", "the calculation snapshot is not available")
    normative = _load_json_artifact(store, job_id, "normative_assessment.json")
    return dict(job), dict(snapshot), normative


def _reassess(
    snapshot: Mapping[str, Any],
    request_spec: Mapping[str, Any],
    normative: Mapping[str, Any],
    *,
    report_context: Mapping[str, Any],
    output_manifest: Mapping[str, Any],
    review_events: list[Mapping[str, Any]],
    signature: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    try:
        from ..valuation_policy.qualification import reassess_qualification_context
    except ImportError as exc:
        raise DocumentWorkflowError(
            "QUALIFICATION_REASSESSMENT_UNAVAILABLE",
            "the C01/C05 document reassessment function is unavailable",
        ) from exc
    fingerprint = report_content_fingerprint(snapshot, report_context)
    # References in an order are declarations, not file evidence. Only the
    # server-read, digest-checked registry can satisfy documentary requirements.
    from ..qualification_profile import resolve_profile
    profile = resolve_profile(request_spec.get("qualification_profile") or {})
    declared = dict(request_spec.get("profile_evidence") or {})
    verified = dict(declared)
    for requirement in profile.get("requirements") or []:
        rid = requirement.get("id")
        if requirement.get("verification") == "calculated":
            continue
        verified.pop(rid, None)
        matches = [item for item in report_context.get("documentary_files") or []
                   if item.get("authorized_for_report") and item.get("attachment_state") == "available"
                   and isinstance(item.get("bytes"), (bytes, bytearray))
                   and _sha(bytes(item["bytes"])) == item.get("sha256")
                   and (rid in (item.get("requirement_ids") or [])
                        or (isinstance(declared.get(rid), str) and declared[rid] == item.get("source")))]
        if matches:
            verified[rid] = "; ".join(f"sha256:{item['sha256']}:{item.get('source')}" for item in matches)
    request_spec = {**request_spec, "profile_evidence": verified}
    updated_context = reassess_qualification_context(
        snapshot=snapshot,
        request_spec=request_spec,
        output_manifest=output_manifest,
        report_content_fingerprint=fingerprint,
        review_events=review_events,
        signature=signature,
        normative_assessment=normative,
    )
    if not isinstance(updated_context, Mapping):
        raise DocumentWorkflowError(
            "QUALIFICATION_REASSESSMENT_INVALID",
            "qualification reassessment did not return an MP-QUAL/1 mapping",
        )
    updated = copy.deepcopy(dict(snapshot))
    updated.setdefault("provenance", {})["qualification_context"] = dict(updated_context)
    from ..valuation_policy.qualification import map_issuance_status

    issuance = updated.setdefault("validation", {}).setdefault("issuance", {})
    release = str(updated_context.get("case_release_status") or "analysis_only")
    issuance["status"] = map_issuance_status(release)
    issuance["case_release_status"] = release
    return updated


def _render_and_verify(snapshot: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[bytes, bytes]:
    pdf = render_report(snapshot, context)
    docx = build_docx(snapshot, context)
    pdf_check = verify_report_consistency(pdf, snapshot, context)
    docx_check = verify_docx_equivalence(docx, snapshot, context)
    if not pdf_check.get("ok"):
        codes = [item.get("code") for item in pdf_check.get("findings") or []]
        raise DocumentWorkflowError("REPORT_PDF_INCONSISTENT", f"PDF verification failed: {codes}")
    if not docx_check.get("equivalent"):
        raise DocumentWorkflowError("REPORT_DOCX_INCONSISTENT", "DOCX is not equivalent to the snapshot")
    return pdf, docx


def _refresh_dossier(
    store: Any,
    job_id: str,
    *,
    snapshot: Mapping[str, Any],
    pdf: bytes,
    docx: bytes,
    signature_record: Optional[Mapping[str, Any]] = None,
    signed_pdf: Optional[bytes] = None,
    documentary_files: list[Mapping[str, Any]] | None = None,
    persist: bool = True,
) -> Optional[bytes]:
    existing = store.get_artifact(job_id, "evidence_bundle.zip")
    if existing is None:
        raise DocumentWorkflowError("DOSSIER_MISSING", "evidence_bundle.zip is required for document emission")
    refreshed = refresh_evidence_bundle_archive(
        existing,
        snapshot=snapshot,
        report_pdf=pdf,
        report_docx=docx,
        signature_record=signature_record,
        signed_report_pdf=signed_pdf,
        documentary_files=documentary_files or [],
    )
    if persist:
        store.save_artifact(job_id, "evidence_bundle.zip", refreshed)
    return refreshed


def _artifact_inventory(store: Any, job_id: str, names: list[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for name in names:
        data = store.get_artifact(job_id, name)
        if data is not None:
            result[name] = {"sha256": _sha(data), "size": len(data)}
    return result


@_serialized
def generate_documents(
    store: Any,
    job_id: str,
    *,
    report_fields: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate and persist equivalent PDF/DOCX plus a refreshed dossier."""
    job, snapshot, normative = _job_inputs(store, job_id)
    persisted_context = _report_context(store, job_id)
    request_spec = dict(job.get("request_spec") or {})
    if report_fields:
        request_spec["report_context"] = {
            **dict(request_spec.get("report_context") or {}),
            **dict(report_fields),
        }
    context = complete_report_context(
        persisted_context,
        request_spec=request_spec,
        snapshot=snapshot,
    )
    # JSON input cannot manufacture attachment bytes or replace the registry.
    context["documentary_files"] = persisted_context.get("documentary_files") or []
    output_manifest = build_output_manifest(snapshot, context)
    current_qctx = dict((snapshot.get("provenance") or {}).get("qualification_context") or {})
    snapshot = _reassess(
        snapshot,
        request_spec,
        normative,
        report_context=context,
        output_manifest=output_manifest,
        review_events=list(current_qctx.get("review_events") or []),
        signature=None,
    )
    # result_fingerprint changed after adding the real output manifest.  The
    # final report-content fingerprint is computed only from that stable result.
    pdf, docx = _render_and_verify(snapshot, context)
    dossier = _refresh_dossier(
        store, job_id, snapshot=snapshot, pdf=pdf, docx=docx,
        documentary_files=context.get("documentary_files") or [], persist=False,
    )
    _archive_current_documents(store, job_id)
    store.save_snapshot(job_id, snapshot)
    # Persist only JSON-safe metadata. Exact attachment bytes stay in their
    # own immutable artifact and are reloaded by digest for later stages.
    _save_json(store, job_id, "report_context.json", _json_value(context))
    _save_json(store, job_id, "output_manifest.json", output_manifest)
    store.save_artifact(job_id, "report.pdf", pdf)
    store.save_artifact(job_id, "report.docx", docx)
    store.save_artifact(job_id, "evidence_bundle.zip", dossier)
    state = assess_document_state(snapshot, context)
    result = {
        "schema_version": "MP-DOCUMENTS/1",
        "job_id": job_id,
        "case_release_status": state.get("case_release_status"),
        "document_state": state,
        "result_fingerprint": state.get("result_fingerprint"),
        "report_content_fingerprint": report_content_fingerprint(snapshot, context),
        "artifacts": _artifact_inventory(
            store,
            job_id,
            ["report.pdf", "report.docx", "evidence_bundle.zip"],
        ),
        "dossier_available": dossier is not None,
    }
    _save_json(store, job_id, "document_state.json", result)
    return result


@_serialized
def record_review(
    store: Any,
    job_id: str,
    *,
    professional_id: str,
    motive: str,
    version: str,
    professional_name: Optional[str] = None,
    synthetic_test_only: bool = False,
) -> Dict[str, Any]:
    """Record a review bound to both result and rendered-content fingerprints."""
    if not all(str(value or "").strip() for value in (professional_id, motive, version)):
        raise DocumentWorkflowError(
            "REVIEW_FIELDS_REQUIRED", "professional_id, motive and version are required", status_code=400
        )
    job, snapshot, normative = _job_inputs(store, job_id)
    context = _report_context(store, job_id)
    if synthetic_test_only:
        context["synthetic_test_only"] = True
    output_manifest = _load_json_artifact(store, job_id, "output_manifest.json")
    qctx = dict((snapshot.get("provenance") or {}).get("qualification_context") or {})
    result_fp = str(qctx.get("result_fingerprint") or "")
    report_fp = report_content_fingerprint(snapshot, context)
    event = {
        "event_type": "professional_review_approved",
        "decision": "approved",
        "professional_id": str(professional_id),
        "professional": {
            "id": str(professional_id),
            "name": str(professional_name or ""),
        },
        "motive": str(motive),
        "reason": str(motive),
        "version": str(version),
        "revision_id": str(version),
        "fingerprint": result_fp,
        "result_fingerprint": result_fp,
        "report_content_fingerprint": report_fp,
        "synthetic_test_only": bool(synthetic_test_only),
    }
    history = list(qctx.get("review_events") or []) + [event]
    snapshot = _reassess(
        snapshot,
        dict(job.get("request_spec") or {}),
        normative,
        report_context=context,
        output_manifest=output_manifest,
        review_events=history,
        signature=None,
    )
    pdf, docx = _render_and_verify(snapshot, context)
    dossier = _refresh_dossier(
        store, job_id, snapshot=snapshot, pdf=pdf, docx=docx,
        documentary_files=context.get("documentary_files") or [], persist=False,
    )
    _archive_current_documents(store, job_id)
    store.save_snapshot(job_id, snapshot)
    _save_json(store, job_id, "report_context.json", _json_value(context))
    store.save_artifact(job_id, "report.pdf", pdf)
    store.save_artifact(job_id, "report.docx", docx)
    store.save_artifact(job_id, "evidence_bundle.zip", dossier)
    state = assess_document_state(snapshot, context)
    result = {
        "schema_version": "MP-REVIEW/1",
        "job_id": job_id,
        "event": event,
        "case_release_status": state.get("case_release_status"),
        "document_state": state,
        "unsigned_pdf_sha256": _sha(pdf),
        "docx_sha256": _sha(docx),
        "dossier_sha256": _sha(dossier),
    }
    _save_json(store, job_id, "document_state.json", result)
    return result


@_serialized
def create_signature_request(store: Any, job_id: str, *, revision_id: str) -> Dict[str, Any]:
    job, snapshot, _normative = _job_inputs(store, job_id)
    context = _report_context(store, job_id)
    pdf = store.get_artifact(job_id, "report.pdf")
    if pdf is None:
        raise DocumentWorkflowError("REPORT_PDF_MISSING", "report.pdf is not available")
    if store.get_artifact(job_id, "evidence_bundle.zip") is None:
        raise DocumentWorkflowError("DOSSIER_MISSING", "evidence_bundle.zip is required for signing")
    state = assess_document_state(snapshot, context)
    if state.get("case_release_status") != "ready_for_professional_signoff" or not state.get("is_final"):
        raise DocumentWorkflowError("DOCUMENT_NOT_READY_FOR_SIGNATURE", "document is not ready for signature")
    reviews = state.get("approved_review_events") or []
    latest = reviews[-1] if reviews else {}
    if not revision_id or revision_id != latest.get("version"):
        raise DocumentWorkflowError("SIGNATURE_REVISION_MISMATCH", "signature must reference the current approved review")
    docx = store.get_artifact(job_id, "report.docx")
    if docx is None:
        raise DocumentWorkflowError("DOCUMENT_ARTIFACT_MISSING", "controlled DOCX is required before signature export")
    reviewed_bytes = _load_json_artifact(store, job_id, "document_state.json")
    dossier = store.get_artifact(job_id, "evidence_bundle.zip")
    if (reviewed_bytes.get("schema_version") != "MP-REVIEW/1"
            or reviewed_bytes.get("unsigned_pdf_sha256") != _sha(pdf)
            or reviewed_bytes.get("docx_sha256") != _sha(docx)
            or reviewed_bytes.get("dossier_sha256") != _sha(dossier)):
        raise DocumentWorkflowError("SIGNATURE_EXPORT_INCONSISTENT", "current bytes differ from the recorded professional review")
    try:
        if not verify_report_consistency(pdf, snapshot, context).get("ok"):
            raise ValueError("controlled PDF differs from the reviewed content")
        if not verify_docx_equivalence(docx, snapshot, context).get("equivalent"):
            raise ValueError("controlled DOCX differs from the reviewed content")
        dossier = store.get_artifact(job_id, "evidence_bundle.zip")
        check = _verify_dossier_archive(dossier, expected_snapshot=snapshot, require_complete=False)
        if not check.get("ok"):
            raise ValueError("dossier integrity or snapshot binding failed")
        with zipfile.ZipFile(io.BytesIO(dossier)) as archive:
            ledger = json.loads(archive.read("completeness/ledger.json"))
        missing = set(ledger.get("missing") or [])
        manifest = check["manifest"]
        if missing != set(manifest.get("completeness_missing") or []):
            raise ValueError("dossier completeness records disagree")
        # The bytes being requested cannot already have a signature. This is
        # the only stage-specific pending item; every other obligation remains.
        if missing - {"signature_record"} or manifest.get("numerical_reproduction_status") not in {"ready", "verified"}:
            raise ValueError("unsigned dossier is incomplete")
    except Exception as exc:
        raise DocumentWorkflowError("SIGNATURE_EXPORT_INCONSISTENT", "controlled documents failed pre-signature verification") from exc
    profile_id = str((state.get("profile") or {}).get("id") or "")
    request = prepare_signature_request(
        pdf,
        snapshot,
        revision_id=revision_id,
        profile_id=profile_id,
        report_context=context,
    )
    _save_json(store, job_id, "signature_request.json", request)
    return request


@_serialized
def import_signed_report(
    store: Any,
    job_id: str,
    *,
    signed_pdf: bytes,
    validation_context: Any = None,
    policy: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Verify and persist exact externally signed bytes; never rerender them."""
    job, snapshot, normative = _job_inputs(store, job_id)
    context = _report_context(store, job_id)
    output_manifest = _load_json_artifact(store, job_id, "output_manifest.json")
    request = _load_json_artifact(store, job_id, "signature_request.json")
    unsigned = store.get_artifact(job_id, "report.pdf")
    docx = store.get_artifact(job_id, "report.docx")
    if unsigned is None or docx is None:
        raise DocumentWorkflowError("DOCUMENT_ARTIFACT_MISSING", "unsigned PDF or DOCX is missing")
    record = record_external_signature(
        bytes(signed_pdf),
        request,
        unsigned_pdf=unsigned,
        validation_context=validation_context,
        policy=policy,
    )
    if record.get("status") != "valid":
        raise DocumentWorkflowError(
            "SIGNATURE_NOT_VALID",
            "signed PDF failed local cryptographic verification: "
            + ", ".join(str(item.get("code")) for item in record.get("findings") or []),
            status_code=422,
        )
    qctx = dict((snapshot.get("provenance") or {}).get("qualification_context") or {})
    signature_for_qualification = {
        "integrity_verified": True,
        "fingerprint": record.get("result_fingerprint"),
        "result_fingerprint": record.get("result_fingerprint"),
        "report_content_fingerprint": record.get("report_content_fingerprint"),
        "unsigned_pdf_sha256": record.get("unsigned_pdf_sha256"),
        "signed_pdf_sha256": record.get("signed_pdf_sha256"),
    }
    snapshot = _reassess(
        snapshot,
        dict(job.get("request_spec") or {}),
        normative,
        report_context=context,
        output_manifest=output_manifest,
        review_events=list(qctx.get("review_events") or []),
        signature=signature_for_qualification,
    )
    snapshot.setdefault("provenance", {}).setdefault("qualification_context", {})[
        "digital_signature"
    ] = record
    # This assignment is post-signing metadata and is excluded by
    # signable_snapshot_sha256/report_content_fingerprint.
    signed_context = {
        **context,
        "unsigned_pdf_bytes": unsigned,
        "signed_pdf_bytes": bytes(signed_pdf),
        "digital_signature": record,
        "signature_validation_context": validation_context,
    }
    state = assess_document_state(snapshot, signed_context)
    if (
        state.get("case_release_status") != "signed_integrity_verified"
        or not state.get("is_final")
    ):
        raise DocumentWorkflowError(
            "SIGNATURE_BINDING_STALE",
            "valid PDF signature is not bound to the current result, report and review: "
            + ", ".join(
                str(item.get("code")) for item in state.get("blockers") or []
            ),
            status_code=422,
        )
    dossier = _refresh_dossier(
        store,
        job_id,
        snapshot=snapshot,
        pdf=unsigned,
        docx=docx,
        signature_record=record,
        signed_pdf=bytes(signed_pdf),
        documentary_files=context.get("documentary_files") or [],
        persist=False,
    )
    requirement_map = _requirement_map(snapshot)
    submission = None
    if dossier is not None:
        submission = build_submission_package(
            snapshot,
            signed_context,
            pdf_bytes=unsigned,
            docx_bytes=docx,
            dossier_bytes=dossier,
            requirement_map=requirement_map,
            signed_pdf_bytes=bytes(signed_pdf),
        )
        check = verify_submission_package(submission)
        if not check.get("ok"):
            raise DocumentWorkflowError("SUBMISSION_PACKAGE_INVALID", "submission package failed verification")
    # All cryptographic, document, dossier and package checks precede mutations.
    store.save_snapshot(job_id, snapshot)
    store.save_artifact(job_id, "signed_report.pdf", bytes(signed_pdf))
    store.save_artifact(job_id, "evidence_bundle.zip", dossier)
    store.save_artifact(job_id, "submission.zip", submission)
    result = {
        "schema_version": "MP-SIGNED-DOCUMENT/1",
        "job_id": job_id,
        "signature": record,
        "document_state": state,
        "signed_pdf_sha256": _sha(bytes(signed_pdf)),
        "unsigned_pdf_sha256": _sha(unsigned),
        "submission_available": submission is not None,
        "artifacts": _artifact_inventory(
            store,
            job_id,
            ["signed_report.pdf", "evidence_bundle.zip", "submission.zip"],
        ),
    }
    _save_json(store, job_id, "document_state.json", result)
    return result


@_serialized
def get_document_status(store: Any, job_id: str) -> Dict[str, Any]:
    job = store.get(job_id)
    if not isinstance(job, Mapping):
        raise DocumentWorkflowError("JOB_NOT_FOUND", f"job {job_id} not found", status_code=404)
    stored = _load_json_artifact(store, job_id, "document_state.json", required=False)
    return {
        "schema_version": "MP-DOCUMENTS/1",
        "job_id": job_id,
        "state": stored or None,
        "artifacts": _artifact_inventory(
            store,
            job_id,
            [
                "report.pdf",
                "report.docx",
                "evidence_bundle.zip",
                "signature_request.json",
                "signed_report.pdf",
                "submission.zip",
                "document_history.zip",
            ],
        ),
    }


def _requirement_map(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    qctx = dict((snapshot.get("provenance") or {}).get("qualification_context") or {})
    profile = dict(qctx.get("profile") or {})
    requirements = []
    for rule in qctx.get("rule_results") or []:
        if not isinstance(rule, Mapping) or not rule.get("rule_id"):
            continue
        requirements.append(
            {
                "id": str(rule["rule_id"]),
                "status": rule.get("status"),
                "evidence": list(rule.get("evidence_refs") or [])
                or [f"qualification/context.json#rule={rule['rule_id']}"],
            }
        )
    return {
        "schema_version": "MP-REQ-MAP/1",
        "profile_id": profile.get("id"),
        "source": {
            "id": profile.get("id"),
            "version": profile.get("version"),
        },
        "requirements": requirements,
    }
