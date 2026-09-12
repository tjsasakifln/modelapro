"""C06 integration of the real C02 -> C01/C05 -> C03 document lifecycle.

All data, identities, review statements and certificate material in this file
are generated fixtures labelled TESTE. They are not professional opinions,
market evidence, ICP-Brasil certificates or institutional acceptance.
"""

from __future__ import annotations

import copy
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from backend.worker import compose_valuation_job, resolve_peers
from modules.job_store import JobStore
from modules.qualification_profile import resolve_profile
from modules.qualification_profile.output_conformance import assess_output_conformance
from modules.pro_workflow.report_context import build_output_manifest
from modules.report_export.submission import verify_submission_package
from modules.report_export.workflow import (
    DocumentWorkflowError,
    create_signature_request,
    generate_documents,
    import_signed_report,
    record_review,
    store_document_attachment,
)
from tests.c17_integration.helpers import (
    analytic_bairro_csv,
    analytic_linear_csv,
    request_spec,
)


ARTIFACTS_FROM_WORKER = (
    "normative_assessment.json",
    "report_context.json",
    "report.pdf",
    "evidence_bundle.zip",
)


def _professional_spec() -> dict:
    resolved = resolve_profile(
        {"id": "abnt-14653-2-regressao-mercado", "version": "1.0.0"}
    )
    profile = {
        key: resolved[key]
        for key in (
            "id",
            "version",
            "source_set_sha256",
            "purpose",
            "value_basis",
            "method",
            "asset_scope",
        )
    }
    finding = {
        "satisfied": True,
        "justification": "TESTE: exame profissional sintético registrado",
    }
    return request_spec(
        candidate_cols=["area"],
        roles={
            "preco": "target",
            "area": "predictor",
            "bairro": "source",
            "id": "identifier",
        },
        units={"area": "m2", "preco": "BRL"},
        target_unit="BRL",
        search_policy={
            "mode": "exact",
            "budget": 16,
            "objective": "aic",
            "seed": 17,
            "y_transformations": ["identity"],
            "minimum_fundamentacao_grade": 1,
        },
        value_policy={
            "adopted": {"method": "point"},
            "source": "TESTE: política sintética explicitamente declarada",
        },
        qualification_profile=profile,
        declared_documentary={
            "item1_grade": 1,
            "item3_grade": 1,
            "item1": {"grade": 1, "provenance": {"ref": "TESTE::vistoria"}},
            "item3": {"grade": 1, "provenance": {"ref": "TESTE::amostra"}},
        },
        profile_evidence={
            "parte1.6.3.vistoria": "TESTE::vistoria",
            "8.2.1.5.2.campo_suficiente": "TESTE::campo",
            "10.1.laudo_completo": "TESTE::laudo",
        },
        professional_findings={
            rule_id: finding
            for rule_id in (
                "anexoA.2.f.variaveis_relevantes",
                "anexoA.2.g.multicolinearidade",
                "anexoA.2.h.residuos_vs_independentes",
                "anexoA.2.i.pontos_influenciantes",
                "anexoA.8.agrupamentos",
            )
        },
        report_context={
            "synthetic_test_only": True,
            "applicant": "TESTE — solicitante sintético",
            "rights": "TESTE — domínio pleno sintético",
            "inspection_date": "2026-09-01",
            "asset_identification": {
                "address": "Rua de Teste, 1",
                "registration": "TESTE-001",
            },
            "region_characterization": "TESTE: região urbana sintética",
            "property_characterization": "TESTE: imóvel sintético com 73,5 m²",
            "methodology_justification": "TESTE: método comparativo por regressão",
            "assumptions": ["TESTE: dados exclusivamente sintéticos"],
            "professional_identity": {
                "name": "PROFISSIONAL TESTE",
                "registration": "CREA-TESTE-000",
                "responsibility_document": "ART-TESTE-000",
            },
        },
    )


@pytest.fixture(scope="module")
def real_worker_product(tmp_path_factory):
    root = tmp_path_factory.mktemp("c06-worker-product")
    store = JobStore(root, recover_abandoned=False)
    spec = _professional_spec()
    job = store.create(request_spec=spec, payload={"filename": "mercado-teste.csv"})
    composed = compose_valuation_job(
        job_id=job["job_id"],
        file_bytes=analytic_linear_csv(n=30, tag="C06DOC"),
        filename="mercado-teste.csv",
        request_spec=spec,
        subject_raw={"area": 73.5, "bairro": "Centro"},
        project_id=None,
        peers=resolve_peers(),
        job_store=store,
    )
    qctx = composed["snapshot"]["provenance"]["qualification_context"]
    assert qctx["calculation_status"] == "ok"
    assert qctx["grade_requirement_status"] == "met"
    assert qctx["case_release_status"] == "review_required"
    return {
        "spec": spec,
        "snapshot": store.get_snapshot(job["job_id"]),
        "artifacts": {
            name: store.get_artifact(job["job_id"], name)
            for name in ARTIFACTS_FROM_WORKER
        },
    }


