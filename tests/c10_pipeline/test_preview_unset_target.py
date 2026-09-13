"""Preview accepts unset target; jobs do not. Drives shipped POST /preview."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import app, bind_runtime, preview_peer_issues, preview_ready, reset_runtime
from backend.worker import peer_kind, resolve_peers
from modules.data_loader import ingest_market
from modules.result_contract import RequestSpecError, fill_preview_spec, validate_request_spec
from tests.c10_pipeline.doubles import CallLog, install_labeled_runtime, make_peers
from tests.c10_pipeline.fixtures import complete_request_spec, market_csv_bytes

XLSX = Path(__file__).parent / "fixtures" / "amostras_mercado_modelapro.xlsx"
EXPECTED_COLUMNS = [
    "id",
    "preco",
    "area",
    "dormitorios",
    "vagas",
    "banheiros",
    "fonte",
    "data_coleta",
    "endereco",
    "url",
]


def _frontend_draft(**overrides):
    spec = {
        "schema_version": "MP/1",
        "target_col": "",
        "candidate_cols": None,
        "roles": {},
        "units": {},
        "import_options": {"locale": "auto", "delimiter": None, "encoding": None},
        "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
        "outlier_policy": {"mode": "report_only", "reviewed_exclusions": []},
        "search_policy": {
            "mode": "default",
            "budget": None,
            "objective": "minimum_fundamentacao_grade",
            "seed": None,
        },
        "evaluation_policy": {
            "method": None,
            "partitions": None,
            "groups": None,
            "seed": None,
        },
        "reference_date": None,
        "inspection_date": None,
        "target_unit": "",
        "applicant": "",
        "purpose": "",
    }
    spec.update(overrides)
    return spec


def _post_preview(client, spec, file_bytes=None, filename="m.csv", content_type="text/csv"):
    payload = file_bytes if file_bytes is not None else market_csv_bytes("P")
    return client.post(
        "/preview",
        files={"file": (filename, payload, content_type)},
        data={"request_json": json.dumps(spec)},
    )


def test_fill_preview_spec_accepts_empty_and_null_target_without_inventing_preco():
    filled = fill_preview_spec(_frontend_draft())
    assert filled["target_col"] == ""
    assert filled["candidate_cols"] is None
    assert filled["target_unit"] == ""
    assert filled["reference_date"] is None
    assert "preco" not in (filled.get("roles") or {})
    assert filled["evaluation_policy"]["method"] == "none"

    filled_null = fill_preview_spec(_frontend_draft(target_col=None))
    assert filled_null["target_col"] == ""

    with pytest.raises(RequestSpecError) as exc:
        validate_request_spec(_frontend_draft())
    assert any(i["code"] == "MISSING_FIELD" for i in exc.value.issues)


def test_preview_empty_target_col_returns_200():
    reset_runtime()
    client = TestClient(app)
    resp = _post_preview(client, _frontend_draft(), XLSX.read_bytes(), "amostras_mercado_modelapro.xlsx")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["preview"] is True
    assert body["search_invoked"] is False
    assert body["fit_invoked"] is False
    assert body["project_mutated"] is False
    assert body["target_col"] == ""
    assert "PEER_UNAVAILABLE" not in {i.get("code") for i in body.get("issues") or []}


def test_preview_null_target_col_returns_200():
    reset_runtime()
    client = TestClient(app)
    resp = _post_preview(client, _frontend_draft(target_col=None), XLSX.read_bytes(), "amostras_mercado_modelapro.xlsx")
    assert resp.status_code == 200, resp.text
    assert resp.json()["preview"] is True
    assert resp.json()["target_col"] == ""


def test_preview_candidate_cols_null_accepted():
    reset_runtime()
    client = TestClient(app)
    spec = _frontend_draft(candidate_cols=None)
    resp = _post_preview(client, spec, XLSX.read_bytes(), "amostras_mercado_modelapro.xlsx")
    assert resp.status_code == 200, resp.text
    assert resp.json()["candidate_cols"] is None


def test_preview_does_not_call_search_fit_job_or_revision():
    log = CallLog()
    peers = make_peers(log)
    peers["ingest_market"] = ingest_market
    store, projects, runner, _log, _peers = install_labeled_runtime(peers=peers)
    client = TestClient(app)
    resp = _post_preview(client, _frontend_draft(), XLSX.read_bytes(), "amostras_mercado_modelapro.xlsx")
    assert resp.status_code == 200, resp.text
    names = log.names()
    assert "search_models" not in names
    assert "fit_dataset" not in names
    assert "fit_candidate" not in names
    assert runner.submitted == []
    assert store.jobs == {}
    assert projects.list() == []
    body = resp.json()
    assert body["search_invoked"] is False
    assert body["fit_invoked"] is False
    assert body["project_mutated"] is False


def test_real_xlsx_preview_has_64_rows_and_ten_columns():
    reset_runtime()
    client = TestClient(app)
    raw = XLSX.read_bytes()
    assert raw[:2] == b"PK"
    resp = _post_preview(
        client,
        _frontend_draft(),
        raw,
        "amostras_mercado_modelapro.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["preview"] is True
    assert body["sample"]["received"] == 64
    assert len(body["row_ledger"]) == 64
    columns = list(body["column_map"].keys())
    for name in EXPECTED_COLUMNS:
        assert name in columns, columns
        assert name in body["feature_schema"]["columns"]
    assert body["search_invoked"] is False
    assert body["fit_invoked"] is False
    assert body["project_mutated"] is False
    assert "preco" not in (body.get("roles_applied") or {})
    units = (body.get("feature_schema") or {}).get("target") or {}
    assert units.get("column") in ("", None)
    assert (units.get("unit") or "") == ""


def test_jobs_still_reject_empty_target():
    install_labeled_runtime()
    client = TestClient(app)
    resp = client.post(
        "/jobs",
        files={"file": ("m.csv", market_csv_bytes("J"), "text/csv")},
        data={"request_json": json.dumps(_frontend_draft())},
    )
    assert resp.status_code == 400, resp.text
    body = resp.json()
    issues = body.get("issues") or (body.get("detail") or {}).get("issues") or []
    assert any(i["code"] == "MISSING_FIELD" for i in issues)


def test_normal_init_registers_real_ingest_market():
    reset_runtime()
    peers = resolve_peers()
    fn = peers["ingest_market"]
    assert callable(fn)
    kind, ref = peer_kind(fn)
    assert kind == "real"
    assert ref == "modules.data_loader.ingest_market"
    assert preview_ready(peers) is True
    assert preview_peer_issues(peers) == []


def test_readiness_fails_closed_when_ingest_market_missing():
    reset_runtime()
    bind_runtime(peers={"ingest_market": None})
    client = TestClient(app)
    health = client.get("/health")
    ready = client.get("/ready")
    assert health.status_code == 503
    assert ready.status_code == 503
    for resp in (health, ready):
        body = resp.json()
        assert body["error"] == "ingest_market unavailable"
        assert any(i["code"] == "PEER_UNAVAILABLE" for i in body["issues"])
        assert "ingest_market" in (body["issues"][0].get("evidence") or {}).get("missing", [])
    preview = _post_preview(client, _frontend_draft(), XLSX.read_bytes(), "amostras_mercado_modelapro.xlsx")
    assert preview.status_code == 503
    assert any(i["code"] == "PEER_UNAVAILABLE" for i in preview.json()["issues"])
    reset_runtime()
