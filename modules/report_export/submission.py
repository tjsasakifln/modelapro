"""Neutral institutional submission package; performs no external submission."""

from __future__ import annotations

import csv
import copy
import hashlib
import io
import json
import zipfile
from collections.abc import Mapping
from typing import Any, Dict, Optional

from ..provenance import canonical_json
from ..report_presenter.qualification import assess_document_state
from ..report_presenter.verifier import verify_report_consistency
from .docx import verify_docx_equivalence

MANIFEST = "SUBMISSION_MANIFEST.json"
_ZIP_TIME = (2020, 1, 1, 0, 0, 0)


def _entry(data: bytes, media_type: str, function: str) -> Dict[str, Any]:
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "media_type": media_type,
        "function": function,
    }


def _write(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, _ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, data)


_DOSSIER_REQUIRED = {
    "snapshot/result_snapshot.json",
    "qualification/context.json",
    "review/history.json",
    "data/source_input.bin",
    "data/original_base.csv",
    "data/interpreted_base.csv",
    "data/used_sample.csv",
    "data/excluded_rows.csv",
    "data/identifier_map.json",
    "data/representation_map.json",
    "model/coefficients.json",
    "model/subject_design.json",
    "model/transformations.json",
    "model/residual_context.json",
    "policies/request_spec.json",
    "policies/missing_policy.json",
    "policies/outlier_policy.json",
    "policies/search_policy.json",
    "policies/evaluation_policy.json",
    "policies/value_policy.json",
    "reproduction/spec.json",
    "completeness/ledger.json",
}


def _verify_requirement_map(
    requirement_map: Mapping[str, Any], profile_id: str
) -> list[Dict[str, Any]]:
    findings: list[Dict[str, Any]] = []
    source = requirement_map.get("source")
    requirements = requirement_map.get("requirements")
    if requirement_map.get("schema_version") != "MP-REQ-MAP/1":
        findings.append({"code": "REQUIREMENT_MAP_SCHEMA_INVALID"})
    if str(requirement_map.get("profile_id") or "") != profile_id:
        findings.append({"code": "REQUIREMENT_MAP_PROFILE_MISMATCH"})
    if (
        not isinstance(source, Mapping)
        or not source.get("id")
        or not source.get("version")
    ):
        findings.append({"code": "REQUIREMENT_MAP_SOURCE_INCOMPLETE"})
    if not isinstance(requirements, list) or not requirements:
        findings.append({"code": "REQUIREMENT_MAP_EMPTY"})
    elif any(
        not isinstance(item, Mapping) or not item.get("id") or not item.get("evidence")
        for item in requirements
    ):
        findings.append({"code": "REQUIREMENT_MAP_ITEM_INCOMPLETE"})
    return findings


