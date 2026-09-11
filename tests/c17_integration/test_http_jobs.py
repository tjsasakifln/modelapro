"""Drive shipped POST /jobs → GET status → GET result with real MP/1 peers."""

from __future__ import annotations

import json

from backend.worker import compose_valuation_job, current_code_sha, peer_kind, resolve_peers

from .helpers import (
    client,
    finite_or_null,
    get_result,
    issue_codes,
    issues_of,
    post_job,
    production_peers,
    ptbr_csv_bytes,
    request_spec,
    subject_raw,
    wait_job,
)


def test_production_peers_are_real_imports():
    peers = resolve_peers()
    required = (
        "ingest_market",
        "fit_dataset",
        "transform_subject",
        "search_models",
        "assess_normative",
        "recommend_next_actions",
        "evaluate_fitted",
        "render_report",
        "build_evidence_bundle",
        "evaluate_batch",
    )
    for name in required:
        kind, ref = peer_kind(peers[name])
        assert kind == "real", f"{name} is {kind}:{ref}"
        assert not getattr(peers[name], "contract_simulator", False)
        assert "doubles" not in ref


def test_post_jobs_returns_mp1_snapshot_without_simulators():
    test_client = client()
    resp = post_job(
        test_client,
        file_bytes=ptbr_csv_bytes(tag="JOB1"),
        subject=subject_raw(),
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["schema_version"] == "MP/1"
    job_id = body["job_id"]
    assert body["status_url"] == f"/jobs/{job_id}"
    assert body["result_url"] == f"/jobs/{job_id}/result"

    status = wait_job(test_client, job_id)
    result = get_result(test_client, job_id)
    assert status["state"] == "succeeded", status
    assert status["result_available"] is True
    assert result.status_code == 200, result.text
    snap = result.json()
    assert snap["schema_version"] == "MP/1"
    assert snap["job_id"] == job_id
    assert finite_or_null(snap["value"]["point"])
    if snap["value"]["point"] == 0:
        assert snap["issues"], "zero point requires issues; 0 is not a silent substitute"
    assert "used_row_ids" in snap["sample"]
    assert "excluded_row_ids" in snap["sample"]
    assert snap["sample"]["observed_target"] < snap["sample"]["received"]
    peers = (snap.get("provenance") or {}).get("peers") or {}
    for name, meta in peers.items():
        assert meta.get("kind") != "simulator", f"{name} recorded as simulator"
    assert "NaN" not in result.text
    assert "Infinity" not in result.text


def test_two_jobs_do_not_leak_values():
    test_client = client()
    first = post_job(
        test_client,
        file_bytes=ptbr_csv_bytes(tag="ISO-A"),
        subject=subject_raw(area=85.5),
    )
    second = post_job(
        test_client,
        file_bytes=ptbr_csv_bytes(n=30, tag="ISO-B"),
        subject=subject_raw(area=100.0),
        spec=request_spec(applicant="Sintetico C17 B"),
    )
    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    id_a = first.json()["job_id"]
    id_b = second.json()["job_id"]
    assert id_a != id_b
    wait_job(test_client, id_a)
    wait_job(test_client, id_b)
    ra = get_result(test_client, id_a)
    rb = get_result(test_client, id_b)
    assert ra.status_code == 200, ra.text
    assert rb.status_code == 200, rb.text
    sa, sb = ra.json(), rb.json()
    assert sa["job_id"] == id_a
    assert sb["job_id"] == id_b
    assert sa["input_sha256"] != sb["input_sha256"]
    assert sa["value"] != sb["value"] or sa["sample"]["received"] != sb["sample"]["received"]


def test_candidate_cols_empty_is_4xx_not_all_columns():
    test_client = client()
    resp = post_job(
        test_client,
        file_bytes=ptbr_csv_bytes(),
        spec=request_spec(candidate_cols=[]),
        subject=subject_raw(),
    )
    assert resp.status_code == 400, resp.text
    assert resp.status_code != 200
    assert "CANDIDATE_COLS_EMPTY" in issue_codes(resp)
    message = " ".join(str(i.get("message", "")).lower() for i in issues_of(resp))
    assert "never all" in message or "no authorized" in message
    assert resp.status_code != 200


def test_preview_does_not_start_search():
    test_client = client()
    resp = test_client.post(
        "/preview",
        files={"file": ("mercado.csv", ptbr_csv_bytes(), "text/csv")},
        data={"request_json": json.dumps(request_spec())},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("preview") is True
    assert body.get("search_invoked") is False
    assert body.get("fit_invoked") is False
    assert "job_id" not in body or body.get("state") != "running"


def test_compose_valuation_job_uses_real_ingest_and_search(isolated_c17_runtime):
    store = isolated_c17_runtime["job_store"]
    created = store.create(payload={"filename": "mercado.csv"})
    peers = production_peers()
    ctx = compose_valuation_job(
        job_id=created["job_id"],
        file_bytes=ptbr_csv_bytes(tag="COMPOSE"),
        filename="mercado.csv",
        request_spec=request_spec(),
        subject_raw=subject_raw(),
        project_id=None,
        peers=peers,
        job_store=store,
    )
    snap = ctx["snapshot"]
    assert snap["schema_version"] == "MP/1"
    assert snap["job_id"] == created["job_id"]
    assert finite_or_null(snap["value"]["point"])
    kinds = {name: kind for name, (kind, _ref) in ctx["peers_used"].items()}
    assert kinds["ingest_market"] == "real"
    assert kinds["search_models"] == "real"
    assert kinds["fit_dataset"] == "real"
    assert "simulator" not in kinds.values()
    loaded = store.get_snapshot(created["job_id"])
    assert loaded is not None
    assert loaded["job_id"] == snap["job_id"]
    assert current_code_sha()
