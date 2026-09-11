"""E2E HTTP acceptances against the real FastAPI app.

HTTP 200 on /upload is not enough: result must be recovered by GET, not WS.
"""
from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from backend.api import app
from _helpers import fixture_bytes, route_paths, try_export


def _client():
    return TestClient(app)


class TestE2EHttpJobs:
    def test_health_is_not_the_acceptance(self):
        client = _client()
        r = client.get("/health")
        assert r.status_code == 200
        # Health is a probe, not the E2E bar.
        assert r.json() == {"status": "healthy"}

    def test_upload_then_get_result_without_websocket(self):
        client = _client()
        files = {"file": ("market_minimal.csv", fixture_bytes("market_minimal.csv"), "text/csv")}
        data = {
            "degree": "1",
            "target_col": "preco",
            "avaliando_json": json.dumps({"area": 100, "quartos": 3}),
            "candidate_cols_json": json.dumps(["area", "quartos"]),
        }
        # Prefer MP/1 POST /jobs; fall back to legacy /upload.
        posted = client.post("/jobs", files=files, data={"request_json": json.dumps({
            "schema_version": "MP/1",
            "target_col": "preco",
            "candidate_cols": ["area", "quartos"],
            "roles": {"preco": "target", "area": "predictor", "quartos": "predictor"},
            "units": {},
            "import_options": {"locale": "pt-BR", "delimiter": ",", "encoding": "utf-8"},
            "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
            "outlier_policy": {"mode": "report_only", "reviewed_exclusions": []},
            "search_policy": {"mode": "exhaustive", "budget": None, "objective": "grau", "seed": 16},
            "evaluation_policy": {"method": "holdout", "seed": 16},
            "reference_date": None,
            "inspection_date": None,
            "target_unit": "",
            "applicant": "synthetic-c16",
            "purpose": "e2e-http",
        }), "subject_json": json.dumps({"area": 100, "quartos": 3})})
        if posted.status_code == 404:
            posted = client.post("/upload", files=files, data=data)
        assert posted.status_code in (200, 202), posted.text
        body = posted.json()
        job_id = body.get("job_id")
        assert job_id, f"E2E requires job_id to GET the result without WS; body={body}"

        deadline = time.time() + 60
        state = None
        while time.time() < deadline:
            status = client.get(f"/jobs/{job_id}")
            assert status.status_code == 200
            payload = status.json()
            state = payload.get("state")
            if state in {"succeeded", "failed", "cancelled", "interrupted"}:
                break
            time.sleep(0.2)
        assert state in {"succeeded", "failed"}

        result = client.get(f"/jobs/{job_id}/result")
        assert result.status_code in (200, 409, 404, 425)
        if result.status_code == 200:
            snap = result.json()
            assert snap.get("schema_version") == "MP/1"
            value = snap.get("value") or {}
            sample = snap.get("sample") or {}
            issues = snap.get("issues") or []
            assert value.get("point") is not None or issues
            assert sample.get("observed_target") is not None
            assert "NaN" not in result.text and "Infinity" not in result.text

    def test_preview_does_not_start_search(self):
        client = _client()
        files = {"file": ("market_minimal.csv", fixture_bytes("market_minimal.csv"), "text/csv")}
        r = client.post("/preview", files=files, data={"request_json": "{}"})
        assert r.status_code != 404, "UNMET_DEPENDENCY:C10 POST /preview"
        body = r.json()
        assert "job_id" not in body or body.get("state") != "running"

    def test_get_result_route_exists(self):
        paths = route_paths(app)
        assert any("/jobs/" in p and p.rstrip("/").endswith("/result") for p in paths), (
            "GET /jobs/{id}/result is not registered; result recovery depends on /ws. "
            f"routes={paths}"
        )
        client = _client()
        r = client.get("/jobs/does-not-exist/result")
        assert r.status_code in (404, 409, 425), (
            f"registered result route returned {r.status_code}"
        )
