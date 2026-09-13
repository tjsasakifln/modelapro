"""Actual TEST worker output consumes a receipt without inventing acceptance."""
import io
import json
import zipfile

import pytest

from backend.worker import compose_valuation_job, resolve_peers
from modules.job_store import JobStore
from modules.qualification_profile import resolve_profile
from modules.report_export.recipient import OPERATOR_DECLARATION, store_recipient_return
from modules.report_export.workflow import DocumentWorkflowError, generate_documents
from tests.c17_integration.helpers import analytic_linear_csv
from tests.comercial.test_c06_document_flow import _professional_spec


def test_real_recipient_is_preserved_then_consumed_by_new_document(tmp_path):
    spec = _professional_spec()
    resolved = resolve_profile({"id": "bb-meci-avaliacao-imovel-pf"})
    spec["qualification_profile"] = {
        field: resolved[field] for field in (
            "id", "version", "source_set_sha256", "purpose", "value_basis", "method", "asset_scope", "recipient_id"
        )
    }
    spec["synthetic_test_only"] = True
    store = JobStore(tmp_path / "store", recover_abandoned=False)
    job = store.create(request_spec=spec, payload={"filename": "SYNTHETIC_TEST.csv"})
    job_id = job["job_id"]
    compose_valuation_job(
        job_id=job_id, file_bytes=analytic_linear_csv(n=30, tag="C06RETURN"),
        filename="SYNTHETIC_TEST.csv", request_spec=spec,
        subject_raw={"area": 73.5, "bairro": "Centro"}, project_id=None,
        peers=resolve_peers(), job_store=store,
    )
    old_snapshot = store.get_snapshot(job_id)
    old_pdf = store.get_artifact(job_id, "report.pdf")
    proof = b"COMPROVANTE SINTETICO DE TESTE - SEM ATO OU VALIDADE EXTERNA"
    response = store_recipient_return(
        store, job_id, filename="SYNTHETIC_TEST_return.txt", media_type="text/plain",
        content=proof, recipient_id="banco-do-brasil", protocol="TESTE-0001",
        received_at="2026-09-12T19:00:00+00:00", source="TESTE autorizado",
        operator_declaration=OPERATOR_DECLARATION, authorized_for_report=True,
        synthetic_test_only=True,
    )
    assert store.get_snapshot(job_id) == old_snapshot
    assert store.get_artifact(job_id, "report.pdf") == old_pdf
    generate_documents(store, job_id)
    snapshot = store.get_snapshot(job_id)
    acceptance = snapshot["provenance"]["qualification_context"]["institution_acceptance"]
    assert acceptance["recorded"] is True
    assert acceptance["record"]["status"] == "received_declared_unverified"
    assert acceptance["record"]["institution_acceptance"] is False
    assert acceptance["record"]["proof_sha256"] == response["record"]["proof_sha256"]
    context = json.loads(store.get_artifact(job_id, "report_context.json"))
    assert context["institution_receipt"]["record"]["record_id"] == response["record"]["record_id"]
    with zipfile.ZipFile(io.BytesIO(store.get_artifact(job_id, "evidence_bundle.zip"))) as bundle:
        assert bundle.testzip() is None
        assert proof in [bundle.read(name) for name in bundle.namelist()]
    with zipfile.ZipFile(io.BytesIO(store.get_artifact(job_id, "document_history.zip"))) as history:
        assert old_pdf in [history.read(name) for name in history.namelist()]
    first_dossier = store.get_artifact(job_id, "evidence_bundle.zip")
    second_proof = b"SEGUNDO COMPROVANTE SINTETICO DE TESTE - SEM VALIDADE EXTERNA"
    second = store_recipient_return(
        store, job_id, filename="SYNTHETIC_TEST_second.txt", media_type="text/plain",
        content=second_proof, recipient_id="banco-do-brasil", protocol="TESTE-0002",
        received_at="2026-09-12T20:00:00+00:00", source="TESTE autorizado",
        operator_declaration=OPERATOR_DECLARATION, authorized_for_report=True,
        synthetic_test_only=True,
    )
    generate_documents(store, job_id)
    with zipfile.ZipFile(io.BytesIO(store.get_artifact(job_id, "evidence_bundle.zip"))) as bundle:
        managed = [bundle.read(name) for name in bundle.namelist() if name.startswith("artifacts/documents/")]
        assert second_proof in managed
        assert proof not in managed
    with zipfile.ZipFile(io.BytesIO(store.get_artifact(job_id, "document_history.zip"))) as history:
        assert first_dossier in [history.read(name) for name in history.namelist()]
    store.save_artifact(job_id, second["record"]["stored_name"], b"ADULTERADO TESTE")
    with pytest.raises(DocumentWorkflowError) as error:
        generate_documents(store, job_id)
    assert error.value.code == "RECIPIENT_RETURN_INTEGRITY_FAILED"
