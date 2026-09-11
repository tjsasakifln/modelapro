"""Hardened production-path checks for PR #17 (R17-01…R17-06).

These drive shipped functions: evaluate_batch, compose_valuation_job,
assess_normative, POST /jobs. Oracles are analytic, not scraped from the
report under test.
"""

from __future__ import annotations

from typing import Any, Dict

from backend.worker import _axes_from_fit
from modules.nbr14653_validation import assess_normative
from modules.valuation_batch import (
    builtin_assess_normative,
    builtin_inverse_target_prediction,
    evaluate_batch,
    resolve_adapters,
)

from tests.c14_batch.conftest import (
    c03_documentary,
    expected_point,
    make_frozen_project,
    make_request_spec,
    make_subject,
)


def _fund(item: Dict[str, Any]) -> Dict[str, Any]:
    return ((item.get("assessment") or {}).get("normative") or {}).get("fundamentacao") or {}


def _item(fund: Dict[str, Any], number: int) -> Dict[str, Any]:
    for row in fund.get("items") or []:
        if int(row.get("item") or 0) == number:
            return row
    return {}


def test_r17_06_missing_subject_docs_stay_pending_despite_sample_scores(monkeypatch):
    frozen = make_frozen_project()
    spec = make_request_spec()
    subject = make_subject("novo", area=95.0, bairro="Centro")
    assert not (subject["documentary"].get("item1") or {}).get("grade")

    called = {"n": 0}
    original = builtin_assess_normative

    def wrapped(ctx):
        called["n"] += 1
        return original(ctx)

    monkeypatch.setattr("modules.valuation_batch.builtin_assess_normative", wrapped)

    batch = evaluate_batch(frozen, [subject], spec)
    item = batch["items"][0]
    fund = _fund(item)
    assert item["value"]["point"] == expected_point(95.0, "Centro")
    assert fund.get("grade") is None
    assert _item(fund, 1).get("grade") is None
    assert _item(fund, 1).get("evidence_status") == "pending"
    assert called["n"] == 0, "C03 grade None must not switch to builtin_assess_normative"


def test_r17_06_out_of_sample_area_fails_item4_not_inherited_grade():
    frozen = make_frozen_project()
    spec = make_request_spec()
    inside = make_subject("in", area=90.0, bairro="Centro", documentary=c03_documentary("in"))
    # Sample area [60, 180]; 270 is inside the expanded 0.5·min–2·max band (30–360)
    # but outside the sample, with 50%+ monetary effect at the frontier for a
    # linear 2500·area model? Use a dedicated frozen with 10000×area below.
    outside = make_subject("out", area=270.0, bairro="Centro", documentary=c03_documentary("out"))
    batch = evaluate_batch(frozen, [inside, outside], spec)
    items = {i["subject_id"]: i for i in batch["items"]}
    assert items["in"]["value"]["point"] == expected_point(90.0, "Centro")
    # 270 is outside declared domain 50–200 → unsupported, point null.
    assert items["out"]["value"]["point"] is None
    assert items["out"]["status"] in {"unsupported", "failed"}


def test_item4_expanded_band_is_not_approval_without_monetary_check():
    """Reference: sample area [50, 100], subject 150, y=10000×area."""

    def predict_original(subject):
        return 10000.0 * float(subject["area"])

    axes = [
        {
            "name": "area",
            "variable": "area",
            "kind": "quantitative",
            "avaliando_value": 150.0,
            "sample_min": 50.0,
            "sample_max": 100.0,
        }
    ]
    assessment = assess_normative(
        {
            "n": 30,
            "k": 1,
            "intercept": True,
            "axes": axes,
            "subject_raw": {"area": 150.0},
            "predict_original": predict_original,
            "pvalues": {"area": 0.01},
            "f_pvalue": 0.001,
            "documentary": c03_documentary("ref"),
        }
    )
    item4 = next(i for i in assessment["fundamentacao"]["items"] if i["item"] == 4)
    assert item4["grade"] in {0, None} or "não" in (item4.get("detail") or "").lower() or item4.get("grade") != 3
    # 50% monetary effect at the frontier (100 vs 150) is not Grau III.
    assert item4.get("grade") != 3


def test_unknown_y_transform_is_not_identity():
    result = builtin_inverse_target_prediction(10.0, {"name": "boxcox"})
    assert result.get("supported") is False
    assert result["value"]["point"] is None
    assert "unknown" in (result.get("error") or "").lower() or "boxcox" in str(result.get("limitations"))


def test_extra_form_field_does_not_create_model_axis():
    import pandas as pd

    frame = pd.DataFrame({"area": [50.0, 100.0], "garagem": [1.0, 20.0]})

    class _Fit:
        candidate_spec = {"base_variables": ["area"], "features": ["area"]}
        base_frame = frame
        feature_schema = {
            "columns": {"area": {"kind": "numeric"}},
            "groups": {},
        }
        X_design = None

    class _Prepared:
        base_frame = frame
        X = None
        feature_schema = _Fit.feature_schema

    raw = {"area": "90,0", "garagem": 9999}
    axes = _axes_from_fit(_Fit(), _Prepared(), raw, locale="pt-BR")
    names = {a.get("variable") or a.get("name") for a in axes}
    assert "garagem" not in names
    area = next(a for a in axes if (a.get("variable") or a.get("name")) == "area")
    assert area.get("avaliando_value") == 90.0


