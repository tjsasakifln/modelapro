"""C10-A04: two local jobs do not mix context; PDF fail is visible on GET."""

import json

from fastapi.testclient import TestClient

from backend.api import app, reset_runtime
from tests.c10_pipeline.doubles import CallLog, install_labeled_runtime, make_peers
from tests.c10_pipeline.fixtures import complete_request_spec, market_csv_bytes, subject_raw


def test_two_jobs_do_not_mix_subject_snapshot_or_artifacts():
    reset_runtime()
    log = CallLog()
    # Distinct points per peer map: install once then run two jobs with different points
    # by swapping peers between submissions via two runtime installs is the
    # realistic API path (each request resolves get_peers()). We submit both
    # against one store by using peers that derive the point from the filename
    # recorded at ingest — implemented here as two sequential installs that
    # share nothing except the TestClient app, which is rebound each time.
    client = TestClient(app)

    store_a, _, _, log_a, _ = install_labeled_runtime(point=111000.0)
    resp_a = client.post(
        "/jobs",
        files={"file": ("a.csv", market_csv_bytes("AAA"), "text/csv")},
        data={
            "request_json": json.dumps(complete_request_spec()),
            "subject_json": json.dumps(subject_raw("centro", 80)),
        },
    )
    job_a = resp_a.json()["job_id"]
    snap_a = client.get(f"/jobs/{job_a}/result").json()
    art_a = client.get(f"/jobs/{job_a}/artifacts/report.pdf")
    ingest_a = log_a.first("ingest_market")

    store_b, _, _, log_b, _ = install_labeled_runtime(point=222000.0)
    # Rebind keeps a new store; to prove isolation we also run both against one
    # store below. First assert sequential rebinds do not leak subject/point.
    resp_b = client.post(
        "/jobs",
        files={"file": ("b.csv", market_csv_bytes("BBB"), "text/csv")},
        data={
            "request_json": json.dumps(complete_request_spec()),
            "subject_json": json.dumps(subject_raw("norte", 120)),
        },
    )
    job_b = resp_b.json()["job_id"]
    snap_b = client.get(f"/jobs/{job_b}/result").json()
    art_b = client.get(f"/jobs/{job_b}/artifacts/report.pdf")

    assert job_a != job_b
    assert snap_a["value"]["point"] == 111000.0
    assert snap_b["value"]["point"] == 222000.0
    assert ingest_a["filename"] == "a.csv"
    assert log_b.first("ingest_market")["filename"] == "b.csv"
    assert log_a.first("transform_subject")["subject_raw"]["bairro"] == "centro"
    assert log_b.first("transform_subject")["subject_raw"]["bairro"] == "norte"
    assert art_a.content != b"" and art_b.content != b""
    # Same labeled PDF bytes in this double — isolation of *identity* is via
    # job_id keying on the store, checked next on a shared store.


def test_shared_store_keeps_artifacts_and_snapshots_keyed_by_job():
    from backend.api import bind_runtime
    from tests.c10_pipeline.doubles import LabeledJobStore, LabeledProjectStore, LabeledTaskRunner

    store = LabeledJobStore()
    projects = LabeledProjectStore()
    runner = LabeledTaskRunner(auto_run=True)
    log = CallLog()

    def peers_for(point):
        return make_peers(log, point=point)

    client = TestClient(app)
    bind_runtime(job_store=store, project_store=projects, task_runner=runner, peers=peers_for(101.0), reset_submissions=True)
    a = client.post(
        "/jobs",
        files={"file": ("a.csv", market_csv_bytes("A"), "text/csv")},
        data={"request_json": json.dumps(complete_request_spec()), "subject_json": json.dumps(subject_raw("centro"))},
    )
    job_a = a.json()["job_id"]
    bind_runtime(job_store=store, project_store=projects, task_runner=runner, peers=peers_for(202.0), reset_submissions=False)
    b = client.post(
        "/jobs",
        files={"file": ("b.csv", market_csv_bytes("B"), "text/csv")},
        data={"request_json": json.dumps(complete_request_spec()), "subject_json": json.dumps(subject_raw("sul"))},
    )
    job_b = b.json()["job_id"]
    assert job_a != job_b
    snap_a = store.get_snapshot(job_a)
    snap_b = store.get_snapshot(job_b)
    assert snap_a["value"]["point"] == 101.0
    assert snap_b["value"]["point"] == 202.0
    assert store.get_artifact(job_a, "report.pdf") is not None
    assert store.get_artifact(job_b, "report.pdf") is not None
    # Frozen projects are distinct objects keyed by job.
    assert store.get_artifact(job_a, "frozen_project.json") != store.get_artifact(job_b, "frozen_project.json")


def test_pdf_failure_visible_on_get_and_snapshot_retrievable():
    store, _projects, _runner, _log, _peers = install_labeled_runtime(pdf_error=True, point=150000.0)
    client = TestClient(app)
    resp = client.post(
        "/jobs",
        files={"file": ("m.csv", market_csv_bytes("PDF"), "text/csv")},
        data={
            "request_json": json.dumps(complete_request_spec()),
            "subject_json": json.dumps(subject_raw()),
        },
    )
    job_id = resp.json()["job_id"]
    status = client.get(f"/jobs/{job_id}").json()
    assert status["state"] == "succeeded"
    assert status["calculation_state"] == "succeeded"
    assert status["artifact_states"]["report.pdf"]["state"] == "failed"
    assert status["artifact_states"]["report.pdf"]["error"]["code"] == "PDF_FAILED"
    result = client.get(f"/jobs/{job_id}/result")
    assert result.status_code == 200
    assert result.json()["value"]["point"] == 150000.0
    missing_pdf = client.get(f"/jobs/{job_id}/artifacts/report.pdf")
    assert missing_pdf.status_code == 404
