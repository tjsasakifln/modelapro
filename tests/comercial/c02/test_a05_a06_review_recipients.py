"""C02-A05 / C02-A06: review invalidation, recipients, real HTTP routes — shipped client."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from frontend.components.forms import JobClient, build_request_spec
from frontend.components.professional import (
    case_release_to_issuance,
    declared_fingerprint_from_imported,
    export_recipient_package_manifest,
    gate_ready_for_professional_signoff,
    invalidate_review_events,
    map_issuance_to_case_release,
    may_reuse_prior_consent,
    present_calculated_vs_adopted,
    present_seguro_value_basis,
    record_institution_return,
    record_institution_submission,
    record_review_event,
    select_qualification_profile,
    sha256_bytes,
    verify_imported_signature_link,
)
from frontend.components.workflow import apply_invalidation
from tests.c09_frontend.fixtures import SNAPSHOT_CLASSIFIED


def test_review_event_binds_to_fingerprint_and_material_change_invalidates():
    event = record_review_event(
        fingerprint="fp-a",
        professional_id="prof-1",
        decision="reviewed",
        motive="amostra e equação conferidas",
        version="C02/1",
        evidence="checklist item sample_review",
    )
    assert event["consent_reusable"] is False
    assert event["signature_image_reused"] is False
    stale = invalidate_review_events([event], current_fingerprint="fp-b")
    assert stale[0]["stale"] is True
    assert stale[0]["consent_reusable"] is False
    assert stale[0]["fingerprint"] == "fp-a"
    assert may_reuse_prior_consent(stale, current_fingerprint="fp-b") is False
    assert may_reuse_prior_consent([], current_fingerprint="fp-b") is False
    live = [record_review_event(
        fingerprint="fp-b",
        professional_id="prof-1",
        decision="reviewed",
        motive="versão atual",
        version="C02/1",
    )]
    assert may_reuse_prior_consent(live, current_fingerprint="fp-b") is True
    session = apply_invalidation(
        {"c09_snapshot": {"value": {"point": 1}}, "c02_review_events": [event]},
        "document",
    )
    assert session["c02_signature_stale"] is True
    assert session["c02_review_events_history"][0]["decision"] == "reviewed"


def test_distinct_reviewer_required_for_bank_profile():
    try:
        record_review_event(
            fingerprint="fp",
            professional_id="prof-1",
            decision="signoff",
            motive="ok",
            version="C02/1",
            distinct_reviewer_required=True,
            reviewer_id="prof-1",
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "revisor distinto" in str(exc)


def test_issuance_mapping_does_not_emit_illegal_mp1_status():
    mapped = map_issuance_to_case_release("ready_for_professional_review")
    assert mapped["case_release_status"] == "ready_for_professional_signoff"
    assert mapped["issuance_status"] == "ready_for_professional_review"
    assert mapped["emitted_illegal_issuance"] is False
    back = case_release_to_issuance("signed_integrity_verified")
    assert back["issuance_status"] == "ready_for_professional_review"
    assert back["local_only"] is True
    assert back["emitted_illegal_issuance"] is False
    illegal = case_release_to_issuance("ready_for_professional_signoff")
    assert illegal["issuance_status"] in {"draft", "review_required", "ready_for_professional_review"}


def test_adopted_value_refused_until_c05_admits():
    waiting = present_calculated_vs_adopted(calculated_point=735000, adopted_point=700000, justification="arbitragem")
    assert waiting["recorded"] is False
    assert waiting["admitted"] is False
    assert waiting["silent_override"] is False
    blocked = present_calculated_vs_adopted(
        calculated_point=735000,
        adopted_point=700000,
        justification="",
        c05_admits=True,
    )
    assert blocked["blocked"] is True
    ok = present_calculated_vs_adopted(
        calculated_point=735000,
        adopted_point=700000,
        justification="arbitragem admitida pelo perfil",
        c05_admits=True,
    )
    assert ok["recorded"] is True


def test_local_http_200_is_not_institution_acceptance():
    event = record_institution_submission(
        recipient_id="banco",
        package_name="urban-comparative-bank-guarantee@1",
        instructions_version="1",
        http_status=200,
        imported_proof=False,
    )
    assert event["institution_acceptance"] is False
    assert event["accepted"] is False
    assert event["simulated_portal"] is False
    assert event["local_http_200_is_not_acceptance"] is True
    ret = record_institution_return(
        recipient_id="banco",
        imported_filename="retorno-sintetico.pdf",
        proof_sha256=sha256_bytes(b"synthetic-proof"),
        decision="received",
        authorized_act=False,
    )
    assert ret["institution_acceptance"] is False
    assert ret["simulated_portal"] is False


def test_seguro_mismatch_is_not_hidden():
    insurer = select_qualification_profile("urban-comparative-insurer-reconstruction")
    view = present_seguro_value_basis(insurer)
    assert view["mismatch_hidden"] is False
    assert view["market_converted_to_cost"] is False
    assert view["required_value_basis"] == "reconstruction_cost"
    assert "mercado" in view["note"].lower() or "custo" in view["note"].lower()


def test_imported_signature_must_link_fingerprint_and_product_does_not_sign():
    missing = verify_imported_signature_link(
        fingerprint="fp-1",
        imported_sha256="",
        declared_fingerprint=None,
    )
    assert missing["linked"] is False
    assert missing["status"] == "unlinked"
    package = json.dumps({"package": {"fingerprint": "fp-1"}}).encode("utf-8")
    declared = declared_fingerprint_from_imported(package)
    assert declared == "fp-1"
    linked = verify_imported_signature_link(
        fingerprint="fp-1",
        imported_sha256=sha256_bytes(package),
        declared_fingerprint=declared,
    )
    assert linked["linked"] is True
    assert linked["signed_in_product_name"] is False
    unlinked = verify_imported_signature_link(
        fingerprint="fp-1",
        imported_sha256=sha256_bytes(b"%PDF-old-consent"),
        declared_fingerprint="fp-old",
    )
    assert unlinked["linked"] is False
    assert unlinked["reused_old_image"] is False


class _Stub(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        return

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _json(self, code: int, payload):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _bytes(self, code: int, payload: bytes):
        self.send_response(code)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        body = self._body()
        if self.path == "/preview":
            self.server.previews.append(body)
            self._json(200, {
                "schema_version": "MP/1",
                "input_sha256": "abc",
                "column_map": {"preco": {"kind": "numeric"}, "area": {"kind": "numeric"}},
                "sample_preview": [{"area": "73,5", "preco": "735000"}],
            })
            return
        if self.path == "/jobs":
            self.server.jobs.append(body)
            self._json(202, {"job_id": "job-c02", "state": "queued", "status_url": "/jobs/job-c02"})
            return
        if self.path.endswith("/revisions"):
            payload = json.loads(body.decode("utf-8") or "{}")
            self.server.revisions.append(payload)
            self._json(201, {"revision_id": "rev-c02", "project_id": "proj-c02", "job_id": "job-c02"})
            return
        if self.path.endswith("/batch"):
            self.server.batches.append(body)
            self._json(202, {"job_id": "batch-c02"})
            return
        if self.path.startswith("/institution"):
            self.send_error(404)
            return
        self._json(404, {"error": self.path})

    def do_GET(self):
        if self.path == "/jobs/job-c02":
            self._json(200, {"job_id": "job-c02", "state": "succeeded", "result_available": True, "artifact_states": {"report.pdf": {"state": "ready"}}})
            return
        if self.path == "/jobs/job-c02/result":
            self._json(200, SNAPSHOT_CLASSIFIED)
            return
        if self.path == "/jobs/job-c02/artifacts/report.pdf":
            self._bytes(200, b"%PDF-synthetic")
            return
        if self.path == "/projects":
            self._json(200, {"schema_version": "MP/1", "projects": [{"project_id": "proj-c02"}]})
            return
        if self.path == "/projects/proj-c02":
            self._json(200, {
                "schema_version": "MP/1",
                "project_id": "proj-c02",
                "revision": {"revision_id": "rev-c02", "job_id": "job-c02", "snapshot_ref": {"job_id": "job-c02"}},
            })
            return
        if self.path.endswith("/revisions"):
            self.send_response(405)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._json(404, {"error": self.path})


def _start():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    server.previews = []
    server.jobs = []
    server.revisions = []
    server.batches = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_job_client_uses_real_routes_and_does_not_treat_200_as_acceptance():
    server = _start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        client = JobClient(base_url=base, timeout=5)
        profile = select_qualification_profile("urban-comparative-market-professional")
        spec = build_request_spec(
            target_col="preco",
            candidate_cols=["area"],
            roles={"preco": "target", "area": "predictor"},
            purpose="avaliacao_profissional",
            rights="plena_propriedade",
            recipient_id="solicitante",
            value_basis="market_value",
            asset_scope="urban_real_estate",
            qualification_profile=profile,
            reference_date="2024-01-15",
            target_unit="BRL",
            applicant="Solicitante sintético",
        )
        preview = client.preview(b"id;area;preco\n", "m.csv", spec)
        assert preview["sample_preview"]
        posted = client.submit_job(b"id;area;preco\n", "m.csv", spec, subject={"area": "73,5"})
        assert posted["job_id"] == "job-c02"
        body = server.jobs[-1]
        assert b"qualification_profile" in body
        assert b"urban-comparative-market-professional" in body
        status = client.recover("job-c02")
        assert status["state"] == "succeeded"
        assert client.last_snapshot["value"]["point"] == SNAPSHOT_CLASSIFIED["value"]["point"]
        projects = client.list_projects()
        assert projects[0]["project_id"] == "proj-c02"
        opened = client.get_project("proj-c02")
        assert opened["revision"]["job_id"] == "job-c02"
        saved = client.save_revision("proj-c02", {"schema_version": "MP/1", "job_id": "job-c02"})
        assert saved["revision_id"] == "rev-c02"
        artifact = client.get_artifact("report.pdf")
        assert artifact.startswith(b"%PDF")
        batch = client.submit_batch("proj-c02", {"subjects": [{"area": "73,5"}]})
        assert batch["job_id"] == "batch-c02"
        # A 200 from this stub is not institution_acceptance.
        submission = record_institution_submission(
            recipient_id="banco",
            package_name="x",
            instructions_version="1",
            http_status=200,
        )
        assert submission["institution_acceptance"] is False
        manifest = export_recipient_package_manifest(profile=profile, fingerprint="fp", artifact_names=["report.pdf"])
        assert manifest["simulated_send"] is False
        assert manifest["homologated"] is False
        gate = gate_ready_for_professional_signoff(profile=profile, essential_evidence_present=True, current_fingerprint="fp")
        assert gate["emitted_illegal_issuance"] is False
    finally:
        server.shutdown()
        server.server_close()
