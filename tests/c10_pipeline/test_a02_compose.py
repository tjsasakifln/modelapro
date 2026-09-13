"""C10-A02: composed path preserves roles, subject, ledger, point, and split states."""

import inspect
import os

import pytest

from backend.worker import (
    CompositionError,
    compose_preview,
    compose_valuation_job,
    resolve_peers,
)
from tests.c10_pipeline.doubles import CallLog, LabeledJobStore, make_peers
from tests.c10_pipeline.fixtures import complete_request_spec, market_csv_bytes, subject_raw


def _source_of(mod) -> str:
    return inspect.getsource(mod)


def test_worker_has_no_hidden_legacy_parser():
    import backend.worker as worker_mod

    src = _source_of(worker_mod)
    assert "load_data(" not in src
    assert "find_best_model(" not in src
    assert "DataLoader(" not in src
    assert "OptimalCombinationFinder(" not in src


def test_roles_and_target_visible_before_cleaning():
    log = CallLog()
    peers = make_peers(log, point=123456.0)
    store = LabeledJobStore()
    created = store.create(payload={})
    spec = complete_request_spec()
    compose_valuation_job(
        job_id=created["job_id"],
        file_bytes=market_csv_bytes("A"),
        filename="m.csv",
        request_spec=spec,
        subject_raw=subject_raw("sul", 88.0),
        project_id=None,
        peers=peers,
        job_store=store,
    )
    assert log.names()[0] == "ingest_market"
    ingest = log.first("ingest_market")
    assert ingest["target_col"] == "preco"
    assert ingest["roles"]["preco"] == "target"
    assert ingest["roles"]["bairro"] == "predictor"
    assert ingest["roles"]["id"] == "identifier"
    assert "fit_dataset" in log.names()
    assert log.names().index("ingest_market") < log.names().index("fit_dataset")


def test_categorical_subject_and_sample_ledger_survive():
    log = CallLog()
    peers = make_peers(log, point=150000.0)
    store = LabeledJobStore()
    created = store.create(payload={})
    ctx = compose_valuation_job(
        job_id=created["job_id"],
        file_bytes=market_csv_bytes("A"),
        filename="m.csv",
        request_spec=complete_request_spec(),
        subject_raw=subject_raw("sul", 88.0),
        project_id=None,
        peers=peers,
        job_store=store,
    )
    transform = log.first("transform_subject")
    assert transform["subject_raw"]["bairro"] == "sul"
    snap = ctx["snapshot"]
    assert snap["provenance"]["sample_ledger_present"] is True
    assert snap["provenance"]["subject_categorical_survived"] is True
    assert snap["sample"]["used"] >= 1
    assert snap["sample"]["used_row_ids"]
    ledger = ctx["report_context"]["sample_ledger"]
    assert ledger["used_row_ids"]


def test_snapshot_point_is_evaluate_fitted_point_not_arbitration_midpoint():
    log = CallLog()
    peers = make_peers(log, point=150000.0)
    store = LabeledJobStore()
    created = store.create(payload={})
    ctx = compose_valuation_job(
        job_id=created["job_id"],
        file_bytes=market_csv_bytes("A"),
        filename="m.csv",
        request_spec=complete_request_spec(),
        subject_raw=subject_raw(),
        project_id=None,
        peers=peers,
        job_store=store,
    )
    snap = ctx["snapshot"]
    assert snap["value"]["point"] == 150000.0
    arb = snap["value"]["arbitration_interval"]
    midpoint = (arb["lower"] + arb["upper"]) / 2.0
    assert snap["value"]["point"] == 150000.0
    assert midpoint == pytest.approx(150000.0)
    # If freeze had rebuilt from a different band it would not equal the peer point.
    assert "evaluate_fitted" in log.names()
    assert snap["model"]["delivered_matches_used"] is True
    assert snap["model"]["used"]["candidate_id"] == snap["model"]["candidate_id"]
    assert snap["model"]["used"]["model_sha256"] == snap["model"]["model_sha256"]


def test_pdf_failure_preserves_calculated_snapshot():
    log = CallLog()
    peers = make_peers(log, point=150000.0, pdf_error=True)
    store = LabeledJobStore()
    created = store.create(payload={})
    job_id = created["job_id"]
    store.update_transition(job_id, "queued", "running")
    ctx = compose_valuation_job(
        job_id=job_id,
        file_bytes=market_csv_bytes("A"),
        filename="m.csv",
        request_spec=complete_request_spec(),
        subject_raw=subject_raw(),
        project_id=None,
        peers=peers,
        job_store=store,
    )
    snap = store.get_snapshot(job_id)
    assert snap is not None
    assert snap["value"]["point"] == 150000.0
    assert ctx["calculation_state"] == "succeeded"
    assert ctx["artifact_states"]["report.pdf"]["state"] == "failed"
    job = store.get(job_id)
    assert job["state"] == "succeeded"
    assert job["artifact_states"]["report.pdf"]["state"] == "failed"
    assert job["result_available"] is True


def test_ingest_failure_does_not_invoke_search_or_legacy_fallback():
    log = CallLog()
    peers = make_peers(log, ingest_error=True)
    store = LabeledJobStore()
    created = store.create(payload={})
    store.update_transition(created["job_id"], "queued", "running")
    with pytest.raises(CompositionError) as exc:
        compose_valuation_job(
            job_id=created["job_id"],
            file_bytes=market_csv_bytes("A"),
            filename="m.csv",
            request_spec=complete_request_spec(),
            subject_raw=subject_raw(),
            project_id=None,
            peers=peers,
            job_store=store,
        )
    assert any(i["code"] == "INGEST_FAIL" for i in exc.value.issues)
    assert "search_models" not in log.names()
    assert "fit_dataset" not in log.names()
    assert "evaluate_fitted" not in log.names()


def test_preview_does_not_search_or_fit():
    log = CallLog()
    peers = make_peers(log)
    result = compose_preview(
        file_bytes=market_csv_bytes("A"),
        filename="m.csv",
        request_spec=complete_request_spec(),
        subject_raw=subject_raw(),
        peers=peers,
    )
    assert result["preview"] is True
    assert result["search_invoked"] is False
    assert result["fit_invoked"] is False
    assert result["roles_applied"]["preco"] == "target"
    assert "search_models" not in log.names()
    assert "evaluate_fitted" not in log.names()
    assert "fit_dataset" not in log.names()
    assert "render_report" not in log.names()


def test_report_context_carries_dates_and_rows():
    log = CallLog()
    peers = make_peers(log)
    store = LabeledJobStore()
    created = store.create(payload={})
    store.update_transition(created["job_id"], "queued", "running")
    ctx = compose_valuation_job(
        job_id=created["job_id"],
        file_bytes=market_csv_bytes("A"),
        filename="m.csv",
        request_spec=complete_request_spec(),
        subject_raw=subject_raw(),
        project_id=None,
        peers=peers,
        job_store=store,
    )
    rc = ctx["report_context"]
    assert rc["reference_date"] == "2024-06-01"
    assert rc["inspection_date"] == "2024-06-15"
    assert rc["used_row_ids"]
    fp = ctx["frozen_project"]
    assert fp["schema_version"] == "MP/1"
    assert fp["request_spec"]["target_col"] == "preco"
    assert fp["feature_schema"]["version"] == "MP/1-test"
    assert "model_object" not in fp["model_state"]
    assert fp["model_state"]["model_sha256"] == "m" * 64


def test_production_resolve_peers_does_not_invent_unlabeled_standins():
    peers = resolve_peers()
    for name, fn in peers.items():
        if fn is None:
            continue
        assert getattr(fn, "contract_simulator", False) is False, name
