"""C02-A07: session isolation, double-submit, redacted diagnostics."""

from frontend.components.forms import DuplicateExecutionError, JobClient, build_request_spec
from frontend.components.professional import (
    BACKUP_NOTICE,
    SYNTHETIC_DEMO_NOTICE,
    diagnostic_contains_pii,
    redact_diagnostic,
    session_binding_token,
)
from frontend.components.layout import FIXTURE_SCREEN_NOTICE
from frontend.components.workflow import mapping_binding_token, should_block_duplicate_submit, widget_namespace


def test_session_tokens_differ_across_files_and_projects():
    a = session_binding_token(filename="a.csv", nbytes=10, project_id="p1", profile_id="prof-a", input_sha256="aaa")
    b = session_binding_token(filename="b.csv", nbytes=10, project_id="p1", profile_id="prof-a", input_sha256="bbb")
    c = session_binding_token(filename="a.csv", nbytes=10, project_id="p2", profile_id="prof-a", input_sha256="aaa")
    assert a != b
    assert a != c
    ta = mapping_binding_token(filename="a.csv", nbytes=10, input_sha256="aaa")
    tb = mapping_binding_token(filename="b.csv", nbytes=10, input_sha256="bbb")
    assert widget_namespace(ta) != widget_namespace(tb)


def test_double_submit_blocked_by_fingerprint():
    blocked = should_block_duplicate_submit(
        current_fingerprint="fp1",
        last_fingerprint="fp1",
        job_status={"state": "running", "job_id": "j1"},
        last_job_id="j1",
    )
    assert blocked is True
    client = JobClient(base_url="http://127.0.0.1:9", timeout=1)
    client.last_submit_fingerprint = "fp1"
    client.job_id = "j1"
    client.last_status = {"state": "queued", "job_id": "j1"}
    spec = build_request_spec(
        target_col="preco",
        candidate_cols=["area"],
        roles={"preco": "target", "area": "predictor"},
    )
    try:
        # Same fingerprint path is guarded before HTTP.
        from frontend.components.workflow import execution_fingerprint
        fp = execution_fingerprint(filename="m.csv", nbytes=4, request_spec=spec, subject={"area": "1"})
        client.last_submit_fingerprint = fp
        client.submit_job(b"data", "m.csv", spec, subject={"area": "1"})
        assert False, "expected DuplicateExecutionError"
    except DuplicateExecutionError:
        pass


def test_diagnostic_redacts_client_pii_and_fixture_is_marked():
    raw = (
        "Falha ao abrir projeto do cliente Maria Silva, CPF 123.456.789-00, "
        "e-mail maria@example.com, tel (11) 98888-7777"
    )
    assert diagnostic_contains_pii(raw) is True
    redacted = redact_diagnostic(raw)
    assert "123.456.789-00" not in redacted
    assert "maria@example.com" not in redacted
    assert "98888-7777" not in redacted
    assert "[cpf-redacted]" in redacted
    assert "[email-redacted]" in redacted
    assert diagnostic_contains_pii(redacted) is False
    assert "não é conclusão real" in FIXTURE_SCREEN_NOTICE.lower()
    assert "sintético" in SYNTHETIC_DEMO_NOTICE.lower() or "sinteticos" in SYNTHETIC_DEMO_NOTICE.lower()
    assert "cópia de segurança" in BACKUP_NOTICE.lower() or "copia de seguranca" in BACKUP_NOTICE.lower() or "backup" in BACKUP_NOTICE.lower() or "segurança" in BACKUP_NOTICE.lower()
