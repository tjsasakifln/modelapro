"""C10-A03: HTTP job lifecycle via the real FastAPI app."""

import json
import math

from fastapi.testclient import TestClient

from backend.api import app, recover_interrupted_jobs, reset_runtime
from tests.c10_pipeline.doubles import install_labeled_runtime
from tests.c10_pipeline.fixtures import complete_request_spec, market_csv_bytes, subject_raw


def _issues(resp):
    body = resp.json()
    if "issues" in body:
        return body["issues"]
    detail = body.get("detail")
    if isinstance(detail, dict):
        return detail.get("issues") or []
    return []


def _post_job(client, tag="A", spec=None, subject=None):
    spec = spec or complete_request_spec()
    files = {"file": (f"m-{tag}.csv", market_csv_bytes(tag), "text/csv")}
    data = {"request_json": json.dumps(spec)}
    if subject is not None:
        data["subject_json"] = json.dumps(subject)
    return client.post("/jobs", files=files, data=data)


def test_post_jobs_202_and_get_recovers_result_twice():
    for run in (1, 2):
        reset_runtime()
        store, _projects, runner, log, _peers = install_labeled_runtime(point=150000.0 + run)
        client = TestClient(app)
        resp = _post_job(client, tag=f"R{run}", subject=subject_raw())
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["job_id"]
        assert isinstance(body["access_token"], str) and body["access_token"]
        assert body["status_url"] == f"/jobs/{body['job_id']}"
        job_id = body["job_id"]

        assert client.get(
            f"/jobs/{job_id}/result", headers={"X-Job-Token": "wrong"}
        ).status_code == 403
        assert client.get(
            f"/jobs/{job_id}/result",
            headers={"X-Job-Token": body["access_token"]},
        ).status_code == 200

        status = client.get(f"/jobs/{job_id}")
        assert status.status_code == 200
        st = status.json()
        assert st["state"] == "succeeded"
        assert st["result_available"] is True
        assert st["schema_version"] == "MP/1"

        result = client.get(f"/jobs/{job_id}/result")
        assert result.status_code == 200
        snap = result.json()
        assert snap["schema_version"] == "MP/1"
        assert snap["value"]["point"] == 150000.0 + run
        assert snap["job_id"] == job_id
        assert runner.submitted == [job_id]
        assert "search_models" in log.names()


def test_preview_does_not_invoke_search_or_write_revision():
    _store, projects, _runner, log, _peers = install_labeled_runtime()
    client = TestClient(app)
    files = {"file": ("m.csv", market_csv_bytes("P"), "text/csv")}
    data = {
        "request_json": json.dumps(complete_request_spec()),
        "subject_json": json.dumps(subject_raw()),
    }
    resp = client.post("/preview", files=files, data=data)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["preview"] is True
    assert body["search_invoked"] is False
    assert "search_models" not in log.names()
    assert "evaluate_fitted" not in log.names()
    assert projects.list() == []


def test_invalid_json_degree_candidates_nonfinite_are_4xx_not_200():
    install_labeled_runtime()
    client = TestClient(app)
    files = {"file": ("m.csv", market_csv_bytes("X"), "text/csv")}

    bad_json = client.post("/jobs", files=files, data={"request_json": "{not json"})
    assert bad_json.status_code == 400
    assert bad_json.status_code != 200

    spec = complete_request_spec()
    spec["search_policy"]["target_degree"] = 9
    degree = client.post(
        "/jobs",
        files={"file": ("m.csv", market_csv_bytes("X"), "text/csv")},
        data={"request_json": json.dumps(spec)},
    )
    assert degree.status_code == 400
    assert any(i["code"] == "DEGREE_OUT_OF_RANGE" for i in _issues(degree))

    spec = complete_request_spec(candidate_cols=[])
    empty = client.post(
        "/jobs",
        files={"file": ("m.csv", market_csv_bytes("X"), "text/csv")},
        data={"request_json": json.dumps(spec)},
    )
    assert empty.status_code == 400
    assert any(i["code"] == "CANDIDATE_COLS_EMPTY" for i in _issues(empty))

    spec = complete_request_spec()
    nan_subject = client.post(
        "/jobs",
        files={"file": ("m.csv", market_csv_bytes("X"), "text/csv")},
        data={
            "request_json": json.dumps(spec),
            "subject_json": json.dumps({"area": math.nan}),
        },
    )
    assert nan_subject.status_code == 400
    assert any(i["code"] == "NON_FINITE_NUMBER" for i in _issues(nan_subject))


def test_idempotent_resubmit_does_not_duplicate_work():
    _store, _projects, runner, log, _peers = install_labeled_runtime(point=111.0)
    client = TestClient(app)
    spec = complete_request_spec()
    subject = subject_raw()
    first = _post_job(client, tag="IDEM", spec=spec, subject=subject)
    second = _post_job(client, tag="IDEM", spec=spec, subject=subject)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert second.json().get("idempotent_replay") is True
    assert second.json().get("access_token") is None
    assert runner.submitted == [first.json()["job_id"]]
    assert log.names().count("search_models") == 1