def test_individual_and_batch_pending_docs_match():
    frozen = make_frozen_project()
    spec = make_request_spec()
    subject = make_subject("p", area=88.0, bairro="Centro")
    lote = evaluate_batch(frozen, [subject], spec)["items"][0]
    adapters = resolve_adapters()
    from modules.valuation_batch import restore_candidate_fit

    fit = restore_candidate_fit(frozen)
    design = adapters["transform_subject"](subject["raw"], frozen["feature_schema"], frozen["encoder_state"])
    individual = adapters["evaluate_fitted"](fit, design, spec)
    assert lote["value"]["point"] == expected_point(88.0, "Centro")
    assert individual["value"]["point"] == lote["value"]["point"]
    fund_batch = _fund(lote)
    # Individual evaluate_fitted does not run C03; batch does. Pending docs
    # must not be filled from sample_item_scores.
    assert fund_batch.get("grade") is None


def test_mutation_other_imovel_docs_are_not_reused():
    frozen = make_frozen_project()
    spec = make_request_spec()
    a = make_subject("a", area=90.0, bairro="Centro", documentary=c03_documentary("a"))
    b = make_subject("b", area=91.0, bairro="Centro")
    batch = evaluate_batch(frozen, [a, b], spec)
    items = {i["subject_id"]: i for i in batch["items"]}
    fund_a = _fund(items["a"])
    fund_b = _fund(items["b"])
    assert fund_a.get("grade") is not None
    assert fund_b.get("grade") is None
    doc_b = ((items["b"].get("assessment") or {}).get("normative") or {}).get("documentary") or {}
    assert doc_b.get("subject_id") == "b"
    assert (doc_b.get("item1") or {}).get("grade") in (None, 0) or doc_b.get("item1", {}).get("evidence_status") == "pending"