def _verify_dossier_archive(
    data: bytes,
    *,
    expected_snapshot: Optional[Mapping[str, Any]] = None,
    require_complete: bool = False,
) -> Dict[str, Any]:
    findings = []
    manifest: Dict[str, Any] = {}
    packaged_snapshot: Dict[str, Any] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
            bad = archive.testzip()
            names = set(archive.namelist())
            if bad:
                findings.append({"code": "DOSSIER_CRC_ERROR", "member": bad})
            if "MANIFEST.json" not in names:
                findings.append({"code": "DOSSIER_MANIFEST_MISSING"})
                return {"ok": False, "findings": findings}
            manifest = json.loads(archive.read("MANIFEST.json").decode("utf-8"))
            if manifest.get("schema_version") != "MP/1" or not str(
                manifest.get("bundle_version") or ""
            ).startswith("C12/"):
                findings.append({"code": "DOSSIER_SCHEMA_INVALID"})
            raw_files = manifest.get("files") or []
            listed = {entry.get("path"): entry for entry in raw_files}
            if len(listed) != len(raw_files):
                findings.append({"code": "DOSSIER_DUPLICATE_MANIFEST_PATH"})
            if None in listed:
                findings.append({"code": "DOSSIER_MANIFEST_PATH_INVALID"})
            missing_required = sorted(_DOSSIER_REQUIRED - set(listed))
            if missing_required:
                findings.append(
                    {
                        "code": "DOSSIER_REQUIRED_EVIDENCE_MISSING",
                        "paths": missing_required,
                    }
                )
            for path, entry in listed.items():
                if not path or path not in names:
                    findings.append({"code": "DOSSIER_FILE_MISSING", "path": path})
                    continue
                member = archive.read(path)
                if hashlib.sha256(member).hexdigest() != entry.get("sha256"):
                    findings.append({"code": "DOSSIER_HASH_MISMATCH", "path": path})
                if len(member) != entry.get("size"):
                    findings.append({"code": "DOSSIER_SIZE_MISMATCH", "path": path})
            extras = names - set(listed) - {"MANIFEST.json"}
            if extras:
                findings.append(
                    {"code": "DOSSIER_UNLISTED_FILE", "paths": sorted(extras)}
                )
            if "snapshot/result_snapshot.json" in names:
                packaged_snapshot = json.loads(
                    archive.read("snapshot/result_snapshot.json").decode("utf-8")
                )
                if expected_snapshot is not None and canonical_json(
                    packaged_snapshot
                ) != canonical_json(dict(expected_snapshot)):
                    findings.append({"code": "DOSSIER_SNAPSHOT_MISMATCH"})
            if {
                "snapshot/result_snapshot.json",
                "qualification/context.json",
            }.issubset(names):
                qualification = json.loads(
                    archive.read("qualification/context.json").decode("utf-8")
                )
                snapshot_qctx = (
                    packaged_snapshot.get("provenance", {}).get(
                        "qualification_context", {}
                    )
                    if isinstance(packaged_snapshot, Mapping)
                    else {}
                )
                if canonical_json(qualification) != canonical_json(snapshot_qctx):
                    findings.append({"code": "DOSSIER_QUALIFICATION_MISMATCH"})
            sample = (
                packaged_snapshot.get("sample", {})
                if isinstance(packaged_snapshot, Mapping)
                else {}
            )
            for path, ids_field in (
                ("data/used_sample.csv", "used_row_ids"),
                ("data/excluded_rows.csv", "excluded_row_ids"),
            ):
                if path not in names:
                    continue
                try:
                    rows = list(
                        csv.DictReader(io.StringIO(archive.read(path).decode("utf-8")))
                    )
                    observed_ids = [str(row["row_id"]) for row in rows]
                except (UnicodeDecodeError, KeyError, csv.Error):
                    findings.append(
                        {"code": "DOSSIER_SAMPLE_CSV_INVALID", "path": path}
                    )
                    continue
                expected_ids = [str(item) for item in sample.get(ids_field) or []]
                if observed_ids != expected_ids:
                    findings.append(
                        {
                            "code": "DOSSIER_SAMPLE_IDS_MISMATCH",
                            "path": path,
                            "expected_count": len(expected_ids),
                            "observed_count": len(observed_ids),
                        }
                    )
            if "model/coefficients.json" in names:
                coefficient_doc = json.loads(
                    archive.read("model/coefficients.json").decode("utf-8")
                )
                encoded_values = coefficient_doc.get("values")
                expected_coefficients = (
                    packaged_snapshot.get("model", {}).get("coefficients", {})
                    if isinstance(packaged_snapshot, Mapping)
                    else {}
                )
                observed_coefficients: Dict[str, float] = {}
                if isinstance(encoded_values, Mapping):
                    try:
                        observed_coefficients = {
                            str(name): float(
                                value.get("text")
                                if isinstance(value, Mapping)
                                else value
                            )
                            for name, value in encoded_values.items()
                        }
                    except (TypeError, ValueError):
                        observed_coefficients = {}
                try:
                    expected_numeric = {
                        str(name): float(value)
                        for name, value in expected_coefficients.items()
                    }
                except (AttributeError, TypeError, ValueError):
                    expected_numeric = {}
                if observed_coefficients != expected_numeric:
                    findings.append({"code": "DOSSIER_COEFFICIENTS_MISMATCH"})
            if "reproduction/spec.json" in names:
                reproduction = json.loads(
                    archive.read("reproduction/spec.json").decode("utf-8")
                )
                if reproduction.get("promised") is not True:
                    findings.append({"code": "DOSSIER_REPRODUCTION_NOT_PROMISED"})
            if require_complete:
                if manifest.get("completeness_status") != "complete":
                    findings.append({"code": "DOSSIER_COMPLETENESS_NOT_COMPLETE"})
                if manifest.get("numerical_reproduction_status") not in {
                    "ready",
                    "verified",
                }:
                    findings.append({"code": "DOSSIER_REPRODUCTION_NOT_READY"})
    except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError) as exc:
        findings.append({"code": "DOSSIER_INVALID", "message": str(exc)})
    return {
        "ok": not findings,
        "findings": findings,
        "manifest": manifest,
        "snapshot": packaged_snapshot,
    }


