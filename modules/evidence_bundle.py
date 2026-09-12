"""C12 evidence dossier: local evaluation package and safe numeric reproduction.

Public entry point (MP/1):

    build_evidence_bundle(snapshot, input_bundle, prepared_dataset, artifacts, output_dir) -> manifest

The snapshot is written first and never mutated with artifact hashes. The
manifest lists SHA-256 / size / type / version / function of every packaged
file plus input/code/schema/policy IDs, and does not include its own hash.

Numeric reconstruction reads only declared coefficients, a whitelist of
transforms, and optional residual context from disk. Unknown pickle, eval,
exec, or in-memory model objects are refused.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import posixpath
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from .provenance import (
    BUNDLE_VERSION,
    COMPLETENESS_DECLARED,
    COMPLETENESS_MISSING,
    COMPLETENESS_PRESENT,
    COMPLETENESS_VERIFIED,
    SCHEMA_VERSION_MP,
    CompletenessLedger,
    canonical_json,
    encode_number,
    is_formula_cell,
    iter_regular_files,
    looks_like_pickle,
    neutralize_formula_cell,
    number_as_float64,
    number_to_cell_text,
    policy_id_from_mapping,
    refuse_code_execution,
    relative_posix,
    resolve_inside,
    sanitize_internal_name,
    schema_id_from_mapping,
    sha256_file,
    strip_dataset_from_log_payload,
    write_bytes_atomic,
    write_json,
)
from .report_presenter.qualification import signable_snapshot_sha256

MANIFEST_NAME = "MANIFEST.json"
_ZIP_TIME = (2020, 1, 1, 0, 0, 0)
CSV_DELIMITER = ","
CSV_QUOTECHAR = '"'
CSV_LINETERMINATOR = "\n"
CSV_ENCODING = "utf-8"

DEFAULT_TOLERANCE = {
    "point_abs": 1e-8,
    "point_rel": 1e-10,
    "interval_abs": 1e-6,
    "interval_rel": 1e-8,
}

# Closed whitelist matching modules.transformations.Transformer names plus aliases.
X_TRANSFORM_WHITELIST = frozenset(
    {
        "linear",
        "identity",
        "none",
        "inverse",
        "inv",
        "ln",
        "log",
        "log10",
        "sqr",
        "square",
        "sqrt",
        "inv_sqr",
        "inv_sqrt",
    }
)

# Inverse of a declared *target* transform, applied to Xb to recover original unit.
Y_INVERSE_WHITELIST = frozenset(
    {
        "linear",
        "identity",
        "none",
        "ln",
        "log",
        "log10",
        "sqrt",
        "sqr",
        "square",
        "inverse",
        "inv",
    }
)

CRITICAL_REPRODUCTION_PARTS = (
    "model_coefficients",
    "subject_design",
    "y_transformation",
)

COMPONENT_ORDER = (
    "frozen_snapshot",
    "original_base",
    "interpreted_base",
    "used_sample",
    "excluded_rows",
    "identification_columns",
    "feature_schema",
    "encoder_state",
    "missing_policy",
    "outlier_policy",
    "search_policy",
    "evaluation_policy",
    "model_coefficients",
    "transformations",
    "subject_design",
    "residual_context",
    "dates",
    "versions",
    "documentary_sources",
    "photos_documents",
    "report_artifact",
    "source_input_bytes",
    "qualification_context",
    "identifier_map",
    "representation_map",
    "review_history",
    "signature_record",
    "docx_artifact",
)


def build_evidence_bundle(
    snapshot: Optional[Mapping[str, Any]],
    input_bundle: Optional[Mapping[str, Any]],
    prepared_dataset: Optional[Mapping[str, Any]],
    artifacts: Optional[Mapping[str, Any]],
    output_dir: Union[str, Path],
) -> Dict[str, Any]:
    """Package a local evaluation dossier and return its manifest mapping.

    ``snapshot`` is treated as already frozen by C10: it is serialized first
    and never updated with hashes of later artifacts. Reproduction is promised
    only when every critical part is present on disk (not merely in memory).
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    out = out.resolve()

    snap = _as_mapping(snapshot)
    ib = _as_mapping(input_bundle)
    prep = _as_mapping(prepared_dataset)
    arts = _as_mapping(artifacts)
    ledger = CompletenessLedger()
    files_meta: List[Dict[str, Any]] = []

    # --- 1. Frozen snapshot BEFORE any artifact registry ---
    snap_rel = "snapshot/result_snapshot.json"
    snap_path = resolve_inside(out, snap_rel)
    frozen_bytes = arts.get("snapshot_bytes")
    if isinstance(frozen_bytes, (bytes, bytearray)):
        try:
            supplied_snapshot = json.loads(bytes(frozen_bytes).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"artifacts.snapshot_bytes is not valid JSON: {exc}") from exc
        if not isinstance(supplied_snapshot, Mapping) or canonical_json(
            supplied_snapshot
        ) != canonical_json(snap):
            raise ValueError(
                "artifacts.snapshot_bytes does not represent the supplied snapshot mapping"
            )
        write_bytes_atomic(snap_path, bytes(frozen_bytes))
        ledger.set(
            "frozen_snapshot",
            COMPLETENESS_PRESENT,
            declared=True,
            source="artifacts.snapshot_bytes",
            notes="Exact frozen bytes supplied by caller; not re-serialized.",
        )
    elif snap:
        write_json(snap_path, snap)
        ledger.set(
            "frozen_snapshot",
            COMPLETENESS_PRESENT,
            declared=True,
            source="snapshot",
            notes="Serialized from the provided ResultSnapshot mapping.",
        )
    else:
        ledger.set(
            "frozen_snapshot",
            COMPLETENESS_MISSING,
            notes="No snapshot mapping or snapshot_bytes were provided.",
        )
        # A dossier without a snapshot is still a completeness record, not a fake result.
    if snap_path.is_file():
        _register(files_meta, out, snap_rel, "application/json", snap.get("schema_version") or SCHEMA_VERSION_MP, "frozen_result_snapshot")
        if snap.get("schema_version") == SCHEMA_VERSION_MP:
            ledger.set(
                "frozen_snapshot",
                COMPLETENESS_VERIFIED,
                declared=True,
                source="snapshot.schema_version",
                notes="schema_version is MP/1.",
                evidence={"schema_version": SCHEMA_VERSION_MP, "sha256": sha256_file(snap_path)},
            )

    request_spec = _first_mapping(
        arts.get("request_spec"),
        snap.get("request_spec"),
        ib.get("request_spec"),
        prep.get("request_spec"),
    )
    roles = _as_mapping(request_spec.get("roles"))
    units = _as_mapping(request_spec.get("units"))

    used_ids, excluded_ids, sample_counts = _sample_ids(snap, ib, prep)
    row_ledger = _row_ledger(ib, prep)

    # --- 2. Tables (full used + excluded; PDF is never a substitute) ---
    raw_cols, raw_rows = frame_to_rows(ib.get("raw_frame"))
    parsed_cols, parsed_rows = frame_to_rows(ib.get("parsed_frame") if ib.get("parsed_frame") is not None else ib.get("raw_frame"))
    base_cols, base_rows = frame_to_rows(prep.get("base_frame"))
    ident_cols, ident_rows = _identification_rows(ib, prep, request_spec, raw_cols, raw_rows, parsed_cols, parsed_rows)

    _write_table_pair(
        out,
        files_meta,
        ledger,
        component="original_base",
        function="original_market_base",
        rel="data/original_base.csv",
        viz_rel="data/visualization/original_base.safe.csv",
        columns=raw_cols,
        rows=raw_rows,
        roles=roles,
        units=units,
        notes_if_missing="Original/raw base was not provided on the InputBundle; not fabricated.",
    )
    _write_table_pair(
        out,
        files_meta,
        ledger,
        component="interpreted_base",
        function="interpreted_market_base",
        rel="data/interpreted_base.csv",
        viz_rel="data/visualization/interpreted_base.safe.csv",
        columns=parsed_cols,
        rows=parsed_rows,
        roles=roles,
        units=units,
        notes_if_missing="Interpreted/parsed base was not provided; not fabricated.",
    )

    used_rows, used_cols = _select_rows_by_id(parsed_rows or raw_rows or base_rows, parsed_cols or raw_cols or base_cols, used_ids)
    if not used_rows and base_rows:
        used_rows, used_cols = _select_rows_by_id(base_rows, base_cols, used_ids)
    _write_table_pair(
        out,
        files_meta,
        ledger,
        component="used_sample",
        function="effective_sample",
        rel="data/used_sample.csv",
        viz_rel="data/visualization/used_sample.safe.csv",
        columns=used_cols,
        rows=used_rows,
        roles=roles,
        units=units,
        extra_meta={"row_ids": list(used_ids), "n": len(used_ids)},
        notes_if_missing="Effective sample rows were not recoverable from the provided frames.",
    )

    excluded_rows, excluded_cols = _select_rows_by_id(parsed_rows or raw_rows, parsed_cols or raw_cols, excluded_ids)
    excluded_table = _attach_exclusion_reasons(excluded_rows, excluded_cols, excluded_ids, row_ledger)
    _write_table_pair(
        out,
        files_meta,
        ledger,
        component="excluded_rows",
        function="exclusions_with_justifications",
        rel="data/excluded_rows.csv",
        viz_rel="data/visualization/excluded_rows.safe.csv",
        columns=excluded_table[1],
        rows=excluded_table[0],
        roles=roles,
        units=units,
        extra_meta={"row_ids": list(excluded_ids), "n": len(excluded_ids)},
        notes_if_missing="No exclusion ledger/rows were provided; not fabricated.",
        allow_empty=True,
    )

    _write_table_pair(
        out,
        files_meta,
        ledger,
        component="identification_columns",
        function="identification_and_source_columns",
        rel="data/identification_columns.csv",
        viz_rel="data/visualization/identification_columns.safe.csv",
        columns=ident_cols,
        rows=ident_rows,
        roles=roles,
        units=units,
        notes_if_missing="No identifier/source columns were declared or present; not fabricated.",
        allow_empty=True,
    )

    # Optional original upload bytes to verify input_sha256 independently of CSV export.
    source_bytes = arts.get("source_bytes") or ib.get("source_bytes") or ib.get("file_bytes")
    declared_input_sha = snap.get("input_sha256") or ib.get("input_sha256")
    if isinstance(source_bytes, (bytes, bytearray)):
        src_rel = "data/source_input.bin"
        src_path = resolve_inside(out, src_rel)
        write_bytes_atomic(src_path, bytes(source_bytes))
        digest = sha256_file(src_path)
        _register(files_meta, out, src_rel, "application/octet-stream", SCHEMA_VERSION_MP, "source_input_bytes")
        if declared_input_sha and digest == declared_input_sha:
            ledger.set(
                "source_input_bytes",
                COMPLETENESS_VERIFIED,
                declared=True,
                source="snapshot.input_sha256",
                evidence={"sha256": digest},
            )
        else:
            ledger.set(
                "source_input_bytes",
                COMPLETENESS_PRESENT,
                declared=bool(declared_input_sha),
                notes="Original bytes packaged; snapshot.input_sha256 missing or does not match.",
                evidence={"sha256": digest, "declared_input_sha256": declared_input_sha},
            )
    elif declared_input_sha:
        ledger.set(
            "source_input_bytes",
            COMPLETENESS_DECLARED,
            declared=True,
            source="snapshot.input_sha256",
            notes="input_sha256 declared on the snapshot; original upload bytes were not packaged.",
            evidence={"declared_input_sha256": declared_input_sha},
        )
    else:
        ledger.set(
            "source_input_bytes",
            COMPLETENESS_MISSING,
            notes="No original upload bytes and no declared input_sha256.",
        )

    # --- 3. Schema, encoder, policies, model ---
    feature_schema = _first_mapping(prep.get("feature_schema"), arts.get("feature_schema"), snap.get("feature_schema"))
    encoder_state = _first_mapping(prep.get("encoder_state"), arts.get("encoder_state"), snap.get("encoder_state"))
    _write_declared_json(
        out, files_meta, ledger, "feature_schema", "model/feature_schema.json",
        feature_schema, "feature_schema", "Declarative feature schema from PreparedDataset.",
    )
    if encoder_state and _encoder_looks_executable(encoder_state):
        ledger.set(
            "encoder_state",
            COMPLETENESS_MISSING,
            declared=True,
            notes="encoder_state contained executable/code-like material and was refused; not packaged.",
        )
    else:
        _write_declared_json(
            out, files_meta, ledger, "encoder_state", "model/encoder_state.json",
            encoder_state, "encoder_state", "Declarative encoder state (not executable).",
        )

    policies = {
        "missing_policy": _first_mapping(
            request_spec.get("missing_policy"), arts.get("missing_policy"), snap.get("missing_policy")
        ),
        "outlier_policy": _first_mapping(
            request_spec.get("outlier_policy"), arts.get("outlier_policy"), snap.get("outlier_policy")
        ),
        "search_policy": _first_mapping(
            request_spec.get("search_policy"), arts.get("search_policy"), snap.get("search_policy")
        ),
        "evaluation_policy": _first_mapping(
            request_spec.get("evaluation_policy"), arts.get("evaluation_policy"), snap.get("evaluation_policy")
        ),
        "value_policy": _first_mapping(
            request_spec.get("value_policy"), arts.get("value_policy"), snap.get("value_policy")
        ),
    }
    for name, payload in policies.items():
        _write_declared_json(
            out, files_meta, ledger, name, f"policies/{name}.json",
            payload, name, f"Policy {name} as used by the evaluation; defaults are not invented.",
        )
    if request_spec:
        write_json(resolve_inside(out, "policies/request_spec.json"), request_spec)
        _register(files_meta, out, "policies/request_spec.json", "application/json", SCHEMA_VERSION_MP, "request_spec")

    coefficients_src = _coefficients_source(snap, arts)
    coef_payload = _integral_coefficients_payload(coefficients_src)
    if coef_payload:
        write_json(resolve_inside(out, "model/coefficients.json"), coef_payload)
        _register(files_meta, out, "model/coefficients.json", "application/json", SCHEMA_VERSION_MP, "model_coefficients")
        ledger.set(
            "model_coefficients",
            COMPLETENESS_PRESENT,
            declared=True,
            source="snapshot.model.coefficients or artifacts.coefficients",
            notes="Integral coefficients stored as typed numeric encodings; display formula is not used.",
            evidence={"n_coefficients": len(coef_payload.get("order") or [])},
        )
    else:
        formula = None
        model = _as_mapping(snap.get("model"))
        formula = model.get("formula") or arts.get("formula")
        if formula:
            ledger.set(
                "model_coefficients",
                COMPLETENESS_MISSING,
                declared=True,
                notes="Only a display formula was available (typically 4-decimal). That is not integral coefficients; not used as reproduction material.",
                evidence={"formula_present": True},
            )
        else:
            ledger.set(
                "model_coefficients",
                COMPLETENESS_MISSING,
                notes="No coefficients were provided; in-memory model_object is not packaged and cannot be promised as reproduction.",
            )

    transformations = _transformations_payload(snap, arts, request_spec)
    if transformations:
        write_json(resolve_inside(out, "model/transformations.json"), transformations)
        _register(files_meta, out, "model/transformations.json", "application/json", SCHEMA_VERSION_MP, "transformations")
        y_name = _as_mapping(transformations.get("y_transformation")).get("name")
        if y_name:
            ledger.set("y_transformation", COMPLETENESS_PRESENT, declared=True, source="transformations.y_transformation")
        else:
            ledger.set("y_transformation", COMPLETENESS_MISSING, notes="y_transformation name was not declared.")
        ledger.set("transformations", COMPLETENESS_PRESENT, declared=True, source="model/transformations.json")
    else:
        ledger.set("transformations", COMPLETENESS_MISSING, notes="No transformation declarations were provided.")
        ledger.set("y_transformation", COMPLETENESS_MISSING, notes="No y_transformation declaration.")

    subject_design = _subject_design_payload(snap, arts, transformations)
    if subject_design:
        write_json(resolve_inside(out, "model/subject_design.json"), subject_design)
        _register(files_meta, out, "model/subject_design.json", "application/json", SCHEMA_VERSION_MP, "subject_design")
        ledger.set("subject_design", COMPLETENESS_PRESENT, declared=True, source="artifacts.subject_design or snapshot")
    else:
        ledger.set(
            "subject_design",
            COMPLETENESS_MISSING,
            notes="No subject design row / raw values were packaged; prediction cannot be reconstructed from memory.",
        )

    provided_residual_context = _first_mapping(
        arts.get("residual_context"),
        _as_mapping(snap.get("model")).get("residual_context"),
    )
    residual_state = _first_mapping(
        arts.get("residual_state"),
        _as_mapping(snap.get("model")).get("residual_state"),
    )
    mapped_residual = _residual_context_for_reproduction(provided_residual_context or residual_state)
    if mapped_residual:
        residual_context = mapped_residual
    elif provided_residual_context:
        residual_context = dict(provided_residual_context)
    else:
        residual_context = {}
    if residual_state:
        write_json(resolve_inside(out, "model/residual_state.json"), residual_state)
        _register(files_meta, out, "model/residual_state.json", "application/json", BUNDLE_VERSION, "residual_state")
        ledger.set("residual_state", COMPLETENESS_PRESENT, declared=True, source="artifacts.residual_state")
    else:
        declared_residual = bool(_as_mapping(snap.get("model")).get("coefficients"))
        ledger.set(
            "residual_state",
            COMPLETENESS_MISSING,
            declared=declared_residual,
            absence_kind="lost_by_integration" if declared_residual else "not_provided",
            notes=(
                "Residual/design state was used in-process but not packaged."
                if declared_residual
                else "No residual state was provided; not fabricated."
            ),
        )
    if residual_context:
        write_json(resolve_inside(out, "model/residual_context.json"), residual_context)
        _register(files_meta, out, "model/residual_context.json", "application/json", SCHEMA_VERSION_MP, "residual_context")
        ledger.set("residual_context", COMPLETENESS_PRESENT, declared=True, source="artifacts.residual_context or residual_state")
    else:
        ledger.set(
            "residual_context",
            COMPLETENESS_MISSING,
            absence_kind="not_provided" if not residual_state else "lost_by_integration",
            notes="No residual context; interval reconstruction is unsupported (limitation, not a fabricated IC).",
        )

    dates = {
        "reference_date": request_spec.get("reference_date") if request_spec else snap.get("reference_date"),
        "inspection_date": request_spec.get("inspection_date") if request_spec else None,
        "generated_at": snap.get("generated_at"),
    }
    if dates["reference_date"] is None and snap.get("reference_date") is not None:
        dates["reference_date"] = snap.get("reference_date")
    write_json(resolve_inside(out, "meta/dates.json"), dates)
    _register(files_meta, out, "meta/dates.json", "application/json", SCHEMA_VERSION_MP, "dates")
    if dates["reference_date"] or dates["inspection_date"]:
        pending = []
        if dates["reference_date"] is None:
            pending.append("reference_date")
        if dates["inspection_date"] is None:
            pending.append("inspection_date")
        ledger.set(
            "dates",
            COMPLETENESS_PRESENT if not pending else COMPLETENESS_DECLARED,
            declared=True,
            notes=("Unknown dates remain pending; current date / BRL were not assumed. " + (", ".join(pending) if pending else "")).strip(),
            evidence=dates,
        )
    else:
        ledger.set(
            "dates",
            COMPLETENESS_MISSING,
            notes="reference_date and inspection_date were not declared; they remain pending (not assumed).",
        )

    versions = {
        "schema_version": snap.get("schema_version") or SCHEMA_VERSION_MP,
        "bundle_version": BUNDLE_VERSION,
        "code_sha": snap.get("code_sha"),
        "input_sha256": declared_input_sha,
        "dataset_sha256": prep.get("dataset_sha256") or snap.get("dataset_sha256"),
        "job_id": snap.get("job_id"),
        "project_id": snap.get("project_id"),
    }
    if versions["code_sha"]:
        ledger.set("versions", COMPLETENESS_PRESENT, declared=True, source="snapshot.code_sha")
    else:
        ledger.set("versions", COMPLETENESS_MISSING, notes="code_sha was not declared on the snapshot; not invented from this process.")
    write_json(resolve_inside(out, "meta/versions.json"), versions)
    _register(files_meta, out, "meta/versions.json", "application/json", SCHEMA_VERSION_MP, "versions")

    # Documentary sources / photos: never generate substitutes.
    documentary = _first_mapping(
        arts.get("documentary"),
        _as_mapping(snap.get("validation")).get("documentary"),
    )
    photos = arts.get("photos") or arts.get("documents") or documentary.get("files") or []
    citations = documentary.get("sources") or documentary.get("items") or documentary.get("citations") or []
    if citations:
        write_json(resolve_inside(out, "meta/documentary_sources.json"), {"sources": citations})
        _register(files_meta, out, "meta/documentary_sources.json", "application/json", SCHEMA_VERSION_MP, "documentary_sources")
        ledger.set("documentary_sources", COMPLETENESS_DECLARED, declared=True, source="snapshot.validation.documentary or artifacts.documentary")
    elif documentary:
        ledger.set(
            "documentary_sources",
            COMPLETENESS_DECLARED,
            declared=True,
            notes="Documentary block present without citable sources list.",
        )
    else:
        ledger.set("documentary_sources", COMPLETENESS_MISSING, notes="No documentary sources were supplied.")

    photo_written = 0
    if isinstance(photos, list) and photos:
        for idx, photo in enumerate(photos):
            if not isinstance(photo, Mapping):
                continue
            raw = photo.get("bytes") or photo.get("content")
            if not isinstance(raw, (bytes, bytearray)):
                continue
            fname = sanitize_internal_name(str(photo.get("filename") or f"document_{idx}"))
            rel = f"artifacts/documents/{fname}"
            write_bytes_atomic(resolve_inside(out, rel), bytes(raw))
            _register(files_meta, out, rel, str(photo.get("type") or "application/octet-stream"), SCHEMA_VERSION_MP, "documentary_file")
            photo_written += 1
        if photo_written:
            ledger.set("photos_documents", COMPLETENESS_PRESENT, declared=True, source="artifacts.photos")
        else:
            ledger.set(
                "photos_documents",
                COMPLETENESS_MISSING,
                declared=True,
                notes="Photos/documents were declared but no bytes were provided; text is not used as a substitute.",
            )
    else:
        declared_photos = bool(documentary) and bool(documentary.get("photos_required") or documentary.get("missing_photos"))
        ledger.set(
            "photos_documents",
            COMPLETENESS_MISSING,
            declared=declared_photos,
            notes="No photo/document bytes were provided; absence is not filled with generated imagery or text.",
        )

    # Opaque artifacts (report PDF, charts, etc.). Never executed.
    packed_artifacts = arts.get("files") or arts.get("artifacts") or {}
    if isinstance(packed_artifacts, Mapping):
        for raw_name, spec in packed_artifacts.items():
            _write_opaque_artifact(out, files_meta, raw_name, spec)
    report = arts.get("report_pdf") or arts.get("report")
    if report is not None:
        _write_opaque_artifact(out, files_meta, "report.pdf", report, function="c08_report_pdf")
        ledger.set("report_artifact", COMPLETENESS_PRESENT, declared=True, source="artifacts.report_pdf")
    else:
        ledger.set(
            "report_artifact",
            COMPLETENESS_MISSING,
            notes="No C08 PDF was supplied. A PDF summary would not replace the full used/excluded tables in any case.",
        )

    report_docx = arts.get("report_docx")
    if report_docx is not None:
        _write_opaque_artifact(
            out, files_meta, "report.docx", report_docx,
            function="editable_report_same_snapshot",
        )
        ledger.set(
            "docx_artifact", COMPLETENESS_PRESENT, declared=True,
            source="artifacts.report_docx",
        )
    else:
        ledger.set("docx_artifact", COMPLETENESS_MISSING, notes="No DOCX export was supplied.")

    provenance = _as_mapping(snap.get("provenance"))
    qualification = _as_mapping(provenance.get("qualification_context"))
    if qualification:
        write_json(resolve_inside(out, "qualification/context.json"), qualification)
        _register(
            files_meta, out, "qualification/context.json", "application/json",
            qualification.get("schema_version") or "MP-QUAL/1", "qualification_context",
        )
        ledger.set(
            "qualification_context", COMPLETENESS_PRESENT, declared=True,
            source="snapshot.provenance.qualification_context",
        )
    else:
        ledger.set(
            "qualification_context", COMPLETENESS_MISSING,
            notes="No MP-QUAL/1 qualification context was supplied; final issuance is not evidenced.",
        )

    identifier_map = _first_mapping(
        arts.get("identifier_map"), ib.get("column_map"), prep.get("column_map")
    )
    if identifier_map:
        write_json(resolve_inside(out, "data/identifier_map.json"), identifier_map)
        _register(
            files_meta, out, "data/identifier_map.json", "application/json",
            BUNDLE_VERSION, "identifier_map",
        )
        ledger.set(
            "identifier_map", COMPLETENESS_PRESENT, declared=True,
            source="input_bundle.column_map",
        )
    else:
        ledger.set(
            "identifier_map", COMPLETENESS_MISSING,
            notes="No original-to-internal identifier map was supplied.",
        )

    representation_map = {
        "schema_version": "MP-EVIDENCE-MAP/1",
        "representations": [
            {"id": "source_bytes", "path": "data/source_input.bin", "role": "original_bytes"},
            {"id": "original_base", "path": "data/original_base.csv", "role": "original_tabular_representation"},
            {"id": "interpreted_base", "path": "data/interpreted_base.csv", "role": "parsed_representation"},
            {"id": "used_sample", "path": "data/used_sample.csv", "role": "effective_model_sample"},
            {"id": "excluded_rows", "path": "data/excluded_rows.csv", "role": "excluded_with_reasons"},
        ],
        "identifier_map": "data/identifier_map.json" if identifier_map else None,
        "row_identity": "row_id",
        "equivalence": (
            "Representations are equivalent only through the declared identifier/column maps and ledger; "
            "byte identity is neither assumed nor claimed."
        ),
    }
    write_json(resolve_inside(out, "data/representation_map.json"), representation_map)
    _register(
        files_meta, out, "data/representation_map.json", "application/json",
        "MP-EVIDENCE-MAP/1", "representation_map",
    )
    ledger.set(
        "representation_map", COMPLETENESS_PRESENT, declared=True,
        source="packaged evidence paths",
    )

    review_events = qualification.get("review_events") or arts.get("review_events") or []
    if review_events:
        write_json(resolve_inside(out, "review/history.json"), {"events": review_events})
        _register(
            files_meta, out, "review/history.json", "application/json",
            "MP-QUAL/1", "review_history",
        )
        ledger.set(
            "review_history", COMPLETENESS_PRESENT, declared=True,
            source="qualification.review_events",
        )
    else:
        ledger.set("review_history", COMPLETENESS_MISSING, notes="No review events were supplied.")

    signature_record = _as_mapping(
        arts.get("signature_record") or qualification.get("digital_signature")
    )
    if signature_record:
        write_json(resolve_inside(out, "signature/verification.json"), signature_record)
        _register(
            files_meta, out, "signature/verification.json", "application/json",
            signature_record.get("schema_version") or "MP-SIGN/1", "signature_record",
        )
        ledger.set(
            "signature_record", COMPLETENESS_PRESENT, declared=True,
            source="artifacts.signature_record",
        )
    else:
        ledger.set(
            "signature_record", COMPLETENESS_MISSING,
            notes="No digital signature verification record was supplied; image signatures are not substituted.",
        )

    signed_report = arts.get("signed_report_pdf")
    if signed_report is not None:
        _write_opaque_artifact(
            out, files_meta, "signed_report.pdf", signed_report,
            function="signed_report_exact_bytes",
        )

    report_revisions = arts.get("report_revisions") or []
    if report_revisions:
        write_json(
            resolve_inside(out, "review/document_revisions.json"),
            {"revisions": report_revisions},
        )
        _register(
            files_meta, out, "review/document_revisions.json", "application/json",
            "MP-QUAL/1", "document_revision_history",
        )

    # Sample-count cross-check evidence (not a second evaluation).
    sample_audit = {
        "snapshot_sample": _as_mapping(snap.get("sample")),
        "used_row_ids": list(used_ids),
        "excluded_row_ids": list(excluded_ids),
        "used_table_rows": len(used_rows or []),
        "excluded_table_rows": len(excluded_table[0] or []),
        "identification_table_rows": len(ident_rows or []),
        "received_rows": (len(raw_rows) if raw_rows is not None else (len(parsed_rows) if parsed_rows is not None else None)),
        "n_coefficients": len((coef_payload or {}).get("order") or []),
        "counts": sample_counts,
    }
    write_json(resolve_inside(out, "meta/sample_audit.json"), sample_audit)
    _register(files_meta, out, "meta/sample_audit.json", "application/json", SCHEMA_VERSION_MP, "sample_audit")

    critical_ok = all(
        ledger.status_of(part) in {COMPLETENESS_PRESENT, COMPLETENESS_VERIFIED}
        for part in CRITICAL_REPRODUCTION_PARTS
    )
    if ledger.status_of("y_transformation") == COMPLETENESS_MISSING:
        critical_ok = False
    reproduction_spec = {
        "method": "declared_coefficients_whitelist_transforms_inverse_to_original_unit",
        "promised": bool(critical_ok and coef_payload and subject_design),
        "reason": (
            None
            if critical_ok
            else "One or more critical parts exist only as a declaration, a display formula, or an in-memory object; reproduction is not promised."
        ),
        "tolerance": dict(DEFAULT_TOLERANCE),
        "determinism": (
            "Reconstruction is a pure function of packaged JSON files. "
            "Coefficient arithmetic uses float64 values recovered from ieee_hex/decimal text, "
            "in the declared feature order, with no RNG. "
            "Two runs on an unchanged package emit identical primary numbers."
        ),
        "refuses": ["pickle.loads", "eval", "exec", "compile", "in-memory model_object"],
        "critical_parts": list(CRITICAL_REPRODUCTION_PARTS),
        "interval_policy": (
            "Intervals are reconstructed only when residual_context declares method, t_crit, "
            "std_error and subject leverage/xtx_inv, and only on the scale declared by "
            "interval_scale. A log/target transform does not produce a normative IC by naive inversion."
        ),
        "csv": {
            "encoding": CSV_ENCODING,
            "delimiter": CSV_DELIMITER,
            "quotechar": CSV_QUOTECHAR,
            "lineterminator": "LF",
            "raw_vs_visualization": (
                "data/*.csv preserves original cell text (including formula-like values). "
                "data/visualization/*.safe.csv prefixes formula-like cells so spreadsheets "
                "do not execute them. The raw evidence file is never rewritten for safety."
            ),
        },
    }
    write_json(resolve_inside(out, "reproduction/spec.json"), reproduction_spec)
    _register(files_meta, out, "reproduction/spec.json", "application/json", BUNDLE_VERSION, "reproduction_spec")

    completeness_doc = ledger.to_dict()
    write_json(resolve_inside(out, "completeness/ledger.json"), completeness_doc)
    _register(files_meta, out, "completeness/ledger.json", "application/json", BUNDLE_VERSION, "completeness_ledger")

    share_selection = arts.get("share_selection")
    if not isinstance(share_selection, list):
        share_selection = [
            "frozen_result_snapshot",
            "model_coefficients",
            "transformations",
            "feature_schema",
            "encoder_state",
            "request_spec",
            "missing_policy",
            "outlier_policy",
            "search_policy",
            "evaluation_policy",
            "completeness_ledger",
            "reproduction_spec",
            "versions",
            "dates",
            "sample_audit",
        ]
    share_doc = {
        "mode": "explicit_selection",
        "include_functions": list(share_selection),
        "original_retained": True,
        "public_pr_policy": "synthetic_fixtures_only",
        "notes": (
            "Selecting contents for sharing copies the named functions into a destination. "
            "It never deletes or rewrites the original local package. "
            "Public PR evidence must use labeled synthetic fixtures, not this local market base."
        ),
    }
    write_json(resolve_inside(out, "share/selection.json"), share_doc)
    _register(files_meta, out, "share/selection.json", "application/json", BUNDLE_VERSION, "share_selection")

    schema_id = schema_id_from_mapping(feature_schema) if feature_schema else None
    policy_id = policy_id_from_mapping({k: v for k, v in policies.items() if v}) if any(policies.values()) else None
    files_meta_sorted = sorted(files_meta, key=lambda item: item["path"])

    manifest = {
        "schema_version": SCHEMA_VERSION_MP,
        "bundle_version": BUNDLE_VERSION,
        "input_id": declared_input_sha,
        "code_id": versions.get("code_sha"),
        "schema_id": schema_id,
        "policy_id": policy_id,
        "snapshot_sha256": sha256_file(snap_path) if snap_path.is_file() else None,
        "job_id": snap.get("job_id"),
        "project_id": snap.get("project_id"),
        "encoding": CSV_ENCODING,
        "csv": reproduction_spec["csv"],
        "numeric_precision": {
            "coefficients": "typed numeric encoding (int/decimal/float64 ieee_hex); display formula is not used",
            "csv_numbers": "decimal text via format(.17g) / exact int; units live in companion .meta.json",
        },
        "reproduction": {
            "promised": reproduction_spec["promised"],
            "reason": reproduction_spec["reason"],
            "tolerance": reproduction_spec["tolerance"],
            "determinism": reproduction_spec["determinism"],
        },
        "integrity_status": "assembled_unverified",
        "completeness_status": "complete" if not completeness_doc["missing"] else "incomplete",
        "numerical_reproduction_status": "ready" if reproduction_spec["promised"] else "not_ready",
        "completeness_summary": completeness_doc["counts"],
        "completeness_missing": completeness_doc["missing"],
        "share_selection": share_doc,
        "files": files_meta_sorted,
        "notes": [
            "MANIFEST.json is not listed in files and has no self-hash (avoids circular hashing).",
            "The frozen snapshot was written before this artifact registry.",
            "A C08 PDF, when present, does not replace the complete used/excluded tables.",
            "Dataset contents are not attached to logs or remote telemetry by this module.",
        ],
    }
    # Manifest last, without hashing itself.
    write_json(resolve_inside(out, MANIFEST_NAME), manifest)
    return manifest


