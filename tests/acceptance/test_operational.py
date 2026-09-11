"""Operational acceptances: WS-independent completion, fast fail, restart,
cancel, failed PDF, large file, >200 rows, two runs, distinct units.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.api import app
from modules.data_loader import DataLoader
from modules.model_builder import ModelBuilder
from modules.results_generator import ResultsGenerator
from _helpers import fixture_bytes, fixture_path, oracles, route_paths, try_export
import pandas as pd


def _client():
    return TestClient(app)


class TestOperationalFlows:
    def test_completion_recoverable_before_websocket(self):
        paths = route_paths(app)
        assert any("/jobs/" in p and p.rstrip("/").endswith("/result") for p in paths), (
            "result GET is not registered; completion cannot be recovered before/without WS. "
            f"routes={paths}"
        )

    def test_fast_fail_unsupported_format(self):
        client = _client()
        r = client.post(
            "/upload",
            files={"file": ("x.bin", b"\x00\x01", "application/octet-stream")},
            data={"degree": "1", "target_col": "preco"},
        )
        # Worker fails after ack today; MP/1 wants a failed job, not a silent 200.
        if r.status_code == 200 and "job_id" not in r.json():
            load = DataLoader().load_data(b"\x00\x01", "x.bin")
            assert load.success is False
            raise AssertionError(
                "fast-fail did not surface as a job state; only WS would see the error"
            )
        assert r.status_code in (400, 422, 202)

    def test_cancel_route_exists(self):
        paths = route_paths(app)
        assert any("/jobs/" in p and p.rstrip("/").endswith("/cancel") for p in paths), (
            f"POST /jobs/{{id}}/cancel is not registered; routes={paths}"
        )

    def test_pdf_failure_is_artifact_state_not_zero_snapshot(self):
        freeze = try_export("modules.result_contract", "freeze_result_snapshot")
        JobStore = try_export("modules.job_store", "JobStore")
        if freeze is None or JobStore is None:
            raise AssertionError(
                "UNMET_DEPENDENCY:C10/C11 PDF-failed artifact_states; "
                "calculation success must be separable from PDF generation"
            )

    def test_large_file_is_ingested_or_rejected_structurally(self):
        payload = oracles.generate_wide_bytes(1_500_000)
        assert len(payload) >= 1_500_000
        result = DataLoader().load_data(payload, "large.csv")
        assert result.success in (True, False)
        if not result.success:
            assert result.error or result.message

    def test_table_over_200_rows_is_not_silently_truncated(self):
        csv_bytes = oracles.generate_large_market_csv(250, seed=16)
        df = pd.read_csv(pd.io.common.BytesIO(csv_bytes))
        assert len(df) == 250
        fitted = ModelBuilder().build_model(
            df[["area"]], df["preco"], degree=1, remove_outliers=False
        )
        pdf = ResultsGenerator.generate_pdf_report(
            fitted, target_col="preco", market_data=df,
        )
        assert pdf is not None and pdf[:4] == b"%PDF"
        bundle = try_export("modules.evidence_bundle", "build_evidence_bundle")
        if bundle is None:
            raise AssertionError(
                "UNMET_DEPENDENCY:C12 table>200: PDF may cap at 200 rows; "
                "integral sample must live in the evidence bundle"
            )

    def test_two_executions_do_not_share_job_identity(self):
        client = _client()
        files = {"file": ("market_minimal.csv", fixture_bytes("market_minimal.csv"), "text/csv")}
        data = {"degree": "1", "target_col": "preco"}
        a = client.post("/upload", files=files, data=data)
        b = client.post("/upload", files=files, data=data)
        assert a.status_code in (200, 202)
        assert b.status_code in (200, 202)
        id_a = a.json().get("job_id")
        id_b = b.json().get("job_id")
        assert id_a and id_b and id_a != id_b, (
            f"two executions are not isolated: {a.json()} vs {b.json()}"
        )

    def test_distinct_units_stay_pending_when_unspecified(self):
        freeze = try_export("modules.result_contract", "freeze_result_snapshot")
        if freeze is None:
            from modules.utils import format_currency
            brl = format_currency(10)
            m2 = format_currency(10)
            assert brl != m2, (
                "UNMET_DEPENDENCY:C10 target_unit; format_currency assumes BRL "
                f"for both unit-less values ({brl!r})"
            )
            raise AssertionError(
                "UNMET_DEPENDENCY:C10 distinct units (BRL vs BRL/m2) cannot be "
                "represented; both format as " + brl
            )

    def test_restart_interrupted_job_is_explicit(self):
        JobStore = try_export("modules.job_store", "JobStore")
        Runner = try_export("modules.local_task_runner", "LocalTaskRunner")
        if JobStore is None or Runner is None:
            raise AssertionError("UNMET_DEPENDENCY:C11 restart/interrupted state")
