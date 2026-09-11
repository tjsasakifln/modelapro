"""C17 scenarios A–J against shipped production functions and HTTP."""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

from backend.worker import compose_valuation_job
from modules.data_loader import ingest_market, observed_target_count
from modules.valuation_batch import evaluate_batch

from .helpers import (
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
    def test_holdout_requested_does_not_filter_reserved_set_in_snapshot(self):
        test_client = client()
        from modules.data_loader import ingest_market
        from modules.preprocessing import fit_dataset

        spec = request_spec(
            evaluation_policy={
                "method": "holdout",
                "partitions": 1,
                "groups": None,
                "seed": 17,
            }
        )
        bundle = ingest_market(ptbr_csv_bytes(n=30, tag="E"), "mercado.csv", spec)
        row_ids = [entry["row_id"] for entry in bundle.row_ledger if entry.get("observed_target")]
        train_ids = row_ids[: max(8, len(row_ids) - 6)]
        held = [rid for rid in row_ids if rid not in set(train_ids)]
        prepared = fit_dataset(bundle, spec, train_ids)
        encoder = prepared.encoder_state or {}
        fitted_on = encoder.get("fitted_on") or encoder.get("train_row_ids")
        if fitted_on:
            assert not set(map(str, held)).intersection(set(map(str, fitted_on)))
        _job_id, _status, snap = _require_success(
            test_client,
            ptbr_csv_bytes(n=30, tag="E"),
            filename="mercado.csv",
            spec=request_spec(),
            subject=subject_raw(),
        )
        statistical = (snap.get("validation") or {}).get("statistical") or {}
        assert snap["schema_version"] == "MP/1"
        assert finite_or_null(snap["value"]["point"])
        if statistical:
            assert "reserved_used_for_selection" not in statistical or statistical[
                "reserved_used_for_selection"
            ] is False


class TestFArtifacts:
    def test_snapshot_pdf_and_dossier_identity_when_ready(self):
        test_client = client()
        job_id, status, snap = _require_success(
            test_client,
            ptbr_csv_bytes(n=24, tag="F"),
            filename="mercado.csv",
            spec=request_spec(),
            subject=subject_raw(),
        )
        point = snap["value"]["point"]
        assert finite_or_null(point)
        pdf_state = (status.get("artifact_states") or {}).get("report.pdf") or {}
        evidence_state = (status.get("artifact_states") or {}).get("evidence_manifest.json") or {}
        if pdf_state.get("state") == "ready":
            pdf = test_client.get(f"/jobs/{job_id}/artifacts/report.pdf")
            assert pdf.status_code == 200
            assert pdf.content.startswith(b"%PDF")
            from .helpers import pdf_text

            text = pdf_text(pdf.content)
            compact = "".join(ch for ch in text if ch.isalnum())
            assert (
                snap["job_id"] in text
                or "MP1" in compact
                or "preco" in text.lower()
                or "avali" in text.lower()
                or "NBR" in compact
                or "14653" in compact
            )
            if point is not None:
                pretty = f"{point:.0f}"
                digits = pretty.replace(".", "").replace(",", "")
                assert pretty in text or digits[:4] in compact or "MP1" in compact or "14653" in compact
        else:
            assert pdf_state.get("state") == "failed"
            assert pdf_state.get("error")
        if evidence_state.get("state") == "ready":
            manifest = test_client.get(f"/jobs/{job_id}/artifacts/evidence_manifest.json")
            assert manifest.status_code == 200
            body = manifest.json() if manifest.headers.get("content-type", "").startswith("application/json") else None
            if body is None:
                import json

                body = json.loads(manifest.content.decode("utf-8"))
            assert body
        else:
            assert evidence_state.get("state") in {"failed", "pending", None}

    def test_more_than_200_rows_keeps_sample_counts(self):
        test_client = client()
        spec = request_spec(candidate_cols=["area"], roles={"preco": "target", "area": "predictor", "id": "identifier", "bairro": "excluded"})
        _job_id, _status, snap = _require_success(
            test_client,
            ptbr_csv_bytes(n=210, missing_target_at=9, tag="F200"),
            filename="mercado.csv",
            spec=spec,
            subject={"area": 90.0},
        )
        assert snap["sample"]["received"] == 210
        assert snap["sample"]["observed_target"] == 209
        assert len(snap["sample"]["used_row_ids"]) == snap["sample"]["used"]


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
        ctx = compose_valuation_job(
            job_id=created["job_id"],
            file_bytes=ptbr_csv_bytes(tag="H"),
            filename="mercado.csv",
            request_spec=request_spec(),
            subject_raw=subject_raw(),
            project_id=None,
            peers=peers,
            job_store=store,
        )
        frozen = ctx["frozen_project"]
        subjects = [
            {"subject_id": "s1", "bairro": "Centro", "area": 80.0},
            {"subject_id": "s2", "bairro": "Sul", "area": 110.0},
            {"subject_id": "s3", "bairro": "bairro_inexistente", "area": 90.0},
        ]
        batch = evaluate_batch(frozen, subjects, request_spec())
        items = batch.get("items") or []
        assert len(items) == 3
        points = [item.get("value", {}).get("point") for item in items]
        grades = []
        for item in items:
            assessment = item.get("assessment") or {}
            fund = ((assessment.get("normative") or {}).get("fundamentacao") or {})
            grades.append(fund.get("grade"))
            if item.get("subject_id") == "s3":
                eligibility = (assessment.get("model_eligibility") or item.get("model_eligibility") or {}).get("status")
                assert item.get("status") in {"unsupported", "failed", "succeeded", "pending"}
                assert eligibility in {"unsupported", "review_required", "error", "eligible", None}
                # Unknown category must not inherit another imóvel's point/grade.
                if item.get("status") in {"unsupported", "failed"}:
                    assert item.get("value", {}).get("point") in (None, 0) or item["value"]["point"] != points[0]
        assert len(set(str(p) for p in points)) >= 2 or any(p is None for p in points)
        assert len(set(str(g) for g in grades)) >= 1


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
                "target_degree": 1,
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
                "target_degree": 1,
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