def refresh_evidence_bundle_archive(
    bundle_bytes: bytes,
    *,
    snapshot: Mapping[str, Any],
    report_pdf: bytes,
    report_docx: bytes,
    signature_record: Optional[Mapping[str, Any]] = None,
    signed_report_pdf: Optional[bytes] = None,
    documentary_files: Sequence[Mapping[str, Any]] = (),
) -> bytes:
    """Refresh document/review/signature evidence in an existing C12 archive.

    The worker is the only component that still has the parsed/raw tables and
    fitted encoder in memory, so post-review document operations must update
    its already-built dossier instead of reconstructing those facts.  Every
    replaced member is re-hashed in ``MANIFEST.json`` and the original tables,
    policies and reproduction inputs remain byte-identical.
    """
    if not bytes(report_pdf).startswith(b"%PDF"):
        raise ValueError("report_pdf is not a PDF")
    if signed_report_pdf is not None and signature_record is None:
        raise ValueError("signed_report_pdf requires signature_record")
    if signature_record is not None and signed_report_pdf is None:
        raise ValueError("signature_record requires signed_report_pdf")

    members: Dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as archive:
            if archive.testzip() is not None:
                raise ValueError("evidence bundle has a CRC error")
            for info in archive.infolist():
                name = info.filename.replace("\\", "/")
                if (
                    not name
                    or name.startswith("/")
                    or posixpath.normpath(name) != name
                    or name.startswith("../")
                    or "/../" in name
                    or info.is_dir()
                ):
                    raise ValueError(f"unsafe evidence bundle member: {info.filename!r}")
                members[name] = archive.read(info)
    except zipfile.BadZipFile as exc:
        raise ValueError("evidence bundle is not a ZIP archive") from exc

    if MANIFEST_NAME not in members:
        raise ValueError("evidence bundle MANIFEST.json missing")
    try:
        manifest = json.loads(members[MANIFEST_NAME].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("evidence bundle manifest is invalid") from exc
    if manifest.get("schema_version") != SCHEMA_VERSION_MP or not str(
        manifest.get("bundle_version") or ""
    ).startswith("C12/"):
        raise ValueError("unsupported evidence bundle schema")

    qctx = _as_mapping(_as_mapping(snapshot.get("provenance")).get("qualification_context"))
    review_events = list(qctx.get("review_events") or [])
    replacements: Dict[str, Tuple[bytes, str, str, str]] = {
        "snapshot/result_snapshot.json": (
            canonical_json(dict(snapshot)).encode("utf-8"),
            "application/json",
            str(snapshot.get("schema_version") or SCHEMA_VERSION_MP),
            "frozen_result_snapshot",
        ),
        "qualification/context.json": (
            canonical_json(qctx).encode("utf-8"),
            "application/json",
            str(qctx.get("schema_version") or "MP-QUAL/1"),
            "qualification_context",
        ),
        "review/history.json": (
            canonical_json({"events": review_events}).encode("utf-8"),
            "application/json",
            "MP-QUAL/1",
            "review_history",
        ),
        "artifacts/report.pdf": (
            bytes(report_pdf),
            "application/pdf",
            SCHEMA_VERSION_MP,
            "c08_report_pdf",
        ),
        "artifacts/report.docx": (
            bytes(report_docx),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            SCHEMA_VERSION_MP,
            "editable_report_same_snapshot",
        ),
    }
    if signature_record is not None and signed_report_pdf is not None:
        replacements.update(
            {
                "signature/verification.json": (
                    canonical_json(dict(signature_record)).encode("utf-8"),
                    "application/json",
                    str(signature_record.get("schema_version") or "MP-SIGN/1"),
                    "signature_record",
                ),
                "artifacts/signed_report.pdf": (
                    bytes(signed_report_pdf),
                    "application/pdf",
                    SCHEMA_VERSION_MP,
                    "signed_report_exact_bytes",
                ),
            }
        )
    else:
        members.pop("signature/verification.json", None)
        members.pop("artifacts/signed_report.pdf", None)

    # Attachments are accepted only when the document workflow has loaded the
    # exact bytes back from JobStore and their declared digest still matches.
    # Existing worker-owned input evidence remains untouched.
    attachment_paths: List[str] = []
    for index, raw_file in enumerate(documentary_files):
        item = _as_mapping(raw_file)
        data = item.get("bytes")
        if not isinstance(data, (bytes, bytearray)):
            continue
        payload = bytes(data)
        digest = hashlib.sha256(payload).hexdigest()
        declared_digest = str(item.get("sha256") or "")
        if declared_digest and declared_digest != digest:
            raise ValueError("documentary attachment hash mismatch")
        filename = sanitize_internal_name(
            str(item.get("filename") or f"document_{index + 1}.bin")
        )
        path = f"artifacts/documents/c06/{index + 1:03d}-{filename}"
        attachment_paths.append(path)
        replacements[path] = (
            payload,
            str(item.get("media_type") or item.get("type") or "application/octet-stream"),
            SCHEMA_VERSION_MP,
            "authorized_documentary_attachment",
        )

    listed = {
        str(item.get("path")): dict(item)
        for item in manifest.get("files") or []
        if isinstance(item, Mapping) and item.get("path")
    }
    # This namespace represents the current document, not accumulated history.
    # The workflow archives the previous complete bundle before publishing the
    # replacement. Rebuild managed attachments so withdrawn/superseded proofs
    # do not remain silently authorized in the current dossier.
    for path, entry in list(listed.items()):
        if entry.get("function") == "authorized_documentary_attachment":
            members.pop(path, None)
            listed.pop(path, None)
    for path, (data, media_type, version, function) in replacements.items():
        members[path] = data
        listed[path] = {
            "path": path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "type": media_type,
            "version": version,
            "function": function,
        }
    for path in ("signature/verification.json", "artifacts/signed_report.pdf"):
        if path not in members:
            listed.pop(path, None)

    ledger_path = "completeness/ledger.json"
    if ledger_path not in members:
        raise ValueError("evidence bundle completeness ledger missing")
    try:
        ledger = json.loads(members[ledger_path].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("evidence bundle completeness ledger is invalid") from exc
    by_component = {
        str(item.get("component")): dict(item)
        for item in ledger.get("items") or []
        if isinstance(item, Mapping) and item.get("component")
    }

    def mark(component: str, status: str, source: str, notes: str = "") -> None:
        row = by_component.get(component, {"component": component})
        row.update(
            {
                "status": status,
                "declared": True,
                "source": source,
                "notes": notes,
                "evidence": {},
            }
        )
        row.pop("absence_kind", None)
        by_component[component] = row

    mark("frozen_snapshot", COMPLETENESS_VERIFIED, "snapshot.schema_version")
    mark("qualification_context", COMPLETENESS_PRESENT, "snapshot.provenance.qualification_context")
    mark("report_artifact", COMPLETENESS_PRESENT, "artifacts.report_pdf")
    mark("docx_artifact", COMPLETENESS_PRESENT, "artifacts.report_docx")
    if review_events:
        mark("review_history", COMPLETENESS_PRESENT, "qualification.review_events")
    else:
        mark("review_history", COMPLETENESS_MISSING, "qualification.review_events")
    if signature_record is not None:
        mark("signature_record", COMPLETENESS_PRESENT, "signature/verification.json")
    else:
        mark("signature_record", COMPLETENESS_MISSING, "signature/verification.json")
    current_document_paths = attachment_paths + [
        path for path, entry in listed.items()
        if entry.get("function") == "documentary_file" and path in members
    ]
    if current_document_paths:
        mark(
            "photos_documents",
            COMPLETENESS_PRESENT,
            ",".join(current_document_paths),
            "Arquivos documentais autorizados e vinculados por SHA-256.",
        )
    else:
        mark("photos_documents", COMPLETENESS_MISSING, "documentary_files")
    ledger["items"] = sorted(by_component.values(), key=lambda item: str(item.get("component")))
    statuses = [item.get("status") for item in ledger["items"]]
    ledger["counts"] = {
        status: statuses.count(status)
        for status in (
            COMPLETENESS_DECLARED,
            COMPLETENESS_MISSING,
            COMPLETENESS_PRESENT,
            COMPLETENESS_VERIFIED,
        )
    }
    ledger["missing"] = [
        item.get("component")
        for item in ledger["items"]
        if item.get("status") == COMPLETENESS_MISSING
    ]
    ledger_bytes = canonical_json(ledger).encode("utf-8")
    members[ledger_path] = ledger_bytes
    old_ledger = listed.get(ledger_path, {})
    listed[ledger_path] = {
        "path": ledger_path,
        "sha256": hashlib.sha256(ledger_bytes).hexdigest(),
        "size": len(ledger_bytes),
        "type": old_ledger.get("type") or "application/json",
        "version": old_ledger.get("version") or BUNDLE_VERSION,
        "function": old_ledger.get("function") or "completeness_ledger",
    }

    manifest["files"] = sorted(listed.values(), key=lambda item: item["path"])
    manifest["snapshot_sha256"] = hashlib.sha256(
        members["snapshot/result_snapshot.json"]
    ).hexdigest()
    manifest["completeness_status"] = "complete" if not ledger["missing"] else "incomplete"
    manifest["completeness_missing"] = ledger["missing"]
    manifest["completeness_summary"] = ledger["counts"]
    members[MANIFEST_NAME] = canonical_json(manifest).encode("utf-8")

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, _ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, members[name])
    return out.getvalue()


def verify_bundle(bundle_dir: Union[str, Path]) -> Dict[str, Any]:
    """Verify on-disk integrity. Never executes package content."""
    root = Path(bundle_dir).resolve()
    errors: List[str] = []
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        return {"ok": False, "errors": [f"{MANIFEST_NAME} missing"], "files_checked": 0, "versions": {}}

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [f"manifest unreadable: {exc}"], "files_checked": 0, "versions": {}}

    if "sha256" in manifest or "manifest_sha256" in manifest or "self_hash" in manifest:
        errors.append("manifest includes a self-hash field (circular hashing is forbidden)")

    files = manifest.get("files") or []
    listed = {}
    for entry in files:
        rel = entry.get("path")
        try:
            path = resolve_inside(root, rel)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        listed[rel] = entry
        if not path.is_file():
            errors.append(f"missing listed file: {rel}")
            continue
        digest = sha256_file(path)
        size = path.stat().st_size
        if digest != entry.get("sha256"):
            errors.append(f"hash mismatch: {rel}")
        if int(entry.get("size", -1)) != size:
            errors.append(f"size mismatch: {rel}")
        for field in ("type", "version", "function"):
            if not entry.get(field):
                errors.append(f"missing {field} for {rel}")

    on_disk = []
    for path in iter_regular_files(root):
        rel = relative_posix(root, path)
        if rel == MANIFEST_NAME:
            continue
        if rel.endswith(".tmp"):
            errors.append(f"unexpected temp file: {rel}")
            continue
        on_disk.append(rel)
        if rel not in listed:
            errors.append(f"unexpected file not listed in manifest: {rel}")
        # Never execute anything we find.
        if rel.endswith((".py", ".pyc", ".pyo", ".so", ".exe", ".sh", ".bat", ".pkl", ".pickle")):
            errors.append(f"unexpected executable/serialized-code file: {rel}")

    versions = {
        "schema_version": manifest.get("schema_version"),
        "bundle_version": manifest.get("bundle_version"),
        "compatible": (
            manifest.get("schema_version") == SCHEMA_VERSION_MP
            and str(manifest.get("bundle_version") or "").startswith("C12/")
        ),
        "input_id": manifest.get("input_id"),
        "code_id": manifest.get("code_id"),
        "schema_id": manifest.get("schema_id"),
        "policy_id": manifest.get("policy_id"),
    }
    if not versions["compatible"]:
        errors.append(
            f"incompatible versions schema={manifest.get('schema_version')!r} bundle={manifest.get('bundle_version')!r}"
        )

    signature_path = root / "signature" / "verification.json"
    signed_pdf_path = root / "artifacts" / "signed_report.pdf"
    if signature_path.is_file() != signed_pdf_path.is_file():
        errors.append("signature record and signed_report.pdf must be supplied together")
    if signature_path.is_file() and signed_pdf_path.is_file():
        signature = _read_json(signature_path) or {}
        signed_pdf = signed_pdf_path.read_bytes()
        snapshot = _read_json(root / "snapshot" / "result_snapshot.json") or {}
        unsigned_path = root / "artifacts" / "report.pdf"
        if hashlib.sha256(signed_pdf).hexdigest() != signature.get("signed_pdf_sha256"):
            errors.append("signed PDF does not match signature record")
        if not unsigned_path.is_file():
            errors.append("unsigned report.pdf missing for signed revision binding")
        else:
            unsigned_pdf = unsigned_path.read_bytes()
            if hashlib.sha256(unsigned_pdf).hexdigest() != signature.get("unsigned_pdf_sha256"):
                errors.append("unsigned PDF does not match signature request")
            if not signed_pdf.startswith(unsigned_pdf):
                errors.append("signed PDF is not an incremental revision of report.pdf")
        snapshot_digest = signable_snapshot_sha256(snapshot)
        if snapshot_digest != signature.get("snapshot_sha256"):
            errors.append("signed snapshot digest does not match packaged snapshot")
        qctx = _as_mapping(_as_mapping(snapshot.get("provenance")).get("qualification_context"))
        if signature.get("result_fingerprint") != qctx.get("result_fingerprint"):
            errors.append("signed result fingerprint does not match qualification context")
        local = _as_mapping(signature.get("local_verification"))
        if not (
            signature.get("status") == "valid"
            and signature.get("backend") == "pyHanko"
            and signature.get("incremental_base_verified") is True
            and local.get("status") == "valid"
            and int(local.get("signature_count") or 0) > 0
        ):
            errors.append("signature record is not a locally verified pyHanko result")

    snapshot = _read_json(root / "snapshot" / "result_snapshot.json") or {}
    qualification_file = _read_json(root / "qualification" / "context.json")
    snapshot_qualification = _as_mapping(
        _as_mapping(snapshot.get("provenance")).get("qualification_context")
    )
    if qualification_file is not None and canonical_json(qualification_file) != canonical_json(
        snapshot_qualification
    ):
        errors.append("qualification/context.json contradicts the frozen snapshot")

    return {
        "ok": not errors,
        "integrity_status": "verified" if not errors else "failed",
        "completeness_status": manifest.get("completeness_status") or "unknown",
        "numerical_reproduction_status": manifest.get("numerical_reproduction_status") or "not_run",
        "errors": errors,
        "files_checked": len(listed),
        "versions": versions,
        "manifest_has_self_hash": "sha256" in manifest or "manifest_sha256" in manifest,
    }