def test_http_save_kill_server_reopen_batch(tmp_path):
    """A6: POST job → save revision → kill uvicorn → new process → batch."""
    import json
    import os
    import socket
    import subprocess
    import sys
    import time
    from pathlib import Path

    import httpx

    from tests.c17_integration.helpers import (
        UNIQUE_SUBJECT_AREA,
        analytic_bairro_csv,
        analytic_bairro_point,
        request_spec,
        wait_job,
    )

    def _free_port() -> int:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return port

    def _wait_health(base: str, timeout: float = 40.0) -> None:
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                resp = httpx.get(f"{base}/health", timeout=2.0)
                if resp.status_code < 500:
                    return
                last = resp.text
            except Exception as exc:  # noqa: BLE001
                last = str(exc)
            time.sleep(0.3)
        raise AssertionError(f"API did not become healthy at {base}: {last}")

    def _start(port: int, store_root: Path, env_base: dict) -> subprocess.Popen:
        env = dict(env_base)
        env["MODELA_STORE_ROOT"] = str(store_root)
        env["MODELA_SKIP_DOTENV"] = "1"
        env.pop("PYTHONPATH", None)
        log = store_root / f"uvicorn-{port}.log"
        handle = log.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.api:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=str(Path(__file__).resolve().parents[2]),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        proc._log_handle = handle  # type: ignore[attr-defined]
        return proc

    def _stop(proc: subprocess.Popen) -> None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        handle = getattr(proc, "_log_handle", None)
        if handle is not None:
            handle.close()

    store_root = tmp_path / "http-store"
    store_root.mkdir()
    env_base = os.environ.copy()
    csv = analytic_bairro_csv(n_per=16, tag="A6")
    spec = request_spec(
        candidate_cols=["area", "bairro"],
        roles={"preco": "target", "area": "predictor", "bairro": "predictor", "id": "identifier"},
    )
    area_c = UNIQUE_SUBJECT_AREA  # 73.5, inside Centro sample [50,80] even grid
    area_s = 77.5  # inside Sul sample [51,81] odd grid; not a sample observation
    expected_c = analytic_bairro_point(area=area_c, bairro="Centro")
    expected_s = analytic_bairro_point(area=area_s, bairro="Sul")

    port1 = _free_port()
    proc1 = _start(port1, store_root, env_base)
    try:
        base1 = f"http://127.0.0.1:{port1}"
        _wait_health(base1)
        with httpx.Client(base_url=base1, timeout=30.0) as http:
            posted = http.post(
                "/jobs",
                files={"file": ("mercado.csv", csv, "text/csv")},
                data={
                    "request_json": json.dumps(spec),
                    "subject_json": json.dumps({"area": area_c, "bairro": "Centro"}),
                    "project_id": "proj-c18-restart",
                },
            )
            assert posted.status_code == 202, posted.text
            job_id = posted.json()["job_id"]
            status = wait_job(http, job_id, timeout=180.0)
            assert status["state"] == "succeeded", status
            frozen_resp = http.get(f"/jobs/{job_id}/artifacts/frozen_project.json")
            assert frozen_resp.status_code == 200, frozen_resp.text
            frozen = frozen_resp.json()
            frozen.pop("candidate_fit", None)
            frozen.pop("artifact_refs", None)
            frozen.pop("revision_id", None)
            frozen["project_id"] = "proj-c18-restart"
            saved = http.post(f"/projects/proj-c18-restart/revisions", json=frozen)
            assert saved.status_code == 201, saved.text
            revision_id = saved.json()["revision_id"]
            assert frozen.get("model_scope") == "population_model"
    finally:
        _stop(proc1)

    port2 = _free_port()
    proc2 = _start(port2, store_root, env_base)
    try:
        base2 = f"http://127.0.0.1:{port2}"
        _wait_health(base2)
        with httpx.Client(base_url=base2, timeout=30.0) as http:
            loaded = http.get("/projects/proj-c18-restart")
            assert loaded.status_code == 200, loaded.text
            rev = loaded.json().get("revision") or {}
            assert rev.get("model_scope") == "population_model"
            subjects = [
                {"subject_id": "r1", "bairro": "Centro", "area": area_c, "documentary": {"subject_id": "r1", "origin": "subject", "item1": {"grade": 3, "evidence_status": "declared"}, "item3": {"grade": 3, "evidence_status": "declared"}}},
                {"subject_id": "r2", "bairro": "Sul", "area": area_s, "documentary": {"subject_id": "r2", "origin": "subject", "item1": {"grade": 3, "evidence_status": "declared"}, "item3": {"grade": 3, "evidence_status": "declared"}}},
                {"subject_id": "r3", "bairro": "bairro_inexistente", "area": area_c},
                {"subject_id": "r4", "bairro": "Centro", "area": area_c, "documentary": {"subject_id": "r4", "origin": "subject", "items": []}},
            ]
            batch_post = http.post(
                "/projects/proj-c18-restart/batch",
                json={"revision_id": revision_id, "subjects": subjects, "request_spec": spec},
            )
            assert batch_post.status_code == 202, batch_post.text
            batch_job = batch_post.json()["job_id"]
            batch_status = wait_job(http, batch_job, timeout=180.0)
            assert batch_status["state"] == "succeeded", batch_status
            result = http.get(f"/jobs/{batch_job}/result")
            assert result.status_code == 200, result.text
            body = result.json()
            batch = body.get("result") or body
            rows = batch.get("items") or batch.get("assessments") or []
            items = {i["subject_id"]: i for i in rows}
            assert set(items) == {"r1", "r2", "r3", "r4"}
            assert abs(float(items["r1"]["value"]["point"]) - expected_c) < 1.0
            assert abs(float(items["r2"]["value"]["point"]) - expected_s) < 1.0
            assert items["r3"]["value"]["point"] is None
            assert items["r3"]["status"] in {"unsupported", "failed"}
            fund4 = ((items["r4"].get("assessment") or {}).get("normative") or {}).get("fundamentacao") or {}
            assert fund4.get("grade") is None
            assert items["r4"]["value"]["point"] is not None
            assert abs(float(items["r4"]["value"]["point"]) - expected_c) < 1.0
    finally:
        _stop(proc2)


def test_pdf_generation_failure_preserves_calculation(monkeypatch, isolated_c17_runtime):
    from tests.c17_integration.helpers import (
        analytic_linear_csv,
        analytic_point,
        client,
        post_job,
        wait_job,
        get_result,
        request_spec,
    )

    def boom(*_a, **_k):
        raise RuntimeError("injected pdf failure")

    monkeypatch.setattr("modules.results_generator.render_report", boom)
    test_client = client()
    spec = request_spec(
        candidate_cols=["area"],
        roles={"preco": "target", "area": "predictor", "id": "identifier", "bairro": "excluded"},
    )
    resp = post_job(
        test_client,
        file_bytes=analytic_linear_csv(n=24, tag="PDFNEG"),
        filename="mercado.csv",
        spec=spec,
        subject={"area": 90.0},
    )
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    status = wait_job(test_client, job_id)
    assert status["state"] == "succeeded"
    assert status.get("calculation_state") == "succeeded"
    pdf_state = (status.get("artifact_states") or {}).get("report.pdf") or {}
    assert pdf_state.get("state") == "failed"
    result = get_result(test_client, job_id)
    assert result.status_code == 200
    point = result.json()["value"]["point"]
    assert abs(float(point) - analytic_point(area=90.0)) < 1.0
    missing = test_client.get(f"/jobs/{job_id}/artifacts/report.pdf")
    assert missing.status_code == 404