def build_submission_package(
    snapshot: Mapping[str, Any],
    report_context: Optional[Mapping[str, Any]],
    *,
    pdf_bytes: bytes,
    docx_bytes: Optional[bytes] = None,
    dossier_bytes: Optional[bytes] = None,
    requirement_map: Optional[Mapping[str, Any]] = None,
    signed_pdf_bytes: Optional[bytes] = None,
) -> bytes:
    """Create a reproducible package containing neutral evidence and mapping."""
    state = assess_document_state(snapshot, report_context)
    if not bytes(pdf_bytes).startswith(b"%PDF"):
        raise ValueError("pdf_bytes is not a PDF")
    comparison_snapshot = snapshot
    comparison_context = report_context
    if state.get("case_release_status") == "signed_integrity_verified":
        comparison_snapshot = copy.deepcopy(dict(snapshot))
        qctx = comparison_snapshot.setdefault("provenance", {}).setdefault(
            "qualification_context", {}
        )
        qctx["case_release_status"] = "ready_for_professional_signoff"
        qctx.pop("digital_signature", None)
        comparison_context = dict(report_context or {})
        for field in (
            "digital_signature",
            "signed_pdf_bytes",
            "unsigned_pdf_bytes",
            "signature_validation_context",
        ):
            comparison_context.pop(field, None)
    pdf_check = verify_report_consistency(
        pdf_bytes, comparison_snapshot, comparison_context
    )
    if not pdf_check.get("ok"):
        codes = ", ".join(
            item.get("code", "UNKNOWN") for item in pdf_check.get("findings") or []
        )
        raise ValueError(f"report PDF is inconsistent with the snapshot: {codes}")
    if docx_bytes is not None:
        docx_check = verify_docx_equivalence(docx_bytes, snapshot, report_context)
        if not docx_check.get("equivalent"):
            raise ValueError("DOCX is not the controlled export of this snapshot")
    if dossier_bytes is not None:
        dossier_check = _verify_dossier_archive(
            dossier_bytes,
            expected_snapshot=snapshot,
            require_complete=bool(state.get("is_final")),
        )
        if not dossier_check.get("ok"):
            codes = ", ".join(
                str(item.get("code")) for item in dossier_check.get("findings") or []
            )
            raise ValueError(
                "dossier ZIP failed internal integrity verification"
                + (f": {codes}; {dossier_check.get('findings')}" if codes else "")
            )
    signature = dict(
        (report_context or {}).get("digital_signature") or {}
    ) if isinstance(report_context, Mapping) else {}
    if signed_pdf_bytes is not None:
        signed = bytes(signed_pdf_bytes)
        if not signed.startswith(bytes(pdf_bytes)):
            raise ValueError("signed PDF is not an incremental revision of report.pdf")
        if hashlib.sha256(signed).hexdigest() != signature.get("signed_pdf_sha256"):
            raise ValueError("signed PDF does not match the verified signature record")
        if hashlib.sha256(bytes(pdf_bytes)).hexdigest() != signature.get("unsigned_pdf_sha256"):
            raise ValueError("report.pdf does not match the signature request")
    elif state.get("case_release_status") == "signed_integrity_verified":
        raise ValueError("signed document state requires signed_pdf_bytes")
    req = dict(requirement_map or {})
    profile_id = str(state.get("profile", {}).get("id") or "")
    if req and str(req.get("profile_id") or "") != profile_id:
        raise ValueError(
            "requirement_map.profile_id does not match the resolved qualification profile"
        )
    req_findings = _verify_requirement_map(req, profile_id) if req else []
    if state.get("is_final") and (dossier_bytes is None or not req or req_findings):
        codes = ", ".join(item["code"] for item in req_findings)
        raise ValueError(
            "final institutional package requires a complete dossier and substantive requirement map"
            + (f": {codes}" if codes else "")
        )
    if req_findings:
        raise ValueError(
            "invalid requirement map: "
            + ", ".join(item["code"] for item in req_findings)
        )
    files: Dict[str, bytes] = {
        "document/report.pdf": bytes(pdf_bytes),
        "requirements/map.json": canonical_json(req).encode("utf-8"),
        "qualification/document_state.json": canonical_json(state).encode("utf-8"),
    }
    if docx_bytes is not None:
        files["document/report.docx"] = bytes(docx_bytes)
    if dossier_bytes is not None:
        files["evidence/dossier.zip"] = bytes(dossier_bytes)
    if signed_pdf_bytes is not None:
        files["document/report.signed.pdf"] = bytes(signed_pdf_bytes)
    metadata = {
        "schema_version": "MP-SUBMISSION/1",
        "profile_id": profile_id or None,
        "recipient_id": state.get("profile", {}).get("recipient_id"),
        "case_release_status": state.get("case_release_status"),
        "document_is_final": bool(state.get("is_final")),
        "institution_acceptance": state.get("institution_acceptance") or {},
        "external_submission_performed": False,
        "branding": "neutral",
        "files": {},
    }
    types = {
        "document/report.pdf": ("application/pdf", "qualified_report"),
        "document/report.docx": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "editable_report",
        ),
        "document/report.signed.pdf": ("application/pdf", "cryptographically_signed_report"),
        "evidence/dossier.zip": ("application/zip", "audit_dossier"),
        "requirements/map.json": ("application/json", "institution_requirement_map"),
        "qualification/document_state.json": (
            "application/json",
            "qualification_state",
        ),
    }
    for name, data in files.items():
        metadata["files"][name] = _entry(data, *types[name])
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name in sorted(files):
            _write(archive, name, files[name])
        _write(archive, MANIFEST, canonical_json(metadata).encode("utf-8"))
    return out.getvalue()