def reproduce_from_bundle(bundle_dir: Union[str, Path]) -> Dict[str, Any]:
    """Reconstruct supported point/intervals from disk. Never uses in-memory models."""
    root = Path(bundle_dir).resolve()
    integrity = verify_bundle(root)
    limitations: List[str] = []
    if not integrity.get("ok"):
        return {
            "ok": False,
            "numerical_reproduction_status": "blocked_by_integrity",
            "integrity": integrity,
            "point": None,
            "mean_ci80": None,
            "prediction_interval": None,
            "arbitration_interval": None,
            "admissible_interval": None,
            "limitations": ["integrity_failed"] + list(integrity.get("errors") or []),
            "comparison": None,
            "promised": False,
        }

    spec = _read_json(root / "reproduction" / "spec.json") or {}
    promised = bool(spec.get("promised"))
    tolerance = dict(DEFAULT_TOLERANCE)
    tolerance.update(_as_mapping(spec.get("tolerance")))

    coef = _read_json(root / "model" / "coefficients.json")
    subject = _read_json(root / "model" / "subject_design.json")
    transforms = _read_json(root / "model" / "transformations.json") or {}
    residual = _read_json(root / "model" / "residual_context.json") or {}
    snapshot = _read_json(root / "snapshot" / "result_snapshot.json") or {}
    completeness = _read_json(root / "completeness" / "ledger.json") or {}
    value_policy = _read_json(root / "policies" / "value_policy.json") or {}

    if coef is None:
        limitations.append("model_coefficients faltante: no integral coefficients on disk")
    if subject is None:
        limitations.append("subject_design faltante: no packaged design row")
    y_state = _as_mapping(transforms.get("y_transformation"))
    y_name = y_state.get("name")
    if not y_name:
        limitations.append("y_transformation faltante: original-unit recovery is not confirmed")

    point = None
    point_transformed = None
    if coef is not None and subject is not None and y_name:
        try:
            point_transformed, point = _reconstruct_point(coef, subject, transforms)
        except Exception as exc:
            limitations.append(f"point reconstruction failed: {exc}")
            promised = False
    elif coef is not None and subject is not None and not y_name:
        # Do not silently assume identity.
        limitations.append("refusing to treat Xb as original-unit price without a declared y_transformation")
        promised = False

    mean_ci80 = None
    prediction_interval = None
    if residual and point_transformed is not None:
        try:
            mean_ci80, prediction_interval, interval_notes = _reconstruct_intervals(
                point_transformed, point, residual, y_name
            )
            limitations.extend(interval_notes)
        except Exception as exc:
            limitations.append(f"interval reconstruction unsupported: {exc}")
    else:
        if not residual:
            limitations.append("residual_context faltante: intervals not reconstructed")

    arbitration_interval, admissible_interval, adopted_value, policy_notes = (
        _reconstruct_value_policy(point, mean_ci80, prediction_interval, value_policy)
    )
    limitations.extend(policy_notes)

    snap_value = _as_mapping(snapshot.get("value"))
    comparison = _compare_to_snapshot(point, mean_ci80, prediction_interval, snap_value, tolerance)

    for field, reconstructed in (
        ("arbitration_interval", arbitration_interval),
        ("admissible_interval", admissible_interval),
    ):
        expected = _as_mapping(snap_value.get(field))
        if not expected:
            comparison[f"{field}_within_tolerance"] = None
            continue
        if not reconstructed:
            comparison[f"{field}_within_tolerance"] = False
            limitations.append(
                f"declared {field} was not reconstructed from an explicit value policy"
            )
            continue
        abs_t = float(tolerance["interval_abs"])
        rel_t = float(tolerance["interval_rel"])
        checks = []
        for bound in ("lower", "upper"):
            observed = number_as_float64(reconstructed[bound])
            declared = number_as_float64(expected[bound])
            checks.append(
                abs(observed - declared) <= abs_t + rel_t * max(abs(observed), abs(declared))
            )
        comparison[f"{field}_within_tolerance"] = all(checks)

    ok = bool(integrity.get("ok")) and point is not None and bool(comparison.get("point_within_tolerance"))
    policy_expected = any(
        snap_value.get(field) is not None
        for field in ("arbitration_interval", "admissible_interval")
    )
    policy_complete = all(
        snap_value.get(field) is None
        or comparison.get(f"{field}_within_tolerance") is True
        for field in ("arbitration_interval", "admissible_interval")
    )
    if value_policy and not policy_complete:
        ok = False
    if promised and point is None:
        ok = False
    if snap_value.get("point") is not None and point is None:
        # Never echo the memorized snapshot value as a reproduction.
        ok = False
        limitations.append("refused to return snapshot.value.point as reproduction without reconstructing it")

    if _interval_reconstruction_supported(residual, y_name):
        method = str(residual.get("interval_method") or residual.get("method") or "")
        if mean_ci80 is None:
            ok = False
            limitations.append(
                "declared supported intervals were not reconstructed in the original unit"
            )
        else:
            if not _interval_centered_on_original(mean_ci80, point, point_transformed, tolerance):
                ok = False
                limitations.append(
                    "reconstructed mean_ci80 is not in the original unit "
                    "(not centered on the original-unit point)"
                )
            if snap_value.get("mean_ci80") is not None and comparison.get("mean_ci80_within_tolerance") is not True:
                ok = False
                limitations.append("reconstructed mean_ci80 does not match the snapshot within tolerance")
        pred_supported = method in {
            "ols_prediction",
            "ols_prediction_interval",
            "prediction_interval",
            "ols_mean_and_prediction",
        }
        if pred_supported:
            if prediction_interval is None and snap_value.get("prediction_interval") is not None:
                ok = False
                limitations.append(
                    "declared supported prediction_interval was not reconstructed in the original unit"
                )
            elif prediction_interval is not None:
                if not _interval_centered_on_original(
                    prediction_interval, point, point_transformed, tolerance
                ):
                    ok = False
                    limitations.append(
                        "reconstructed prediction_interval is not in the original unit "
                        "(not centered on the original-unit point)"
                    )
                if (
                    snap_value.get("prediction_interval") is not None
                    and comparison.get("prediction_interval_within_tolerance") is not True
                ):
                    ok = False
                    limitations.append(
                        "reconstructed prediction_interval does not match the snapshot within tolerance"
                    )

    return {
        "ok": ok,
        "numerical_reproduction_status": (
            "verified"
            if ok and (not policy_expected or policy_complete)
            else ("partial" if ok else "failed")
        ),
        "integrity": integrity,
        "promised": promised,
        "point": point,
        "point_transformed": point_transformed,
        "mean_ci80": mean_ci80,
        "prediction_interval": prediction_interval,
        "arbitration_interval": arbitration_interval,
        "admissible_interval": admissible_interval,
        "adopted_value": adopted_value,
        "limitations": limitations,
        "tolerance": tolerance,
        "comparison": comparison,
        "versions": integrity.get("versions"),
        "completeness_missing": completeness.get("missing") or [],
        "determinism": spec.get("determinism"),
        "method": spec.get("method"),
    }