def _clone_product(tmp_path, product, *, spec=None):
    store = JobStore(tmp_path / "store", recover_abandoned=False)
    job = store.create(
        request_spec=copy.deepcopy(spec or product["spec"]),
        payload={"filename": "mercado-teste.csv"},
    )
    store.save_snapshot(job["job_id"], copy.deepcopy(product["snapshot"]))
    for name, value in product["artifacts"].items():
        assert value is not None, name
        store.save_artifact(job["job_id"], name, value)
    return store, job["job_id"]


def _attach_test_document(store, job_id):
    return store_document_attachment(
        store,
        job_id,
        filename="vistoria-sintetica-teste.txt",
        media_type="text/plain",
        content=b"DOCUMENTO SINTETICO DE TESTE - SEM VALIDADE EXTERNA",
        source="TESTE::vistoria-autorizada",
        authorized_for_report=True,
        category="document",
        description="TESTE: registro documental sintético",
        synthetic_test_only=True,
    )


def _sign_with_test_certificate(pdf_bytes: bytes):
    from asn1crypto import x509 as asn1_x509
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers
    from pyhanko_certvalidator import ValidationContext

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "MODELA PRO CERTIFICADO SINTETICO DE TESTE")]
    )
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    p12 = pkcs12.serialize_key_and_certificates(
        b"TESTE",
        key,
        cert,
        None,
        serialization.BestAvailableEncryption(b"senha-teste"),
    )
    signer = signers.SimpleSigner.load_pkcs12_data(
        p12, other_certs=[], passphrase=b"senha-teste"
    )
    signed = signers.PdfSigner(
        signers.PdfSignatureMetadata(field_name="AssinaturaTeste"), signer=signer
    ).sign_pdf(IncrementalPdfFileWriter(io.BytesIO(pdf_bytes))).getvalue()
    trusted_test_cert = asn1_x509.Certificate.load(
        cert.public_bytes(serialization.Encoding.DER)
    )
    return signed, ValidationContext(
        trust_roots=[trusted_test_cert], allow_fetching=False
    )


def _review_to_signature_request(store, job_id):
    _attach_test_document(store, job_id)
    generated = generate_documents(store, job_id)
    assert generated["case_release_status"] == "review_required"
    reviewed = record_review(
        store,
        job_id,
        professional_id="CREA-TESTE-000",
        professional_name="PROFISSIONAL TESTE",
        motive="TESTE: revisão sintética sem validade externa",
        version="C06-TEST-1",
        synthetic_test_only=True,
    )
    assert reviewed["case_release_status"] == "ready_for_professional_signoff"
    assert reviewed["document_state"]["is_final"] is True
    request = create_signature_request(store, job_id, revision_id="C06-TEST-1")
    return request, store.get_artifact(job_id, "report.pdf")


def test_real_product_emits_equivalent_documents_dossier_and_test_signature(
    tmp_path, real_worker_product
):
    store, job_id = _clone_product(tmp_path, real_worker_product)
    request, unsigned = _review_to_signature_request(store, job_id)
    signed, validation_context = _sign_with_test_certificate(unsigned)
    assert signed.startswith(unsigned)

    result = import_signed_report(
        store,
        job_id,
        signed_pdf=signed,
        validation_context=validation_context,
    )
    assert result["document_state"]["is_final"] is True
    assert result["document_state"]["case_release_status"] == "signed_integrity_verified"
    assert result["signature"]["status"] == "valid"
    assert result["signature"]["synthetic_test_only"] is True
    assert result["document_state"]["document_kind"].startswith("TESTE —")
    assert result["signature"]["revision_id"] == request["revision_id"]
    assert store.get_artifact(job_id, "signed_report.pdf") == signed

    dossier = store.get_artifact(job_id, "evidence_bundle.zip")
    with zipfile.ZipFile(io.BytesIO(dossier)) as archive:
        names = set(archive.namelist())
        assert "artifacts/report.pdf" in names
        assert "artifacts/report.docx" in names
        assert "artifacts/signed_report.pdf" in names
        assert any(name.startswith("artifacts/documents/") for name in names)
        manifest = json.loads(archive.read("MANIFEST.json"))
        assert manifest["completeness_status"] == "complete"
    submission = store.get_artifact(job_id, "submission.zip")
    assert verify_submission_package(submission)["ok"] is True