def test_cancel_uses_runner_and_stops_before_search():
    store, _projects, runner, log, _peers = install_labeled_runtime(auto_run=False)
    client = TestClient(app)
    resp = _post_job(client, tag="CAN", subject=subject_raw())
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert store.get(job_id)["state"] == "queued"
    cancel = client.post(f"/jobs/{job_id}/cancel")
    assert cancel.status_code == 200
    assert runner.is_cancelled(job_id)
    runner.run(job_id)
    job = client.get(f"/jobs/{job_id}").json()
    assert job["state"] == "cancelled"
    assert "search_models" not in log.names()


def test_result_not_available_is_explicit_http_not_empty_success():
    store, _projects, _runner, _log, _peers = install_labeled_runtime(auto_run=False)
    client = TestClient(app)
    resp = _post_job(client, tag="PEND")
    job_id = resp.json()["job_id"]
    result = client.get(f"/jobs/{job_id}/result")
    assert result.status_code == 409
    body = result.json()
    assert body.get("result_available") is False
    assert body.get("schema_version") == "MP/1"
    unknown = client.get("/jobs/does-not-exist/result")
    assert unknown.status_code == 404


def test_upload_adapter_returns_202_with_job_id():
    install_labeled_runtime()
    client = TestClient(app)
    files = {"file": ("m.csv", market_csv_bytes("U"), "text/csv")}
    data = {"degree": 2, "target_col": "preco", "solicitante": "X", "finalidade": "teste"}
    resp = client.post("/upload", files=files, data=data)
    assert resp.status_code == 202, resp.text
    assert resp.json()["job_id"]
    job_id = resp.json()["job_id"]
    snap = client.get(f"/jobs/{job_id}/result")
    assert snap.status_code == 200
    assert snap.json()["target"]["column"] == "preco"


def test_upload_empty_candidates_is_4xx_not_all_columns():
    install_labeled_runtime()
    client = TestClient(app)
    files = {"file": ("m.csv", market_csv_bytes("U"), "text/csv")}
    data = {
        "degree": 1,
        "target_col": "preco",
        "candidate_cols_json": "[]",
    }
    resp = client.post("/upload", files=files, data=data)
    assert resp.status_code == 400
    assert any(i["code"] == "CANDIDATE_COLS_EMPTY" for i in _issues(resp))


def test_interrupted_on_restart_not_stuck_running():
    store, _projects, _runner, _log, _peers = install_labeled_runtime(auto_run=False)
    created = store.create(payload={})
    store.update_transition(created["job_id"], "queued", "running")
    n = recover_interrupted_jobs(store)
    assert n == 1
    client = TestClient(app)
    # bind already installed
    status = client.get(f"/jobs/{created['job_id']}")
    assert status.status_code == 200
    assert status.json()["state"] == "interrupted"


def test_projects_revisions_immutable_and_batch_uses_evaluate_batch():
    _store, projects, runner, log, _peers = install_labeled_runtime()
    client = TestClient(app)
    payload = {"schema_version": "MP/1", "request_spec": complete_request_spec(), "frozen": True}
    created = client.post("/projects/p1/revisions", json=payload)
    assert created.status_code == 201
    rev_id = created.json()["revision_id"]
    loaded = client.get("/projects/p1")
    assert loaded.status_code == 200
    first = projects.load_revision("p1", rev_id)
    client.post("/projects/p1/revisions", json={**payload, "note": "second"})
    still = projects.load_revision("p1", rev_id)
    assert still == first
    batch = client.post(
        "/projects/p1/batch",
        json={"subjects": [{"area": 1}, {"area": 2}], "revision_id": rev_id},
    )
    assert batch.status_code == 202, batch.text
    assert "evaluate_batch" in log.names()
    assert runner.submitted


def test_batch_idempotency_hashes_subjects_not_just_count():
    """Same n, different subjects must not reuse the first job or skip evaluate_batch."""
    _store, _projects, runner, log, _peers = install_labeled_runtime()
    client = TestClient(app)
    payload = {"schema_version": "MP/1", "request_spec": complete_request_spec(), "frozen": True}
    created = client.post("/projects/p-batch/revisions", json=payload)
    assert created.status_code == 201, created.text
    rev_id = created.json()["revision_id"]

    first = client.post(
        "/projects/p-batch/batch",
        json={"subjects": [{"area": 1}, {"area": 2}], "revision_id": rev_id},
    )
    second = client.post(
        "/projects/p-batch/batch",
        json={"subjects": [{"area": 9}, {"area": 8}], "revision_id": rev_id},
    )
    replay = client.post(
        "/projects/p-batch/batch",
        json={"subjects": [{"area": 1}, {"area": 2}], "revision_id": rev_id},
    )
    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert replay.status_code == 202, replay.text
    job_a = first.json()["job_id"]
    job_b = second.json()["job_id"]
    assert job_a != job_b
    assert replay.json()["job_id"] == job_a
    assert replay.json().get("idempotent_replay") is True
    assert log.names().count("evaluate_batch") == 2
    assert runner.submitted.count(job_a) == 1
    assert runner.submitted.count(job_b) == 1
