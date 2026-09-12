"""C06 commercial mutation detectors on surfaces the product really emits.

The data and identities below are explicitly synthetic TEST fixtures.  A
passing test is evidence of a software guard, not professional review,
institutional acceptance, certification or a licence conclusion.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import zipfile

import pytest

from backend.worker import compose_valuation_job, resolve_peers
from frontend.components.professional import present_independent_validation_coverage
from modules.job_store import JobStore
from modules.qualification_profile import resolve_profile
from modules.qualification_profile.assessment import normalize_institution_receipt
from modules.report_export.submission import (
    build_submission_package,
    verify_submission_package,
)
from modules.report_export.workflow import generate_documents
from modules.report_presenter.verifier import verify_report_consistency
from modules.valuation_policy.qualification import reassess_qualification_context
from scripts.comercial.operacao import sbom
from tests.c17_integration.helpers import analytic_linear_csv
from tests.comercial.test_c06_document_flow import (
    _attach_test_document,
    _professional_spec,
)
from tests.comercial.test_c06_recipient_return import _case, _store_return
from tests.pro_workflow.p04.test_mutations_commercial import (
    CANDIDATE_SHA,
    _clean_run_payload,
    _write_artifacts_dir,
)


@pytest.fixture(scope="module")
def emitted_product(tmp_path_factory):
    """One real worker -> document emission, shared by read-only mutations."""
    root = tmp_path_factory.mktemp("c06-commercial-surfaces")
    store = JobStore(root / "store", recover_abandoned=False)
    spec = _professional_spec()
    job = store.create(request_spec=spec, payload={"filename": "SYNTHETIC_TEST.csv"})
    compose_valuation_job(
        job_id=job["job_id"],
        file_bytes=analytic_linear_csv(n=30, tag="C06SURFACE"),
        filename="SYNTHETIC_TEST.csv",
        request_spec=spec,
        subject_raw={"area": 73.5, "bairro": "Centro"},
        project_id=None,
        peers=resolve_peers(),
        job_store=store,
    )
    _attach_test_document(store, job["job_id"])
    generated = generate_documents(store, job["job_id"])
    assert generated["case_release_status"] == "review_required"
    snapshot = store.get_snapshot(job["job_id"])
    context = json.loads(store.get_artifact(job["job_id"], "report_context.json"))
    pdf = store.get_artifact(job["job_id"], "report.pdf")
    docx = store.get_artifact(job["job_id"], "report.docx")
    dossier = store.get_artifact(job["job_id"], "evidence_bundle.zip")
    normative = json.loads(store.get_artifact(job["job_id"], "normative_assessment.json"))
    output_manifest = json.loads(store.get_artifact(job["job_id"], "output_manifest.json"))
    assert verify_report_consistency(pdf, snapshot, context)["ok"] is True
    package = build_submission_package(
        snapshot,
        context,
        pdf_bytes=pdf,
        dossier_bytes=dossier,
    )
    assert verify_submission_package(package)["ok"] is True
    return {
        "snapshot": snapshot,
        "context": context,
        "pdf": pdf,
        "docx": docx,
        "dossier": dossier,
        "package": package,
        "spec": spec,
        "normative": normative,
        "output_manifest": output_manifest,
    }


def _finding_codes(product, snapshot):
    result = verify_report_consistency(
        product["pdf"], snapshot, product["context"]
    )
    return {item["code"] for item in result["findings"]}


def _replace_nested_dossier_with_missing_member(package: bytes) -> bytes:
    """Remove a listed dossier member while keeping the outer hashes coherent."""
    with zipfile.ZipFile(io.BytesIO(package)) as source:
        outer = {name: source.read(name) for name in source.namelist()}
    dossier_name = "evidence/dossier.zip"
    with zipfile.ZipFile(io.BytesIO(outer[dossier_name])) as source:
        inner = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(inner["MANIFEST.json"])
    victim = next(
        item["path"]
        for item in manifest["files"]
        if item["path"].startswith("artifacts/documents/")
    )
    del inner[victim]
    changed_dossier = io.BytesIO()
    with zipfile.ZipFile(changed_dossier, "w", zipfile.ZIP_DEFLATED) as target:
        for name, data in sorted(inner.items()):
            target.writestr(name, data)
    dossier_bytes = changed_dossier.getvalue()
    outer[dossier_name] = dossier_bytes
    outer_manifest = json.loads(outer["SUBMISSION_MANIFEST.json"])
    outer_manifest["files"][dossier_name]["sha256"] = hashlib.sha256(
        dossier_bytes
    ).hexdigest()
    outer_manifest["files"][dossier_name]["size"] = len(dossier_bytes)
    outer["SUBMISSION_MANIFEST.json"] = json.dumps(
        outer_manifest, sort_keys=True, separators=(",", ":")
    ).encode()
    changed = io.BytesIO()
    with zipfile.ZipFile(changed, "w", zipfile.ZIP_DEFLATED) as target:
        for name, data in sorted(outer.items()):
            target.writestr(name, data)
    return changed.getvalue()


def test_01_acceptance_aggregator_refuses_a_lost_nonzero_exit(tmp_path):
    """Tooling guard: a job status cannot launder the recorded test exit."""
    from c15_local.aggregate_required import verify_artifacts

    clean = _write_artifacts_dir(
        tmp_path / "clean", run_payload=_clean_run_payload()
    )
    assert verify_artifacts(clean, expected_sha=CANDIDATE_SHA, min_wide_tests=40) == []
    failed = _clean_run_payload(exit_code=1)
    mutated = _write_artifacts_dir(tmp_path / "mutated", run_payload=failed)
    findings = verify_artifacts(mutated, expected_sha=CANDIDATE_SHA, min_wide_tests=40)
    assert any("exit_code" in finding for finding in findings)


def test_02_emitted_report_refuses_empty_value_presented_as_finished(emitted_product):
    assert _finding_codes(emitted_product, emitted_product["snapshot"]) == set()
    mutated = copy.deepcopy(emitted_product["snapshot"])
    mutated["value"]["point"] = None
    assert "MUTATED_VALUE" in _finding_codes(emitted_product, mutated)


def test_03_method_none_surface_never_presents_training_metrics_as_external(emitted_product):
    """Presentation guard only; arbitrary out-of-band claims remain audit-only."""
    spec = copy.deepcopy(emitted_product["spec"])
    spec["evaluation_policy"] = {"method": "none"}
    snapshot = copy.deepcopy(emitted_product["snapshot"])
    snapshot.setdefault("model", {}).setdefault("diagnostics", {})["r2"] = 0.999999
    snapshot.setdefault("validation", {})["statistical"] = {}
    clean = present_independent_validation_coverage(snapshot, spec)
    assert clean["external_available"] is False
    assert clean["presented_train_as_external"] is False
    assert clean["label"] == "Validação independente não executada"
    # Deliberately attractive train metrics are the mutation.  They remain
    # visible as train metrics and cannot change the independent label.
    snapshot["model"]["diagnostics"].update({"rmse_train": 0.000001, "adj_r2": 0.99999})
    guarded = present_independent_validation_coverage(snapshot, spec)
    assert guarded["external_available"] is False
    assert guarded["presented_train_as_external"] is False
    assert guarded["train_metrics"]["rmse_train"] == 0.000001


def test_04_emitted_report_refuses_tampered_coefficient(emitted_product):
    assert _finding_codes(emitted_product, emitted_product["snapshot"]) == set()
    mutated = copy.deepcopy(emitted_product["snapshot"])
    name = next(key for key in mutated["model"]["coefficients"] if key != "const")
    mutated["model"]["coefficients"][name] *= 1.15
    assert "INCOHERENT_EQUATION" in _finding_codes(emitted_product, mutated)


def test_05_emitted_report_refuses_tampered_interval(emitted_product):
    assert _finding_codes(emitted_product, emitted_product["snapshot"]) == set()
    mutated = copy.deepcopy(emitted_product["snapshot"])
    interval = mutated["value"]["mean_ci80"]
    # The analytic fixture may produce a zero-width interval.  Move one bound
    # by a material fixed amount so this mutation is red-capable either way.
    interval["lower"] = float(interval["lower"]) - 12_345.0
    assert "MUTATED_INTERVAL" in _finding_codes(emitted_product, mutated)


def test_06_submission_refuses_missing_integral_attachment(emitted_product):
    assert verify_submission_package(emitted_product["package"])["ok"] is True
    mutated = _replace_nested_dossier_with_missing_member(emitted_product["package"])
    findings = verify_submission_package(mutated)
    assert findings["ok"] is False
    assert "DOSSIER_FILE_MISSING" in {item["code"] for item in findings["findings"]}


def test_07_emitted_report_binds_resolved_profile(emitted_product):
    assert _finding_codes(emitted_product, emitted_product["snapshot"]) == set()
    mutated = copy.deepcopy(emitted_product["snapshot"])
    profile = mutated["provenance"]["qualification_context"]["profile"]
    profile["version"] = "TESTE-VERSAO-ADULTERADA"
    assert "MUTATED_PROFILE" in _finding_codes(emitted_product, mutated)


def test_08_emitted_report_refuses_unverified_rule_laundered_as_release(emitted_product):
    assert _finding_codes(emitted_product, emitted_product["snapshot"]) == set()
    normative = copy.deepcopy(emitted_product["normative"])
    item6 = next(
        item for item in normative["fundamentacao"]["items"]
        if item["id"] == "tabela1.item6"
    )
    item6["grade"] = 0
    item6["detail"] = "TESTE: violação deliberada da regra decisiva"
    current = emitted_product["snapshot"]["provenance"]["qualification_context"]
    reassessed = reassess_qualification_context(
        snapshot=emitted_product["snapshot"],
        request_spec=emitted_product["spec"],
        output_manifest=emitted_product["output_manifest"],
        report_content_fingerprint=current["report_content_fingerprint"],
        review_events=current["review_events"],
        normative_assessment=normative,
    )
    assert reassessed["case_release_status"] == "analysis_only"
    assert "decisive_rule_not_satisfied" in {
        item["code"] for item in reassessed["release_blockers"]
    }

    mutated = copy.deepcopy(emitted_product["snapshot"])
    qctx = mutated["provenance"]["qualification_context"]
    rule = next(item for item in qctx["rule_results"] if item["rule_id"] == "tabela1.item6")
    rule["status"] = "pending_manual"
    # Preserve the old release classification: this is exactly the attempted
    # laundering.  The rendered rules hash and fields must expose it.
    assert qctx["case_release_status"] == "review_required"
    assert "MUTATED_QUALIFICATION_RULES" in _finding_codes(emitted_product, mutated)


def test_09_emitted_sbom_queues_missing_licence_metadata(monkeypatch):
    packages = [{"name": "known", "version": "1"}]
    monkeypatch.setattr(sbom, "_pip_report", lambda _python: packages)

    def metadata(_python, _name):
        return {
            "license": "MIT",
            "license_expression": "",
            "home_page": "",
            "summary": "SYNTHETIC TEST component",
            "project_urls": [],
            "license_files": [],
            "native_files": [],
            "font_files": [],
        }

    monkeypatch.setattr(sbom, "_metadata", metadata)
    clean = sbom.build_sbom("python-test", generated_at="2026-09-12T00:00:00Z")
    assert clean["review_queue"] == []
    monkeypatch.setattr(
        sbom,
        "_metadata",
        lambda python, name: {**metadata(python, name), "license": ""},
    )
    mutated = sbom.build_sbom("python-test", generated_at="2026-09-12T00:00:00Z")
    assert mutated["components"][0]["licenses"][0]["license"]["name"] == "NOASSERTION"
    assert mutated["review_queue"] == [
        {"name": "known", "version": "1", "reason": "license_metadata_missing"}
    ]


def test_10_received_bytes_never_become_institutional_acceptance(tmp_path):
    store, job, _snapshot = _case(tmp_path)
    received = _store_return(store, job["job_id"])
    profile = resolve_profile(job["request_spec"]["qualification_profile"])
    clean = normalize_institution_receipt(received["institution_acceptance"], profile)
    assert clean["recorded"] is True
    assert clean["record"]["institution_acceptance"] is False
    mutated = copy.deepcopy(received["institution_acceptance"])
    mutated["record"]["institution_acceptance"] = True
    mutated["record"]["status"] = "accepted"
    refused = normalize_institution_receipt(mutated, profile)
    assert refused["recorded"] is False
    assert "não constituem aceite" in refused["detail"]