def test_missing_document_and_violated_rule_remain_blocking(tmp_path, real_worker_product):
    missing_store, missing_id = _clone_product(tmp_path / "missing", real_worker_product)
    attachment = _attach_test_document(missing_store, missing_id)
    artifact_path = (
        missing_store.root / "jobs" / missing_id / "artifacts" / attachment["stored_name"]
    )
    artifact_path.unlink()
    missing = generate_documents(missing_store, missing_id)
    assert "DOCUMENTARY_ATTACHMENT_UNAVAILABLE" in {
        item["code"] for item in missing["document_state"]["blockers"]
    }

    failed_store, failed_id = _clone_product(tmp_path / "failed", real_worker_product)
    _attach_test_document(failed_store, failed_id)
    normative = json.loads(
        failed_store.get_artifact(failed_id, "normative_assessment.json")
    )
    item6 = next(
        item for item in normative["fundamentacao"]["items"] if item["id"] == "tabela1.item6"
    )
    item6["grade"] = 0
    item6["detail"] = "TESTE: violação deliberada da regra decisiva"
    failed_store.save_artifact(
        failed_id,
        "normative_assessment.json",
        json.dumps(normative, ensure_ascii=False).encode("utf-8"),
    )
    failed = generate_documents(failed_store, failed_id)
    assert failed["case_release_status"] == "analysis_only"
    assert "decisive_rule_not_satisfied" in {
        item["code"] for item in failed["document_state"]["blockers"]
    }


def test_unknown_category_is_rejected_by_the_real_c02_encoder():
    peers = resolve_peers()
    spec = request_spec(candidate_cols=["area", "bairro"])
    bundle = peers["ingest_market"](
        analytic_bairro_csv(n_per=16, tag="C06CAT"), "categorias.csv", spec
    )
    prepared = peers["fit_dataset"](bundle, spec, None)
    subject = peers["transform_subject"](
        {"area": 73.5, "bairro": "CATEGORIA_DESCONHECIDA_TESTE"},
        prepared.feature_schema,
        prepared.encoder_state,
    )
    assert subject.supported is False
    assert "unknown_category" in {item["code"] for item in subject.issues}


def test_bb_output_strings_and_test_certificate_cannot_claim_icp_conformance():
    bb = resolve_profile({"id": "bb-meci-avaliacao-imovel-pf", "version": "0.3.0"})
    declarations = {
        item["id"]: "TESTE: alegação textual sem representação verificada"
        for item in bb["output_requirements"]
    }
    manifest = build_output_manifest(
        {"schema_version": "MP/1"}, {"output_evidence": declarations}
    )
    assert manifest["items"] == {}
    assessed = assess_output_conformance(bb, manifest)
    by_id = {item["rule_id"]: item for item in assessed["rule_results"]}
    assert by_id["bb.guiar.assinatura_icp"]["status"] == "unsupported"
    assert assessed["would_be_accepted_without_reservations"] is False


def test_material_change_invalidates_review_and_signature_request(
    tmp_path, real_worker_product
):
    store, job_id = _clone_product(tmp_path, real_worker_product)
    _request, _unsigned = _review_to_signature_request(store, job_id)
    changed = store.get_snapshot(job_id)
    changed["value"]["point"] += 1000.0
    store.save_snapshot(job_id, changed)
    with pytest.raises(DocumentWorkflowError, match="not ready for signature"):
        create_signature_request(store, job_id, revision_id="C06-TEST-2")


def test_stale_or_adulterated_signed_pdf_is_not_persisted(
    tmp_path, real_worker_product
):
    stale_store, stale_id = _clone_product(tmp_path / "stale", real_worker_product)
    _request, unsigned = _review_to_signature_request(stale_store, stale_id)
    signed, validation_context = _sign_with_test_certificate(unsigned)
    changed = stale_store.get_snapshot(stale_id)
    changed["model"]["coefficients"]["area"] += 1.0
    stale_store.save_snapshot(stale_id, changed)
    with pytest.raises(DocumentWorkflowError) as stale:
        import_signed_report(
            stale_store,
            stale_id,
            signed_pdf=signed,
            validation_context=validation_context,
        )
    assert stale.value.code == "SIGNATURE_BINDING_STALE"
    assert stale_store.get_artifact(stale_id, "signed_report.pdf") is None

    tampered_store, tampered_id = _clone_product(tmp_path / "tampered", real_worker_product)
    _request, unsigned = _review_to_signature_request(tampered_store, tampered_id)
    signed, validation_context = _sign_with_test_certificate(unsigned)
    tampered = bytearray(signed)
    tampered[-200] ^= 1
    with pytest.raises(DocumentWorkflowError) as invalid:
        import_signed_report(
            tampered_store,
            tampered_id,
            signed_pdf=bytes(tampered),
            validation_context=validation_context,
        )
    assert invalid.value.code == "SIGNATURE_NOT_VALID"
    assert tampered_store.get_artifact(tampered_id, "signed_report.pdf") is None