def assess_bundle_status(bundle_dir: Union[str, Path]) -> Dict[str, Any]:
    """Report integrity, completeness and numeric reproduction independently."""
    root = Path(bundle_dir).resolve()
    integrity = verify_bundle(root)
    ledger = _read_json(root / "completeness" / "ledger.json") or {}
    missing = list(ledger.get("missing") or [])
    completeness_status = "complete" if not missing else "incomplete"
    if integrity.get("ok"):
        reproduction = reproduce_from_bundle(root)
    else:
        reproduction = {
            "ok": False,
            "numerical_reproduction_status": "blocked_by_integrity",
            "limitations": list(integrity.get("errors") or []),
        }
    return {
        "integrity_status": integrity.get("integrity_status") or "failed",
        "completeness_status": completeness_status,
        "numerical_reproduction_status": reproduction.get("numerical_reproduction_status") or "failed",
        "integrity": integrity,
        "completeness": {"missing": missing, "counts": ledger.get("counts") or {}},
        "numerical_reproduction": reproduction,
    }


def export_share_copy(
    bundle_dir: Union[str, Path],
    dest_dir: Union[str, Path],
    include_functions: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Copy selected functions to dest_dir. Never deletes or rewrites the original."""
    root = Path(bundle_dir).resolve()
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    dest = dest.resolve()
    if dest == root:
        raise ValueError("share destination must be distinct from the original local package")
    manifest = _read_json(root / MANIFEST_NAME) or {}
    if include_functions is None:
        include_functions = _as_mapping(manifest.get("share_selection")).get("include_functions") or []
    wanted = set(include_functions)
    copied = []
    for entry in manifest.get("files") or []:
        if entry.get("function") not in wanted:
            continue
        rel = entry["path"]
        src = resolve_inside(root, rel)
        target = resolve_inside(dest, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(src.read_bytes())
        copied.append(rel)
    share_manifest = {
        "schema_version": SCHEMA_VERSION_MP,
        "bundle_version": BUNDLE_VERSION,
        "original_root_note": "original local package was not removed or rewritten",
        "include_functions": list(include_functions),
        "copied": copied,
    }
    write_json(dest / "SHARE_MANIFEST.json", share_manifest)
    # Confirm original still intact.
    original_ok = (root / MANIFEST_NAME).is_file()
    return {"copied": copied, "original_retained": original_ok, "destination": str(dest)}


# ---------------------------------------------------------------------------
# Frame / table helpers
# ---------------------------------------------------------------------------

def frame_to_rows(frame: Any) -> Tuple[Optional[List[str]], Optional[List[Dict[str, Any]]]]:
    if frame is None:
        return None, None
    if isinstance(frame, Mapping) and "columns" in frame and "rows" in frame:
        columns = [str(c) for c in frame["columns"]]
        rows: List[Dict[str, Any]] = []
        for raw in frame["rows"]:
            if isinstance(raw, Mapping):
                rows.append({c: _normalize_cell(raw.get(c)) for c in columns})
            else:
                rows.append({c: _normalize_cell(v) for c, v in zip(columns, list(raw))})
        return columns, rows
    if isinstance(frame, Mapping) and frame and all(isinstance(v, list) for v in frame.values()):
        columns = [str(c) for c in frame.keys()]
        n = len(next(iter(frame.values())))
        rows = [{c: _normalize_cell(frame[c][i]) for c in columns} for i in range(n)]
        return columns, rows
    if isinstance(frame, list):
        columns: List[str] = []
        seen = set()
        for rec in frame:
            if not isinstance(rec, Mapping):
                raise TypeError("list frames must contain mappings")
            for key in rec.keys():
                name = str(key)
                if name not in seen:
                    seen.add(name)
                    columns.append(name)
        rows = [{c: _normalize_cell(rec.get(c)) for c in columns} for rec in frame]
        return columns, rows
    if hasattr(frame, "columns") and hasattr(frame, "itertuples"):
        columns = [str(c) for c in list(frame.columns)]
        rows = []
        for tup in frame.itertuples(index=False):
            rows.append({c: _normalize_cell(v) for c, v in zip(columns, tup)})
        if "row_id" not in columns and hasattr(frame, "index"):
            columns = ["row_id"] + columns
            for rec, idx in zip(rows, frame.index):
                rec["row_id"] = _normalize_cell(idx)
        return columns, rows
    raise TypeError(f"unsupported frame type: {type(frame).__name__}")


def _normalize_cell(value: Any) -> Any:
    if value is None:
        return None
    try:
        if value != value:  # NaN
            return None
    except Exception:
        pass
    if isinstance(value, bytes):
        return value.decode("utf-8")
    # numpy / pandas scalars
    if hasattr(value, "item") and not isinstance(value, (bytes, str, dict, list)):
        try:
            value = value.item()
        except Exception:
            pass
    try:
        import datetime as _dt
        if isinstance(value, (_dt.date, _dt.datetime)):
            return value.isoformat()
    except Exception:
        pass
    return value


def write_csv_table(
    path: Path,
    columns: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    *,
    representation: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=CSV_ENCODING, newline="") as fh:
        writer = csv.writer(
            fh,
            delimiter=CSV_DELIMITER,
            quotechar=CSV_QUOTECHAR,
            quoting=csv.QUOTE_MINIMAL,
            lineterminator=CSV_LINETERMINATOR,
        )
        writer.writerow(list(columns))
        for rec in rows:
            line = []
            for col in columns:
                cell = rec.get(col)
                if cell is None:
                    text = ""
                elif isinstance(cell, (int, float)) and not isinstance(cell, bool):
                    text = number_to_cell_text(cell)
                else:
                    text = str(cell)
                if representation == "visualization_safe" and is_formula_cell(text):
                    text = neutralize_formula_cell(text)
                line.append(text)
            writer.writerow(line)


def _write_table_pair(
    root: Path,
    files_meta: List[Dict[str, Any]],
    ledger: CompletenessLedger,
    *,
    component: str,
    function: str,
    rel: str,
    viz_rel: str,
    columns: Optional[List[str]],
    rows: Optional[List[Dict[str, Any]]],
    roles: Mapping[str, Any],
    units: Mapping[str, Any],
    notes_if_missing: str,
    extra_meta: Optional[Mapping[str, Any]] = None,
    allow_empty: bool = False,
) -> None:
    if columns is None or rows is None or (len(rows) == 0 and not allow_empty):
        if allow_empty and columns is not None and rows is not None:
            pass
        else:
            ledger.set(component, COMPLETENESS_MISSING, notes=notes_if_missing)
            return
    write_csv_table(resolve_inside(root, rel), columns, rows, representation="raw")
    write_csv_table(resolve_inside(root, viz_rel), columns, rows, representation="visualization_safe")
    meta = {
        "encoding": CSV_ENCODING,
        "delimiter": CSV_DELIMITER,
        "quotechar": CSV_QUOTECHAR,
        "lineterminator": "LF",
        "n_rows": len(rows),
        "n_columns": len(columns),
        "columns": [
            {
                "name": c,
                "role": _role_for(c, roles),
                "unit": units.get(c),
            }
            for c in columns
        ],
        "representation_raw": rel,
        "representation_visualization_safe": viz_rel,
    }
    if extra_meta:
        meta.update(dict(extra_meta))
    meta_rel = rel + ".meta.json"
    write_json(resolve_inside(root, meta_rel), meta)
    _register(files_meta, root, rel, "text/csv", BUNDLE_VERSION, function)
    _register(files_meta, root, viz_rel, "text/csv", BUNDLE_VERSION, function + "_visualization_safe")
    _register(files_meta, root, meta_rel, "application/json", BUNDLE_VERSION, function + "_meta")
    ledger.set(
        component,
        COMPLETENESS_PRESENT,
        declared=True,
        source=rel,
        evidence={"n_rows": len(rows), "n_columns": len(columns)},
    )


def _write_declared_json(
    root: Path,
    files_meta: List[Dict[str, Any]],
    ledger: CompletenessLedger,
    component: str,
    rel: str,
    payload: Mapping[str, Any],
    function: str,
    present_notes: str,
) -> None:
    if not payload:
        ledger.set(component, COMPLETENESS_MISSING, notes=f"{component} was not declared; not invented.")
        return
    write_json(resolve_inside(root, rel), payload)
    _register(files_meta, root, rel, "application/json", SCHEMA_VERSION_MP, function)
    ledger.set(component, COMPLETENESS_PRESENT, declared=True, source=rel, notes=present_notes)


def _write_opaque_artifact(
    root: Path,
    files_meta: List[Dict[str, Any]],
    raw_name: Any,
    spec: Any,
    function: str = "opaque_artifact",
) -> None:
    name = _safe_artifact_filename(str(raw_name))
    rel = f"artifacts/{name}"
    data: Optional[bytes] = None
    version = SCHEMA_VERSION_MP
    mime = "application/octet-stream"
    if isinstance(spec, (bytes, bytearray)):
        data = bytes(spec)
    elif isinstance(spec, Mapping):
        if spec.get("path"):
            # Only read the caller's local path; still store under artifacts/safe name.
            src = Path(str(spec["path"]))
            if not src.is_file():
                return
            data = src.read_bytes()
        elif isinstance(spec.get("bytes"), (bytes, bytearray)):
            data = bytes(spec["bytes"])
        elif isinstance(spec.get("content"), (bytes, bytearray)):
            data = bytes(spec["content"])
        elif spec.get("json") is not None:
            data = canonical_json(spec["json"]).encode("utf-8")
            mime = "application/json"
        function = str(spec.get("function") or function)
        version = str(spec.get("version") or version)
        mime = str(spec.get("type") or mime)
        given = spec.get("filename")
        if given:
            name = _safe_artifact_filename(str(given))
            rel = f"artifacts/{name}"
    elif isinstance(spec, str):
        data = spec.encode("utf-8")
        mime = "text/plain; charset=utf-8"
    if data is None:
        return
    # Store pickle/opaque bytes if the caller handed them over, but never load.
    if looks_like_pickle(data):
        mime = "application/octet-stream"
        function = "opaque_untrusted_pickle_not_for_reproduction"
    write_bytes_atomic(resolve_inside(root, rel), data)
    _register(files_meta, root, rel, mime, version, function)


_EXECUTABLE_SUFFIXES = (
    ".py",
    ".pyc",
    ".pyo",
    ".so",
    ".exe",
    ".sh",
    ".bat",
    ".pkl",
    ".pickle",
    ".pyd",
    ".dll",
)


def _safe_artifact_filename(raw_name: str) -> str:
    name = sanitize_internal_name(str(raw_name))
    lower = name.lower()
    for ext in _EXECUTABLE_SUFFIXES:
        if lower.endswith(ext):
            name = name[: len(name) - len(ext)] + ".bin"
            lower = name.lower()
            break
    return name or "artifact.bin"


def _register(
    files_meta: List[Dict[str, Any]],
    root: Path,
    rel: str,
    type_: str,
    version: str,
    function: str,
) -> None:
    path = resolve_inside(root, rel)
    files_meta.append(
        {
            "path": rel.replace("\\", "/"),
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
            "type": type_,
            "version": str(version),
            "function": function,
        }
    )


# ---------------------------------------------------------------------------
# Domain extraction
# ---------------------------------------------------------------------------

def _as_mapping(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    # InputBundle predates the Mapping subclass used by PreparedDataset but
    # deliberately exposes a side-effect-free to_dict()/keys()/get protocol.
    # Reject arbitrary objects; accept only this explicit producer contract.
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    return {}


def _first_mapping(*candidates: Any) -> Dict[str, Any]:
    for cand in candidates:
        mapped = _as_mapping(cand)
        if mapped:
            return mapped
    return {}


def _sample_ids(
    snap: Mapping[str, Any],
    ib: Mapping[str, Any],
    prep: Mapping[str, Any],
) -> Tuple[List[str], List[str], Dict[str, Any]]:
    sample = _as_mapping(snap.get("sample"))
    used = sample.get("used_row_ids")
    excluded = sample.get("excluded_row_ids")
    if used is None:
        used = prep.get("row_ids") or prep.get("used_row_ids")
    if used is None:
        used = []
    if excluded is None:
        excluded = prep.get("excluded_row_ids") or []
    used_ids = [str(x) for x in list(used)]
    excluded_ids = [str(x) for x in list(excluded)]
    counts = {
        "received": sample.get("received"),
        "observed_target": sample.get("observed_target"),
        "prepared": sample.get("prepared"),
        "used": sample.get("used") if sample.get("used") is not None else len(used_ids),
        "excluded": sample.get("excluded") if sample.get("excluded") is not None else len(excluded_ids),
    }
    return used_ids, excluded_ids, counts


def _row_ledger(ib: Mapping[str, Any], prep: Mapping[str, Any]) -> List[Dict[str, Any]]:
    for key in ("sample_ledger", "row_ledger"):
        for src in (prep, ib):
            val = src.get(key)
            if isinstance(val, list):
                return [dict(x) if isinstance(x, Mapping) else {"row_id": x} for x in val]
            if isinstance(val, Mapping):
                items = []
                for rid, payload in val.items():
                    rec = dict(payload) if isinstance(payload, Mapping) else {"reason": payload}
                    rec.setdefault("row_id", rid)
                    items.append(rec)
                return items
    return []


def _select_rows_by_id(
    rows: Optional[List[Dict[str, Any]]],
    columns: Optional[List[str]],
    ids: Sequence[str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    if not rows or not ids:
        cols = list(columns or ["row_id"])
        if "row_id" not in cols:
            cols = ["row_id"] + cols
        # Still emit a row skeleton for declared ids when the base is missing? No: that would fabricate.
        return [], cols if columns else ["row_id"]
    cols = list(columns or [])
    if "row_id" not in cols:
        cols = ["row_id"] + cols
    index = {}
    for rec in rows:
        rid = rec.get("row_id")
        if rid is not None:
            index[str(rid)] = rec
    selected = []
    for rid in ids:
        rec = index.get(str(rid))
        if rec is None:
            continue
        selected.append({c: rec.get(c) for c in cols if c in rec or c == "row_id"})
        selected[-1]["row_id"] = str(rid)
    return selected, cols


def _attach_exclusion_reasons(
    rows: List[Dict[str, Any]],
    columns: List[str],
    excluded_ids: Sequence[str],
    ledger: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    by_id = {str(item.get("row_id")): item for item in ledger if item.get("row_id") is not None}
    cols = list(columns)
    for extra in ("row_id", "disposition", "exclusion_reasons"):
        if extra not in cols:
            cols.append(extra)
    index = {str(r.get("row_id")): r for r in rows}
    out_rows = []
    for rid in excluded_ids:
        rec = dict(index.get(str(rid)) or {"row_id": str(rid)})
        info = by_id.get(str(rid), {})
        rec["row_id"] = str(rid)
        rec["disposition"] = info.get("disposition") or rec.get("disposition") or "excluded"
        reasons = info.get("reasons") or info.get("reason") or rec.get("exclusion_reasons")
        if isinstance(reasons, list):
            rec["exclusion_reasons"] = " | ".join(str(x) for x in reasons)
        elif reasons is None:
            rec["exclusion_reasons"] = info.get("notes") or ""
        else:
            rec["exclusion_reasons"] = str(reasons)
        out_rows.append({c: rec.get(c) for c in cols})
    return out_rows, cols


def _identification_rows(
    ib: Mapping[str, Any],
    prep: Mapping[str, Any],
    request_spec: Mapping[str, Any],
    raw_cols: Optional[List[str]],
    raw_rows: Optional[List[Dict[str, Any]]],
    parsed_cols: Optional[List[str]],
    parsed_rows: Optional[List[Dict[str, Any]]],
) -> Tuple[Optional[List[str]], Optional[List[Dict[str, Any]]]]:
    roles = _as_mapping(request_spec.get("roles"))
    id_roles = {"identifier", "source", "date"}
    declared = [name for name, role in roles.items() if str(role).lower() in id_roles]
    # identification_df from legacy DataLoadResult, if adapted into the bundle.
    ident_frame = ib.get("identification_frame") or ib.get("identification_df")
    ident_cols, ident_rows = frame_to_rows(ident_frame) if ident_frame is not None else (None, None)
    source_cols = parsed_cols or raw_cols
    source_rows = parsed_rows or raw_rows
    if source_cols and source_rows:
        keep = []
        if "row_id" in source_cols:
            keep.append("row_id")
        for name in declared:
            if name in source_cols and name not in keep:
                keep.append(name)
        if ident_cols:
            for name in ident_cols:
                if name not in keep:
                    keep.append(name)
        if len(keep) <= 1 and ident_cols:
            keep = (["row_id"] if "row_id" in (ident_cols or []) or "row_id" in (source_cols or []) else []) + [
                c for c in ident_cols if c != "row_id"
            ]
        if keep:
            merged = []
            ident_index = {str(r.get("row_id")): r for r in (ident_rows or []) if r.get("row_id") is not None}
            for rec in source_rows:
                out = {}
                for c in keep:
                    if c in rec:
                        out[c] = rec.get(c)
                    elif ident_index:
                        alt = ident_index.get(str(rec.get("row_id")), {})
                        if c in alt:
                            out[c] = alt.get(c)
                if out:
                    merged.append(out)
            if ident_rows and not merged:
                return ident_cols, ident_rows
            return keep, merged
    if ident_cols and ident_rows:
        return ident_cols, ident_rows
    if declared and not (source_rows or ident_rows):
        return None, None
    return (declared or None), None


def _role_for(column: str, roles: Mapping[str, Any]) -> Optional[str]:
    if column in roles:
        return str(roles[column])
    if column == "row_id":
        return "identifier"
    return None


def _coefficients_source(snap: Mapping[str, Any], arts: Mapping[str, Any]) -> Mapping[str, Any]:
    for cand in (
        arts.get("coefficients"),
        _as_mapping(arts.get("candidate_fit")).get("coefficients"),
        _as_mapping(snap.get("model")).get("coefficients"),
        _as_mapping(snap.get("model")).get("coefficients_integral"),
    ):
        if isinstance(cand, Mapping) and cand:
            return cand
    return {}


def _integral_coefficients_payload(source: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    if not source:
        return None
    if "values" in source and "order" in source:
        order = [str(x) for x in source["order"]]
        values = {}
        raw_values = _as_mapping(source.get("values"))
        for name in order:
            values[name] = encode_number(raw_values.get(name))
        return {
            "encoding": "typed-numeric",
            "order": order,
            "values": values,
            "intercept": bool(source.get("intercept", "const" in order)),
        }
    # Mapping of name -> number (CandidateFit.coefficients).
    order = [str(k) for k in source.keys()]
    # Keep const first when present.
    if "const" in order:
        order = ["const"] + [k for k in order if k != "const"]
    values = {name: encode_number(source[name]) for name in order}
    return {
        "encoding": "typed-numeric",
        "order": order,
        "values": values,
        "intercept": "const" in order,
    }


def _transformations_payload(
    snap: Mapping[str, Any],
    arts: Mapping[str, Any],
    request_spec: Mapping[str, Any],
) -> Dict[str, Any]:
    model = _as_mapping(snap.get("model"))
    cand = _as_mapping(arts.get("candidate_spec") or arts.get("candidate_fit"))
    spec = _as_mapping(cand.get("candidate_spec")) if cand.get("candidate_spec") else cand
    x_tr = (
        spec.get("x_transformations")
        or model.get("x_transformations")
        or arts.get("x_transformations")
        or model.get("transformations")
        or {}
    )
    y_tr = spec.get("y_transformation") or model.get("y_transformation") or arts.get("y_transformation")
    if isinstance(y_tr, str):
        y_tr = {"name": y_tr}
    y_tr = _as_mapping(y_tr)
    if not y_tr and model.get("transformations") is None and not x_tr:
        return {}
    if not y_tr.get("name"):
        # Explicit linear is allowed only when declared. If the caller packed
        # x transforms but omitted y, leave name empty so reproduction refuses
        # to assume identity.
        pass
    return {
        "x_transformations": dict(x_tr) if isinstance(x_tr, Mapping) else {},
        "y_transformation": y_tr,
        "target_unit": (_as_mapping(snap.get("target")).get("unit") or request_spec.get("target_unit")),
        "estimand": _as_mapping(snap.get("target")).get("estimand"),
    }


def _subject_design_payload(
    snap: Mapping[str, Any],
    arts: Mapping[str, Any],
    transformations: Mapping[str, Any],
) -> Dict[str, Any]:
    for cand in (
        arts.get("subject_design"),
        arts.get("subject"),
        snap.get("subject_design"),
        snap.get("subject"),
        _as_mapping(snap.get("model")).get("subject_design"),
    ):
        mapped = _as_mapping(cand)
        if mapped:
            x_row = mapped.get("X") or mapped.get("x") or mapped.get("design_row")
            raw = mapped.get("raw_values") or mapped.get("subject_raw") or mapped.get("raw")
            if isinstance(x_row, Mapping) or isinstance(raw, Mapping):
                return {
                    "X": dict(x_row) if isinstance(x_row, Mapping) else {},
                    "raw_values": dict(raw) if isinstance(raw, Mapping) else {},
                    "supported": mapped.get("supported"),
                }
    raw = arts.get("subject_raw") or snap.get("subject_raw")
    raw = _as_mapping(raw)
    if raw:
        x_row = {}
        x_tr = _as_mapping(transformations.get("x_transformations"))
        for name, value in raw.items():
            tr_name = x_tr.get(name) or "linear"
            if isinstance(tr_name, Mapping):
                tr_name = tr_name.get("name") or "linear"
            x_row[str(name)] = value
            x_row_key = _transformed_column_name(str(tr_name), str(name))
            if x_row_key != name:
                x_row[x_row_key] = value  # transform applied at reconstruction time
        return {"X": {}, "raw_values": raw, "supported": True}
    return {}


def _transformed_column_name(transform: str, base: str) -> str:
    if transform in {None, "", "linear", "identity", "none"}:
        return base
    return f"{transform}({base})"


def _encoder_looks_executable(state: Mapping[str, Any]) -> bool:
    dumped = json.dumps(state, default=str)
    lowered = dumped.lower()
    if "pickle" in lowered or "__reduce__" in lowered:
        return True
    if "lambda" in lowered and "code" in lowered:
        return True
    if state.get("executable") or state.get("python_code") or state.get("bytecode"):
        return True
    return False


# ---------------------------------------------------------------------------
# Reconstruction (disk only, closed whitelist)
# ---------------------------------------------------------------------------

def _reconstruct_point(
    coef: Mapping[str, Any],
    subject: Mapping[str, Any],
    transforms: Mapping[str, Any],
) -> Tuple[float, float]:
    order = [str(x) for x in (coef.get("order") or [])]
    values = _as_mapping(coef.get("values"))
    if not order:
        raise ValueError("coefficient order is empty")
    x_row = _design_row(order, subject, transforms)
    total = 0.0
    for name in order:
        if name not in values:
            raise ValueError(f"missing coefficient {name}")
        coef_v = number_as_float64(values[name])
        xv = number_as_float64(x_row[name])
        total += coef_v * xv
    y_name = _as_mapping(transforms.get("y_transformation")).get("name")
    original = apply_inverse_y(total, y_name)
    return total, original


def _design_row(
    order: Sequence[str],
    subject: Mapping[str, Any],
    transforms: Mapping[str, Any],
) -> Dict[str, float]:
    provided = _as_mapping(subject.get("X"))
    raw = _as_mapping(subject.get("raw_values"))
    x_tr = _as_mapping(transforms.get("x_transformations"))
    row: Dict[str, float] = {}
    for name in order:
        if name == "const":
            row[name] = 1.0
            continue
        if name in provided and provided[name] is not None:
            row[name] = number_as_float64(provided[name])
            continue
        base, transform = _split_transformed_name(name)
        declared = x_tr.get(base) or x_tr.get(name) or transform
        if isinstance(declared, Mapping):
            declared = declared.get("name") or transform
        declared = str(declared or "linear")
        if base not in raw and name not in raw:
            raise ValueError(f"subject design missing {name}")
        raw_v = raw.get(base) if base in raw else raw.get(name)
        row[name] = apply_x_transform(number_as_float64(raw_v), declared)
    return row


def _split_transformed_name(name: str) -> Tuple[str, str]:
    if "(" in name and name.endswith(")"):
        func = name[: name.index("(")]
        base = name[name.index("(") + 1 : -1]
        return base, func
    return name, "linear"


def apply_x_transform(value: float, name: str) -> float:
    key = str(name or "linear").lower()
    if key not in X_TRANSFORM_WHITELIST:
        refuse_code_execution(f"x transform {name!r} is not on the closed whitelist")
    if key in {"linear", "identity", "none"}:
        return float(value)
    if key in {"ln", "log"}:
        if value <= 0:
            raise ValueError("ln/log requires value > 0")
        return math.log(value)
    if key == "log10":
        if value <= 0:
            raise ValueError("log10 requires value > 0")
        return math.log10(value)
    if key == "sqrt":
        if value < 0:
            raise ValueError("sqrt requires value >= 0")
        return math.sqrt(value)
    if key in {"sqr", "square"}:
        return float(value) * float(value)
    if key in {"inverse", "inv"}:
        if value == 0:
            raise ValueError("inverse requires value != 0")
        return 1.0 / float(value)
    if key == "inv_sqr":
        if value == 0:
            raise ValueError("inv_sqr requires value != 0")
        return 1.0 / (float(value) ** 2)
    if key == "inv_sqrt":
        if value <= 0:
            raise ValueError("inv_sqrt requires value > 0")
        return 1.0 / math.sqrt(value)
    refuse_code_execution(f"x transform {name!r} is not implemented")
    raise AssertionError("unreachable")


def apply_inverse_y(value: float, name: Any) -> float:
    key = str(name or "").lower()
    if key not in Y_INVERSE_WHITELIST:
        refuse_code_execution(f"y inverse {name!r} is not on the closed whitelist")
    if key in {"linear", "identity", "none"}:
        return float(value)
    if key in {"ln", "log"}:
        return math.exp(value)
    if key == "log10":
        return 10.0 ** float(value)
    if key == "sqrt":
        return float(value) ** 2
    if key in {"sqr", "square"}:
        if value < 0:
            raise ValueError("inverse of sqr requires value >= 0")
        return math.sqrt(value)
    if key in {"inverse", "inv"}:
        if value == 0:
            raise ValueError("inverse y requires value != 0")
        return 1.0 / float(value)
    refuse_code_execution(f"y inverse {name!r} is not implemented")
    raise AssertionError("unreachable")


def _residual_context_for_reproduction(residual_state: Mapping[str, Any]) -> Dict[str, Any]:
    """Map MP-PRO residual_state onto the C12 residual_context field names."""
    state = _as_mapping(residual_state)
    if not state:
        return {}
    if state.get("interval_method") and (
        state.get("std_error")
        or state.get("residual_std_error")
        or state.get("residual_std")
        or state.get("t_crit")
        or state.get("t_crit_80")
    ):
        mapped = dict(state)
        if mapped.get("std_error") is None:
            mapped["std_error"] = state.get("residual_std") or state.get("residual_std_error")
        if mapped.get("t_crit") is None:
            mapped["t_crit"] = state.get("t_crit_80")
        if mapped.get("subject_x") is None:
            mapped["subject_x"] = state.get("x0")
        return mapped
    std = state.get("residual_std") or state.get("std_error") or state.get("residual_std_error")
    t_crit = state.get("t_crit_80") or state.get("t_crit")
    xtx = state.get("xtx_inv")
    if std is None and xtx is None:
        return {}
    out = {
        "interval_method": state.get("interval_method") or "ols_mean_and_prediction",
        "interval_scale": state.get("interval_scale") or "transformed",
        "std_error": std,
        "residual_std_error": std,
        "t_crit": t_crit,
        "subject_x": state.get("subject_x") or state.get("x0"),
        "xtx_inv": xtx,
        "xtx_inv_kind": state.get("xtx_inv_kind"),
        "scale_convention": state.get("scale_convention"),
        "df_resid": state.get("df_resid"),
        "feature_order": state.get("feature_order"),
        "schema_version": state.get("schema_version"),
        "status": state.get("status"),
        "limitations": list(state.get("limitations") or []),
    }
    return {k: v for k, v in out.items() if v is not None}


def _reconstruct_intervals(
    point_transformed: float,
    point_original: float,
    residual: Mapping[str, Any],
    y_name: str,
) -> Tuple[Optional[Dict[str, float]], Optional[Dict[str, float]], List[str]]:
    notes: List[str] = []
    method = residual.get("interval_method") or residual.get("method")
    scale = str(residual.get("interval_scale") or "transformed")
    if not method:
        notes.append("interval_method not declared; intervals not reconstructed")
        return None, None, notes
    t_crit = residual.get("t_crit")
    std_error = residual.get("std_error") or residual.get("residual_std_error")
    if t_crit is None or std_error is None:
        notes.append("t_crit or std_error missing; intervals not reconstructed")
        return None, None, notes
    t_crit_f = number_as_float64(t_crit)
    se = number_as_float64(std_error)
    x0 = residual.get("subject_x") or residual.get("x0")
    xtx_inv = residual.get("xtx_inv")
    leverage = residual.get("leverage")
    if leverage is None:
        if x0 is None or xtx_inv is None:
            notes.append("leverage/xtx_inv/subject_x missing; intervals not reconstructed")
            return None, None, notes
        leverage = _quadratic_form(x0, xtx_inv)
    lev = number_as_float64(leverage)
    se_mean = se * math.sqrt(max(lev, 0.0))
    se_pred = se * math.sqrt(max(1.0 + lev, 0.0))

    def band(center: float, half: float) -> Dict[str, float]:
        return {"lower": center - half, "upper": center + half}

    y_key = str(y_name or "linear").lower()
    y_identity = y_key in {"linear", "identity", "none"}
    if scale == "original":
        if point_original is None:
            notes.append("original-unit point missing; cannot center original-scale intervals")
            return None, None, notes
        # residual std_error is declared on the original unit; do not band around Xb.
        center = float(point_original)
        notes.append(
            "intervals reconstructed on interval_scale=original, centered on the original-unit point"
        )
    elif y_identity:
        center = float(point_transformed)
    else:
        notes.append(
            f"interval_scale={scale!r} with y_transformation={y_name!r}: "
            "naive inversion of interval bounds is not a validated method; "
            "intervals left unrecovered rather than presented as normative IC."
        )
        return None, None, notes

    mean_ci = band(center, t_crit_f * se_mean)
    pred = band(center, t_crit_f * se_pred)

    supported_mean = method in {"ols_mean_ci", "ols_mean", "mean_ci80"}
    supported_pred = method in {"ols_prediction", "ols_prediction_interval", "prediction_interval", "ols_mean_and_prediction"}
    if method == "ols_mean_and_prediction":
        supported_mean = True
        supported_pred = True
    out_mean = mean_ci if supported_mean or method.startswith("ols") else None
    out_pred = pred if supported_pred else None
    if out_mean is None and out_pred is None:
        notes.append(f"interval_method {method!r} is not a supported reconstructed method")
    return out_mean, out_pred, notes


def _quadratic_form(x0: Any, xtx_inv: Any) -> float:
    vec = [number_as_float64(v) for v in list(x0)]
    mat = [[number_as_float64(c) for c in row] for row in list(xtx_inv)]
    n = len(vec)
    if any(len(row) != n for row in mat) or len(mat) != n:
        raise ValueError("xtx_inv shape does not match subject_x")
    tmp = [sum(mat[i][j] * vec[j] for j in range(n)) for i in range(n)]
    return sum(vec[i] * tmp[i] for i in range(n))


def _interval_reconstruction_supported(residual: Mapping[str, Any], y_name: Any) -> bool:
    """True when residual_context declares a reconstructable original-unit interval."""
    if not residual:
        return False
    method = residual.get("interval_method") or residual.get("method")
    if not method:
        return False
    scale = str(residual.get("interval_scale") or "transformed")
    y_key = str(y_name or "").lower()
    if scale == "original":
        return True
    return y_key in {"linear", "identity", "none"}


def _interval_centered_on_original(
    interval: Mapping[str, Any],
    point_original: Optional[float],
    point_transformed: Optional[float],
    tolerance: Mapping[str, float],
) -> bool:
    if not interval or point_original is None:
        return False
    try:
        lo = number_as_float64(interval.get("lower"))
        hi = number_as_float64(interval.get("upper"))
    except (TypeError, ValueError):
        return False
    mid = 0.5 * (lo + hi)
    abs_t = float(tolerance.get("interval_abs", 1e-6))
    rel_t = float(tolerance.get("interval_rel", 1e-8))
    if abs(mid - point_original) > abs_t + rel_t * max(abs(mid), abs(point_original)):
        return False
    if point_transformed is None:
        return True
    separated = abs(point_original - point_transformed) > abs_t + rel_t * max(
        abs(point_original), abs(point_transformed)
    )
    if separated and abs(mid - point_transformed) < abs(mid - point_original):
        return False
    return True


def _compare_to_snapshot(
    point: Optional[float],
    mean_ci80: Optional[Mapping[str, float]],
    prediction_interval: Optional[Mapping[str, float]],
    snap_value: Mapping[str, Any],
    tolerance: Mapping[str, float],
) -> Dict[str, Any]:
    def close(a: Optional[float], b: Any, abs_t: float, rel_t: float) -> Optional[bool]:
        if a is None or b is None:
            return None
        bf = number_as_float64(b)
        return abs(a - bf) <= abs_t + rel_t * max(abs(a), abs(bf))

    snap_point = snap_value.get("point")
    point_ok = close(point, snap_point, float(tolerance["point_abs"]), float(tolerance["point_rel"]))
    result: Dict[str, Any] = {
        "snapshot_point": snap_point,
        "point_delta": (None if point is None or snap_point is None else abs(point - number_as_float64(snap_point))),
        "point_within_tolerance": point_ok,
    }
    snap_ci = snap_value.get("mean_ci80")
    if mean_ci80 and isinstance(snap_ci, Mapping):
        lo_ok = close(mean_ci80.get("lower"), snap_ci.get("lower"), float(tolerance["interval_abs"]), float(tolerance["interval_rel"]))
        hi_ok = close(mean_ci80.get("upper"), snap_ci.get("upper"), float(tolerance["interval_abs"]), float(tolerance["interval_rel"]))
        result["mean_ci80_within_tolerance"] = bool(lo_ok and hi_ok)
    else:
        result["mean_ci80_within_tolerance"] = None
    snap_pi = snap_value.get("prediction_interval")
    if prediction_interval and isinstance(snap_pi, Mapping):
        lo_ok = close(prediction_interval.get("lower"), snap_pi.get("lower"), float(tolerance["interval_abs"]), float(tolerance["interval_rel"]))
        hi_ok = close(prediction_interval.get("upper"), snap_pi.get("upper"), float(tolerance["interval_abs"]), float(tolerance["interval_rel"]))
        result["prediction_interval_within_tolerance"] = bool(lo_ok and hi_ok)
    else:
        result["prediction_interval_within_tolerance"] = None
    return result


def _reconstruct_value_policy(
    point: Optional[float],
    mean_ci80: Optional[Mapping[str, float]],
    prediction_interval: Optional[Mapping[str, float]],
    policy: Mapping[str, Any],
) -> Tuple[Optional[Dict[str, float]], Optional[Dict[str, float]], Optional[float], List[str]]:
    """Apply only explicitly declared, whitelisted post-calculation policies."""
    notes: List[str] = []
    if point is None or not policy:
        return None, None, None, notes
    arbitration = None
    arbitration_rule = _as_mapping(policy.get("arbitration"))
    method = str(arbitration_rule.get("method") or "").lower()
    if method == "percent_around_point":
        try:
            percent = number_as_float64(arbitration_rule.get("percent"))
            if percent < 0 or percent > 100:
                raise ValueError("percent out of range")
            delta = point * percent / 100.0
            arbitration = {"lower": point - delta, "upper": point + delta}
        except (TypeError, ValueError) as exc:
            notes.append(f"arbitration policy invalid: {exc}")
    elif method:
        notes.append(f"arbitration policy unsupported: {method}")

    admissible = None
    admissible_rule = _as_mapping(policy.get("admissible"))
    admissible_method = str(admissible_rule.get("method") or "").lower()
    if admissible_method == "intersection":
        names = list(admissible_rule.get("inputs") or [])
        available = {
            "mean_ci80": mean_ci80,
            "prediction_interval": prediction_interval,
            "arbitration_interval": arbitration,
        }
        selected = [available.get(str(name)) for name in names]
        if selected and all(isinstance(item, Mapping) for item in selected):
            lower = max(number_as_float64(item.get("lower")) for item in selected if item)
            upper = min(number_as_float64(item.get("upper")) for item in selected if item)
            if lower <= upper:
                admissible = {"lower": lower, "upper": upper}
            else:
                notes.append("admissible policy intersection is empty")
        else:
            notes.append("admissible policy inputs are missing")
    elif admissible_method:
        notes.append(f"admissible policy unsupported: {admissible_method}")

    adopted = None
    adopted_rule = _as_mapping(policy.get("adopted"))
    adopted_method = str(adopted_rule.get("method") or "").lower()
    if adopted_method == "point":
        adopted = point
    elif adopted_method == "explicit":
        try:
            adopted = number_as_float64(adopted_rule.get("value"))
        except (TypeError, ValueError) as exc:
            notes.append(f"adopted value policy invalid: {exc}")
    elif adopted_method:
        notes.append(f"adopted value policy unsupported: {adopted_method}")
    return arbitration, admissible, adopted, notes


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# Silence unused import warning for log helper (exported for callers / tests).
__all__ = [
    "build_evidence_bundle",
    "verify_bundle",
    "reproduce_from_bundle",
    "assess_bundle_status",
    "export_share_copy",
    "apply_x_transform",
    "apply_inverse_y",
    "frame_to_rows",
    "write_csv_table",
    "DEFAULT_TOLERANCE",
    "strip_dataset_from_log_payload",
]