def verify_submission_package(package_bytes: bytes) -> Dict[str, Any]:
    findings = []
    try:
        with zipfile.ZipFile(io.BytesIO(package_bytes), "r") as archive:
            bad = archive.testzip()
            names = set(archive.namelist())
            if bad:
                findings.append({"code": "SUBMISSION_CRC_ERROR", "member": bad})
            if MANIFEST not in names:
                return {
                    "ok": False,
                    "findings": [{"code": "SUBMISSION_MANIFEST_MISSING"}],
                }
            manifest = json.loads(archive.read(MANIFEST).decode("utf-8"))
            listed = dict(manifest.get("files") or {})
            extras = sorted(names - set(listed) - {MANIFEST})
            missing = sorted(set(listed) - names)
            if extras:
                findings.append({"code": "SUBMISSION_UNLISTED_FILE", "paths": extras})
            if missing:
                findings.append({"code": "SUBMISSION_FILE_MISSING", "paths": missing})
            for name, entry in listed.items():
                if name not in names:
                    continue
                data = archive.read(name)
                digest = hashlib.sha256(data).hexdigest()
                if digest != entry.get("sha256"):
                    findings.append({"code": "SUBMISSION_HASH_MISMATCH", "path": name})
                if len(data) != entry.get("size"):
                    findings.append({"code": "SUBMISSION_SIZE_MISMATCH", "path": name})
            if "document/report.pdf" in names and not archive.read(
                "document/report.pdf"
            ).startswith(b"%PDF"):
                findings.append({"code": "SUBMISSION_REPORT_NOT_PDF"})
            if "document/report.signed.pdf" in names:
                signed = archive.read("document/report.signed.pdf")
                unsigned = archive.read("document/report.pdf") if "document/report.pdf" in names else b""
                if not signed.startswith(unsigned):
                    findings.append({"code": "SUBMISSION_SIGNED_REPORT_BASE_MISMATCH"})
            if "document/report.docx" in names:
                try:
                    with zipfile.ZipFile(
                        io.BytesIO(archive.read("document/report.docx")), "r"
                    ) as docx:
                        docx_names = set(docx.namelist())
                    if "word/document.xml" not in docx_names:
                        findings.append(
                            {"code": "SUBMISSION_DOCX_REQUIRED_PART_MISSING"}
                        )
                except zipfile.BadZipFile:
                    findings.append({"code": "SUBMISSION_DOCX_INVALID"})
            if "evidence/dossier.zip" in names:
                dossier = _verify_dossier_archive(
                    archive.read("evidence/dossier.zip"),
                    require_complete=bool(manifest.get("document_is_final")),
                )
                findings.extend(dossier.get("findings") or [])
            if manifest.get("document_is_final"):
                if "evidence/dossier.zip" not in names:
                    findings.append({"code": "SUBMISSION_FINAL_DOSSIER_MISSING"})
                if "requirements/map.json" not in names:
                    findings.append({"code": "SUBMISSION_REQUIREMENT_MAP_MISSING"})
                else:
                    requirement_map = json.loads(
                        archive.read("requirements/map.json").decode("utf-8")
                    )
                    findings.extend(
                        _verify_requirement_map(
                            requirement_map, str(manifest.get("profile_id") or "")
                        )
                    )
    except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {
            "ok": False,
            "findings": [{"code": "SUBMISSION_INVALID", "message": str(exc)}],
        }
    return {"ok": not findings, "findings": findings, "manifest": manifest}
