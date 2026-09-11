"""P02-A03: vínculo arquivo/esquema, invalidação e bloqueio de POST duplicado."""

from frontend.components.forms import (
    DuplicateExecutionError,
    JobClient,
    build_request_spec,
    preview_to_form_model,
)
from frontend.components.workflow import (
    apply_invalidation,
    execution_fingerprint,
    mapping_binding_token,
    preview_failure_clears_interpretation,
    schema_fingerprint,
    should_block_duplicate_submit,
    unused_columns_view,
    widget_namespace,
)
from tests.c09_frontend.fixtures import PREVIEW_BAIRRO_FORMATTED
from tests.c09_frontend.test_job_client import _spec, _start


def test_mapping_token_differs_for_different_files():
    a = mapping_binding_token(filename="a.csv", nbytes=10, import_options={"locale": "pt-BR"}, input_sha256="aaa")
    b = mapping_binding_token(filename="b.xlsx", nbytes=10, import_options={"locale": "pt-BR"}, input_sha256="bbb")
    assert a != b
    assert widget_namespace(a) != widget_namespace(b)


def test_same_schema_same_file_keeps_token():
    token = mapping_binding_token(
        filename="m.csv",
        nbytes=4,
        import_options={"locale": "pt-BR"},
        input_sha256="abc",
        schema_fingerprint=schema_fingerprint(PREVIEW_BAIRRO_FORMATTED),
    )
    again = mapping_binding_token(
        filename="m.csv",
        nbytes=4,
        import_options={"locale": "pt-BR"},
        input_sha256="abc",
        schema_fingerprint=schema_fingerprint(PREVIEW_BAIRRO_FORMATTED),
    )
    assert token == again


def test_file_change_invalidates_preview_and_marks_previous_result():
    session = {
        "c09_preview": PREVIEW_BAIRRO_FORMATTED,
        "c09_snapshot": {"value": {"point": 1}},
        "p02_subject": {"raw_values": {"area": "10"}},
    }
    out = apply_invalidation(session, "file")
    assert "c09_preview" not in out
    assert out["p02_result_stale"] is True
    assert "versão anterior" in out["p02_result_stale_reason"]
    assert out["p02_previous_snapshot"]["value"]["point"] == 1
    assert session["c09_preview"] is PREVIEW_BAIRRO_FORMATTED


def test_subject_or_policy_change_keeps_preview_but_stales_result():
    session = {"c09_preview": {"ok": True}, "c09_snapshot": {"value": {"point": 2}}}
    subject = apply_invalidation(session, "subject")
    assert subject["c09_preview"]["ok"] is True
    assert subject["p02_result_stale"] is True
    policy = apply_invalidation(session, "policy")
    assert "política" in policy["p02_result_stale_reason"].lower() or "politica" in policy["p02_result_stale_reason"].lower()


def test_preview_failure_drops_old_interpretation():
    session = {"c09_preview": PREVIEW_BAIRRO_FORMATTED, "p02_form_model": {"columns": ["x"]}}
    out = preview_failure_clears_interpretation(session)
    assert "c09_preview" not in out
    assert "p02_form_model" not in out
    assert out["p02_preview_error_cleared"] is True


def test_unused_columns_state_reason_and_never_silent():
    model = preview_to_form_model(PREVIEW_BAIRRO_FORMATTED)
    roles = {"preco": "target", "bairro": "predictor", "area": "predictor", "informante": "identifier"}
    unused = unused_columns_view(
        model["column_map"],
        roles=roles,
        candidate_cols=["area"],
        target_col="preco",
        preview_issues=model["issues"],
    )
    names = {item["name"] for item in unused}
    assert "informante" in names
    assert "bairro" in names
    informante = next(item for item in unused if item["name"] == "informante")
    assert "papel" in informante["reason"]
    bairro = next(item for item in unused if item["name"] == "bairro")
    assert "não autorizada" in bairro["reason"]


def test_equivalent_fingerprint_blocks_second_post():
    spec = build_request_spec(
        target_col="preco",
        candidate_cols=["area"],
        roles={"preco": "target", "area": "predictor"},
        evaluation_method="none",
        minimum_fundamentacao_grade=None,
    )
    fp = execution_fingerprint(filename="a.csv", nbytes=3, request_spec=spec, subject={"area": "73,5"})
    assert should_block_duplicate_submit(
        current_fingerprint=fp,
        last_fingerprint=fp,
        job_status={"state": "succeeded", "job_id": "job-1"},
        last_job_id="job-1",
    )
    other = execution_fingerprint(filename="a.csv", nbytes=3, request_spec=spec, subject={"area": "80"})
    assert other != fp
    assert should_block_duplicate_submit(
        current_fingerprint=other,
        last_fingerprint=fp,
        last_job_id="job-1",
    ) is False


def test_job_client_blocks_equivalent_submit_after_success():
    server, url = _start({"job_state": "succeeded", "result_available": True})
    try:
        client = JobClient(base_url=url, timeout=2)
        client.submit_job(b"col\n1", "a.csv", _spec(), subject={"area": "10"})
        assert server.jobs_posted == 1
        client.last_status = {"job_id": "job-1", "state": "succeeded", "result_available": True}
        try:
            client.submit_job(b"col\n1", "a.csv", _spec(), subject={"area": "10"})
            raise AssertionError("equivalent work must not POST again")
        except DuplicateExecutionError:
            pass
        assert server.jobs_posted == 1
        client.submit_job(b"col\n1", "a.csv", _spec(), subject={"area": "11"})
        assert server.jobs_posted == 2
    finally:
        server.shutdown()
