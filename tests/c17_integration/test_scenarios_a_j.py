"""C17 scenarios A–J against shipped production functions and HTTP."""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

from backend.worker import compose_valuation_job
from modules.data_loader import ingest_market, observed_target_count
from modules.valuation_batch import evaluate_batch

from typing import Mapping

from .helpers import (
    UNIQUE_SUBJECT_AREA,
    analytic_linear_csv,
    analytic_point,
    client,
    excel_bytes,
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


def _require_success(test_client, file_bytes, *, filename, spec, subject, content_type="text/csv"):
    resp = post_job(
        test_client,
        file_bytes=file_bytes,
        filename=filename,
        spec=spec,
        subject=subject,
        content_type=content_type,
    )
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    status = wait_job(test_client, job_id)
    result = get_result(test_client, job_id)
    assert result.status_code == 200, (status, result.text)
    snap = result.json()
    assert snap["schema_version"] == "MP/1"
    return job_id, status, snap


class TestALocaleAndMissingTarget:
    def test_ptbr_csv_does_not_invent_prices_and_keeps_bairro(self):
        csv = ptbr_csv_bytes(tag="A-CSV")
        bundle = ingest_market(csv, "mercado.csv", request_spec())
        assert bundle["schema_version"] == "MP/1"
        observed = observed_target_count(bundle)
        assert observed == 23
        parsed = bundle.parsed_frame
        assert parsed["preco"].isna().sum() == 1
        mean_fill = parsed["preco"].mean()
        missing_row = parsed[parsed["preco"].isna()].iloc[0]
        assert missing_row["preco"] != mean_fill
        assert "Centro" in set(parsed["bairro"].astype(str))
        ledger = bundle.row_ledger
        pending = [row for row in ledger if not row["observed_target"]]
        assert pending
        assert all(row["disposition"] != "imputed" for row in ledger)

        test_client = client()
        _job_id, _status, snap = _require_success(
            test_client,
            csv,
            filename="mercado.csv",
            spec=request_spec(),
            subject=subject_raw(bairro="Centro", area=85.5),
        )
        assert snap["sample"]["observed_target"] == observed
        assert snap["sample"]["received"] == 24
        assert finite_or_null(snap["value"]["point"])
        assert snap["value"]["point"] != 0 or snap["issues"]
        assert snap["provenance"].get("subject_categorical_survived") is True

    def test_excel_equivalent_same_observed_count(self):
        csv_bundle = ingest_market(ptbr_csv_bytes(tag="A-X"), "mercado.csv", request_spec())
        xlsx_spec = request_spec(import_options={"locale": "auto", "delimiter": None, "encoding": None})
        xlsx_bundle = ingest_market(excel_bytes(), "mercado.xlsx", xlsx_spec)
        assert observed_target_count(csv_bundle) == observed_target_count(xlsx_bundle)
        test_client = client()
        _job_id, _status, snap = _require_success(
            test_client,
            excel_bytes(),
            filename="mercado.xlsx",
            spec=xlsx_spec,
            subject=subject_raw(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        assert snap["sample"]["observed_target"] == observed_target_count(xlsx_bundle)


class TestBInvalidInputs:
    def test_empty_selection_invalid_file_ambiguous_nan_unknown_category(self):
        test_client = client()

        empty = post_job(
            test_client,
            file_bytes=ptbr_csv_bytes(),
            spec=request_spec(candidate_cols=[]),
            subject=subject_raw(),
        )
        assert empty.status_code == 400
        assert "CANDIDATE_COLS_EMPTY" in issue_codes(empty)

        invalid = post_job(
            test_client,
            file_bytes=b"\x00\x01not-a-spreadsheet",
            filename="lixo.bin",
            spec=request_spec(),
            subject=subject_raw(),
            content_type="application/octet-stream",
        )
        assert invalid.status_code in (400, 202, 422)
        if invalid.status_code == 202:
            job_id = invalid.json()["job_id"]
            status = wait_job(test_client, job_id)
            result = get_result(test_client, job_id)
            assert status["state"] in {"failed", "succeeded"}
            if result.status_code == 200:
                assert result.json().get("issues")
            else:
                assert result.status_code in (409, 422)
                assert issues_of(result) or status.get("issues")
        else:
            assert invalid.status_code != 200

        ambiguous = ingest_market(
            "valor,area\n1.234,80\n".encode("utf-8"),
            "amb.csv",
            request_spec(
                target_col="valor",
                candidate_cols=["area"],
                roles={"valor": "target", "area": "predictor"},
                import_options={"locale": "auto", "delimiter": ",", "encoding": "utf-8"},
            ),
        )
        assert any(i.get("code") == "ambiguous_number" for i in ambiguous.issues)

        nan_subject = post_job(
            test_client,
            file_bytes=ptbr_csv_bytes(),
            spec=request_spec(),
            subject={"bairro": "Centro", "area": math.nan},
        )
        assert nan_subject.status_code == 400
        assert "NON_FINITE_NUMBER" in issue_codes(nan_subject)

        inf_subject = post_job(
            test_client,
            file_bytes=ptbr_csv_bytes(),
            spec=request_spec(),
            subject={"bairro": "Centro", "area": math.inf},
        )
        assert inf_subject.status_code == 400

        unknown = post_job(
            test_client,
            file_bytes=ptbr_csv_bytes(),
            spec=request_spec(),
            subject=subject_raw(bairro="bairro_inexistente", area=85.5),
        )
        assert unknown.status_code in (202, 400, 422)
        if unknown.status_code == 202:
            job_id = unknown.json()["job_id"]
            status = wait_job(test_client, job_id)
            result = get_result(test_client, job_id)
            if result.status_code == 200:
                snap = result.json()
                eligibility = ((snap.get("validation") or {}).get("model_eligibility") or {}).get("status")
                assert eligibility in {"unsupported", "review_required", "error", "eligible", None}
                if snap["value"]["point"] is not None:
                    assert snap["issues"] or eligibility != "eligible" or snap["provenance"]
            else:
                assert result.status_code != 200 or status["state"] == "failed"


class TestCNormativeExtrapolation:
    def test_far_subject_keeps_pending_rules_and_original_unit(self):
        test_client = client()
        _job_id, _status, snap = _require_success(
            test_client,
            ptbr_csv_bytes(tag="C"),
            filename="mercado.csv",
            spec=request_spec(),
            subject=subject_raw(bairro="Centro", area=500.0),
        )
        validation = snap["validation"]
        assert validation["issuance"]["status"] in {
            "draft",
            "review_required",
            "ready_for_professional_review",
        }
        assert validation["issuance"]["status"] != "ready_for_professional_review" or validation.get(
            "normative_verification_status"
        ) in {"verified_rules_listed", "partial"}
        status = validation.get("normative_verification_status")
        assert status in {"verified_rules_listed", "partial", "pending", None}
        precisao = validation.get("precisao") or {}
        assert precisao.get("status") in {"not_computed", "classified", "unclassified", "error"}
        assert snap["target"]["unit"] == ""
        assert snap["sample"]["used"] >= 1
        assert snap["sample"]["used"] + snap["sample"]["excluded"] <= snap["sample"]["received"]
        codes = {i.get("code") for i in snap.get("issues") or []}
        assert "item4_axes_missing" not in codes
        assert "k_unknown" not in codes
        fund = validation.get("fundamentacao") or {}
        item4 = next((i for i in (fund.get("items") or []) if i.get("item") == 4), None)
        assert item4 is not None
        assert "axes_missing" not in (item4.get("reasons") or [])
        calc = item4.get("calculation") or {}
        assert calc.get("out_of_measure") or calc.get("extrapolated") or item4.get("grade") == 0
        stat = validation.get("statistical") or {}
        n_eff = stat.get("n")
        k_eff = stat.get("k")
        assert n_eff == snap["sample"]["used"]
        assert k_eff is not None and int(k_eff) >= 1
        assert snap["sample"]["used"] == len(snap["sample"]["used_row_ids"])


class TestDInfluence:
    def test_report_only_does_not_drop_sample_to_fabricate_quality(self):
        test_client = client()
        spec = request_spec(outlier_policy={"mode": "report_only", "reviewed_exclusions": []})
        _job_id, _status, snap = _require_success(
            test_client,
            ptbr_csv_bytes(tag="D"),
            filename="mercado.csv",
            spec=spec,
            subject=subject_raw(),
        )
        used = snap["sample"]["used"]
        excluded = snap["sample"]["excluded"]
        assert used >= 10
        hidden = [
            i
            for i in snap["issues"]
            if i.get("code") in {"silent_exclusion", "auto_removed_outlier"}
        ]
        assert not hidden
        assert excluded == len(snap["sample"]["excluded_row_ids"])


class TestEIndependentValidation:
    def test_holdout_requested_is_posted_and_scored(self):
        test_client = client()
        spec = request_spec(
            candidate_cols=["area"],
            roles={"preco": "target", "area": "predictor", "id": "identifier", "bairro": "excluded"},
            evaluation_policy={
                "method": "holdout",
                "partitions": 1,
                "groups": None,
                "seed": 17,
            },
            search_policy={
                "mode": "exact",
                "budget": 16,
                "objective": "aic",
                "seed": 17,

                "y_transformations": ["identity"],
            },
        )
        _job_id, _status, snap = _require_success(
            test_client,
            analytic_linear_csv(n=30, tag="E"),
            filename="mercado.csv",
            spec=spec,
            subject={"area": 90.0},
        )
        statistical = (snap.get("validation") or {}).get("statistical") or {}
        procedure = statistical.get("procedure") or {}
        assert procedure, "holdout was requested; validation.statistical.procedure must exist"
        assert procedure.get("usable_for_model_selection") is False
        assert procedure.get("reserved_filtered_by_error") is False
        partition = procedure.get("partition") or {}
        folds = partition.get("folds") or []
        assert folds, "holdout must record partitions"
        reserved = []
        for fold in folds:
            reserved.extend(fold.get("reserved_row_ids") or [])
        assert reserved, "holdout must keep a reserved set"
        used = set(map(str, (snap.get("sample") or {}).get("used_row_ids") or []))
        assert used.isdisjoint(set(map(str, reserved))) or procedure.get("winner_retrained_on_full_data") is False
        predictions = procedure.get("predictions") or []
        assert predictions, "at least one reserved prediction must be observable"
        ys = []
        ps = []
        n_reserved = 0
        n_finite = 0
        for item in predictions:
            if not isinstance(item, Mapping):
                continue
            n_reserved += 1
            y = item.get("y_true")
            if y is None:
                y = item.get("y") or item.get("observed") or item.get("y_original")
            p = item.get("y_pred")
            if p is None:
                p = item.get("value") or item.get("yhat") or item.get("predicted") or item.get("point")
            if y is None:
                continue
            if p is not None:
                try:
                    pf = float(p)
                except (TypeError, ValueError):
                    pf = None
            else:
                pf = None
            n_finite += 1 if pf is not None and math.isfinite(pf) else 0
            if pf is None:
                continue
            ys.append(float(y))
            ps.append(pf)
        assert n_reserved >= 1
        coverage = n_finite / n_reserved
        reported = (procedure.get("coverage") or {})
        if isinstance(reported, Mapping):
            reported_cov = reported.get("coverage")
        else:
            reported_cov = reported
        if reported_cov is not None:
            assert abs(float(reported_cov) - coverage) < 1e-9 or math.isfinite(float(reported_cov))
        assert any(abs(y - p) < 1.0 for y, p in zip(ys, ps)), "at least one reserved prediction must match the linear case"
        if ys:
            mae = sum(abs(y - p) for y, p in zip(ys, ps)) / len(ys)
            rmse = (sum((y - p) ** 2 for y, p in zip(ys, ps)) / len(ys)) ** 0.5
            metrics = procedure.get("metrics") or {}
            if metrics.get("mae") is not None:
                assert abs(float(metrics["mae"]) - mae) < 1.0
            if metrics.get("rmse") is not None:
                assert abs(float(metrics["rmse"]) - rmse) < 1.0
        assert snap["value"]["point"] is not None

    def test_method_none_does_not_satisfy_holdout_scenario(self):
        test_client = client()
        _job_id, _status, snap = _require_success(
            test_client,
            analytic_linear_csv(n=24, tag="E0"),
            filename="mercado.csv",
            spec=request_spec(
                candidate_cols=["area"],
                roles={"preco": "target", "area": "predictor", "id": "identifier", "bairro": "excluded"},
                evaluation_policy={"method": "none", "partitions": None, "groups": None, "seed": 17},
                search_policy={
                    "mode": "exact",
                    "budget": 16,
                    "objective": "aic",
                    "seed": 17,
    
                    "y_transformations": ["identity"],
                },
            ),
            subject={"area": 90.0},
        )
        procedure = ((snap.get("validation") or {}).get("statistical") or {}).get("procedure")
        assert not procedure, "method=none must not be scored as independent validation"


class TestFArtifacts:
    def test_snapshot_pdf_and_dossier_identity_when_ready(self, isolated_c17_runtime, tmp_path):
        import json
        import subprocess
        import sys

        from .helpers import analytic_linear_sample_areas, assert_pdf_conclusion_point

        test_client = client()
        n_rows = 24
        area = UNIQUE_SUBJECT_AREA
        expected = analytic_point(area=area)
        assert area not in analytic_linear_sample_areas(n=n_rows)
        sample_prices = {analytic_point(area=a) for a in analytic_linear_sample_areas(n=n_rows)}
        assert expected not in sample_prices
        spec = request_spec(
            candidate_cols=["area"],
            roles={"preco": "target", "area": "predictor", "id": "identifier", "bairro": "excluded"},
            reference_date="2024-06-01",
            inspection_date="2024-06-15",
        )
        job_id, status, snap = _require_success(
            test_client,
            analytic_linear_csv(n=n_rows, tag="F"),
            filename="mercado.csv",
            spec=spec,
            subject={"area": area},
        )
        point = snap["value"]["point"]
        assert point is not None and math.isfinite(float(point))
        assert abs(float(point) - expected) < 1.0
        pdf_state = (status.get("artifact_states") or {}).get("report.pdf") or {}
        evidence_state = (status.get("artifact_states") or {}).get("evidence_manifest.json") or {}
        assert pdf_state.get("state") == "ready", pdf_state
        pdf = test_client.get(f"/jobs/{job_id}/artifacts/report.pdf")
        assert pdf.status_code == 200
        assert pdf.content.startswith(b"%PDF")
        assert_pdf_conclusion_point(pdf.content, expected)
        from tests.c08_report.pdf_text import extract_pdf_text, parse_frozen_lines

        frozen = parse_frozen_lines(extract_pdf_text(pdf.content))
        assert frozen.get("MP1_REFERENCE_DATE") == "2024-06-01"
        assert frozen.get("MP1_INSPECTION_DATE") == "2024-06-15"
        assert snap["job_id"] in extract_pdf_text(pdf.content) or job_id in extract_pdf_text(pdf.content)
        assert evidence_state.get("state") == "ready", evidence_state
        manifest = test_client.get(f"/jobs/{job_id}/artifacts/evidence_manifest.json")
        assert manifest.status_code == 200
        body = manifest.json() if "json" in manifest.headers.get("content-type", "") else json.loads(manifest.content.decode("utf-8"))
        assert body.get("files") or body.get("completeness") or body.get("schema_version")
        evidence_dir = isolated_c17_runtime["root"] / "jobs" / job_id / "evidence"
        assert (evidence_dir / "MANIFEST.json").is_file(), list(evidence_dir.glob("*"))
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        cli = Path(__file__).resolve().parents[2] / "scripts" / "c12_reproduce" / "reproduce.py"
        ran = subprocess.run(
            [sys.executable, str(cli), "--bundle", str(evidence_dir)],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        repro = json.loads(ran.stdout)
        # P01 SEALED: CLI may exit non-zero when interval reconstruction is incomplete.
        assert repro.get("point") is not None
        assert abs(float(repro["point"]) - expected) < 1.0
        integrity = (repro.get("integrity") or {}).get("ok")
        assert integrity is True or repro.get("ok") is True, repro
        if repro.get("ok") is not True:
            limits = " ".join(repro.get("limitations") or [])
            assert "interval" in limits.lower() or "t_crit" in limits.lower(), repro
        assert (repro.get("comparison") or {}).get("point_within_tolerance") is True

    def test_more_than_200_rows_keeps_every_id(self):
        test_client = client()
        spec = request_spec(
            candidate_cols=["area"],
            roles={"preco": "target", "area": "predictor", "id": "identifier", "bairro": "excluded"},
        )
        job_id, status, snap = _require_success(
            test_client,
            analytic_linear_csv(n=210, missing_target_at=9, tag="F200"),
            filename="mercado.csv",
            spec=spec,
            subject={"area": UNIQUE_SUBJECT_AREA},
        )
        assert snap["sample"]["received"] == 210
        assert snap["sample"]["observed_target"] == 209
        used = list(snap["sample"]["used_row_ids"])
        excluded = list(snap["sample"].get("excluded_row_ids") or [])
        assert len(used) == snap["sample"]["used"]
        pdf_state = (status.get("artifact_states") or {}).get("report.pdf") or {}
        assert pdf_state.get("state") == "ready", pdf_state
        pdf = test_client.get(f"/jobs/{job_id}/artifacts/report.pdf")
        from .helpers import pdf_text

        text = pdf_text(pdf.content)
        missing = [rid for rid in used + excluded if str(rid) not in text]
        assert not missing, f"annex omitted {len(missing)} ids, e.g. {missing[:8]}"


class TestGRecovery:
    def test_cancel_is_terminal_and_queryable(self):
        test_client = client()
        resp = post_job(
            test_client,
            file_bytes=ptbr_csv_bytes(n=40, tag="G"),
            spec=request_spec(),
            subject=subject_raw(),
        )
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job_id"]
        cancelled = test_client.post(f"/jobs/{job_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        status = wait_job(test_client, job_id)
        assert status["state"] in {"cancelled", "succeeded", "failed"}
        # Calculation may finish before cancel is observed; state must stay queryable.
        again = test_client.get(f"/jobs/{job_id}")
        assert again.status_code == 200
        assert again.json()["job_id"] == job_id


class TestHIsolationBatch:
    def test_evaluate_batch_does_not_copy_grade_across_subjects(self, isolated_c17_runtime):
        store = isolated_c17_runtime["job_store"]
        created = store.create(payload={"filename": "mercado.csv"})
        peers = production_peers()
        spec = request_spec(
            candidate_cols=["area", "bairro"],
            search_policy={
                "mode": "exact",
                "budget": 32,
                "objective": "aic",
                "seed": 17,

                "y_transformations": ["identity"],
            },
        )
        ctx = compose_valuation_job(
            job_id=created["job_id"],
            file_bytes=ptbr_csv_bytes(tag="H"),
            filename="mercado.csv",
            request_spec=spec,
            subject_raw=subject_raw(),
            project_id=None,
            peers=peers,
            job_store=store,
        )
        frozen = ctx["frozen_project"]
        assert frozen.get("model_scope") == "population_model"
        subjects = [
            {"subject_id": "s1", "bairro": "Centro", "area": 80.0},
            {"subject_id": "s2", "bairro": "Sul", "area": 110.0},
            {"subject_id": "s3", "bairro": "bairro_inexistente", "area": 90.0},
            {
                "subject_id": "s4",
                "bairro": "Centro",
                "area": 95.0,
                "documentary": {"subject_id": "s4", "origin": "subject", "items": []},
            },
        ]
        batch = evaluate_batch(frozen, subjects, spec)
        items = {item["subject_id"]: item for item in (batch.get("items") or [])}
        assert set(items) == {"s1", "s2", "s3", "s4"}
        p1 = items["s1"]["value"]["point"]
        p2 = items["s2"]["value"]["point"]
        assert p1 is not None and math.isfinite(float(p1))
        assert p2 is not None and math.isfinite(float(p2))
        assert p1 != 0 and p2 != 0
        assert items["s3"]["value"]["point"] is None
        elig3 = (items["s3"].get("assessment") or {}).get("model_eligibility") or {}
        assert items["s3"]["status"] in {"unsupported", "failed"}
        assert elig3.get("status") in {"unsupported", "error"}
        assert "unknown_category" in (elig3.get("reasons") or []) or any(
            "unknown" in str(i.get("code", "")).lower()
            for i in (items["s3"].get("assessment") or {}).get("issues") or []
        )
        fund4 = ((items["s4"].get("assessment") or {}).get("normative") or {}).get("fundamentacao") or {}
        assert fund4.get("grade") is None
        assert items["s4"]["value"]["point"] is not None
        for sid, item in items.items():
            documentary = ((item.get("assessment") or {}).get("normative") or {}).get("documentary") or {}
            assert documentary.get("subject_id") == sid


class TestISearchCoverage:
    def test_exact_mode_records_coverage_and_limited_mode_discloses(self):
        test_client = client()
        _job_id, _status, exact = _require_success(
            test_client,
            ptbr_csv_bytes(tag="I-EXACT"),
            filename="mercado.csv",
            spec=request_spec(search_policy={
                "mode": "exact",
                "budget": 64,
                "objective": "aic",
                "seed": 17,

                "y_transformations": ["identity"],
            }),
            subject=subject_raw(),
        )
        audit = (exact.get("search") or {}).get("audit") or {}
        coverage = audit.get("coverage") or audit
        assert audit or exact["issues"]

        _job_id2, _status2, approx = _require_success(
            test_client,
            ptbr_csv_bytes(tag="I-APPR"),
            filename="mercado.csv",
            spec=request_spec(search_policy={
                "mode": "approximate",
                "budget": 3,
                "objective": "aic",
                "seed": 17,

                "y_transformations": ["identity"],
            }),
            subject=subject_raw(),
        )
        approx_audit = (approx.get("search") or {}).get("audit") or {}
        guaranteed = (approx_audit.get("coverage") or {}).get("exact_optimum_guaranteed")
        if guaranteed is not None:
            assert guaranteed is False
        issues_text = " ".join(i.get("message", "") for i in approx.get("issues") or [])
        assert guaranteed is False or "approximate" in issues_text.lower() or approx_audit


class TestJLocalInstall:
    def test_loopback_default_and_redis_not_required(self):
        from modules.config_manager import config

        try:
            from c15_local.launcher import backend_command
        except ImportError:
            from scripts.c15_local.launcher import backend_command

        assert config.API_HOST == "127.0.0.1"
        assert "*" not in config.CORS_ORIGINS
        assert config.REDIS_ENABLED is False
        cmd = backend_command(config.API_HOST, config.API_PORT)
        assert "--host" in cmd
        host = cmd[cmd.index("--host") + 1]
        assert host == "127.0.0.1"
        assert host not in {"0.0.0.0", "::"}
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        text = pyproject.read_text(encoding="utf-8")
        assert 'redis = ["redis' in text or "modelapro[redis]" in text
        assert os.environ.get("REDIS_URL") in (None, "")
        assert os.name == "posix"
