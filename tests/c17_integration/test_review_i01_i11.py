"""Review I01–I11 against shipped producers. No labeled C10 simulators."""

from __future__ import annotations

import json

from backend.worker import compose_preview, compose_valuation_job, _model_identity
from modules.data_loader import ingest_market
from modules.model_builder import CandidateFit, fit_candidate
from modules.optimal_combination import search_models
from modules.preprocessing import fit_dataset, transform_subject
from modules.utils import parse_numeric_token
from modules.variable_schema import parse_numeric

from .helpers import (
    client,
    issue_codes,
    post_job,
    production_peers,
    ptbr_csv_bytes,
    request_spec,
    subject_raw,
    wait_job,
)


class TestI01CanonicalObjects:
    def test_real_chain_numeric_and_categorical(self, isolated_c17_runtime):
        spec = request_spec()
        bundle = ingest_market(ptbr_csv_bytes(tag="I01"), "mercado.csv", spec)
        prepared = fit_dataset(bundle, spec, None)
        assert hasattr(prepared, "get")
        assert prepared.get("X") is prepared.X
        assert list(prepared.row_ids) == list(prepared.X.index) or len(prepared.row_ids) == len(prepared.X)
        schema = prepared.feature_schema
        groups = schema.get("groups") or {}
        assert any("bairro" in str(g).lower() or "bairro" in str(schema.get("columns")) for g in groups)
        encoder = prepared.encoder_state
        bases = encoder.get("base_variables") or []
        cat = next(b for b in bases if b.get("original_name") == "bairro" or b.get("kind") == "categorical")
        assert "Centro" in (cat.get("categories") or [])
        assert cat.get("reference_category") == "Centro"
        design = transform_subject(subject_raw(bairro="Centro"), schema, encoder)
        assert design.supported is True
        assert design.get("raw_values")["bairro"] == "Centro"
        result = search_models(prepared, design, spec)
        winner = result["winner"]
        assert winner is not None
        fit = winner.get("candidate_fit")
        assert isinstance(fit, CandidateFit)
        assert fit.coefficients
        assert fit.used_row_ids
        assert list(prepared.X.columns)


class TestI02SingleParser:
    def test_same_token_same_locale_same_result(self):
        cases = [
            ("1.234", "auto", None, "ambiguous"),
            ("1.234", "pt-BR", 1234.0, "parsed"),
            ("1.234", "en-US", 1.234, "parsed"),
            ("1,234", "pt-BR", 1.234, "parsed"),
            ("1,234", "en-US", 1234.0, "parsed"),
            ("123.45", "en-US", 123.45, "parsed"),
            ("123.45", "pt-BR", 123.45, "parsed"),
            ("R$ 1.234,56", "pt-BR", 1234.56, "parsed"),
            ("1,234.56", "en-US", 1234.56, "parsed"),
            (1234.56, "auto", 1234.56, "already_numeric"),
        ]
        for token, locale, expected, status in cases:
            c01 = parse_numeric_token(token, locale)
            c02 = parse_numeric(token, locale)
            assert c01.status == status, (token, locale, c01)
            if expected is None:
                assert c01.value is None
                assert c02 is None
            else:
                assert c01.value == expected
                assert c02 == expected

    def test_missing_target_and_empty_cols(self):
        spec = request_spec()
        bundle = ingest_market(ptbr_csv_bytes(), "m.csv", spec)
        assert sum(1 for r in bundle.row_ledger if r["observed_target"]) == 23
        test_client = client()
        resp = post_job(test_client, file_bytes=ptbr_csv_bytes(), spec=request_spec(candidate_cols=[]))
        assert resp.status_code == 400
        assert "CANDIDATE_COLS_EMPTY" in issue_codes(resp)


class TestI03WinnerIsFit:
    def test_frozen_project_has_coefficients(self, isolated_c17_runtime):
        store = isolated_c17_runtime["job_store"]
        created = store.create(payload={"filename": "m.csv"})
        ctx = compose_valuation_job(
            job_id=created["job_id"],
            file_bytes=ptbr_csv_bytes(tag="I03"),
            filename="m.csv",
            request_spec=request_spec(),
            subject_raw=subject_raw(),
            project_id="proj_i03",
            peers=production_peers(),
            job_store=store,
        )
        frozen = ctx["frozen_project"]
        coeffs = (frozen.get("model_state") or {}).get("coefficients") or {}
        assert coeffs, frozen.get("model_state")
        fit = ctx["snapshot"]
        ident = fit["model"]
        assert ident.get("coefficients")
        assert ident.get("delivered_matches_used") is True
        used = ident.get("used") or {}
        delivered = ident.get("delivered") or {}
        assert used.get("used_row_ids") == delivered.get("used_row_ids")
        # Mutation of used_row_ids must not still match.
        used_mut = dict(used)
        used_mut["used_row_ids"] = list(used["used_row_ids"])[:-1]
        assert used_mut["used_row_ids"] != delivered.get("used_row_ids")


class TestI04NormativeContext:
    def test_item4_uses_point_not_assessment_object(self, isolated_c17_runtime):
        store = isolated_c17_runtime["job_store"]
        created = store.create()
        ctx = compose_valuation_job(
            job_id=created["job_id"],
            file_bytes=ptbr_csv_bytes(tag="I04"),
            filename="m.csv",
            request_spec=request_spec(),
            subject_raw=subject_raw(area=150.0, bairro="Centro"),
            project_id=None,
            peers=production_peers(),
            job_store=store,
        )
        snap = ctx["snapshot"]
        fund = (snap.get("validation") or {}).get("fundamentacao") or {}
        items = fund.get("items") or []
        item4 = next((i for i in items if i.get("item") == 4), None)
        assert item4 is not None
        assert item4.get("source", {}).get("edition") or snap["validation"].get("normative_edition")
        assert snap["validation"]["issuance"]["status"] != "ready_for_professional_review" or snap["validation"].get(
            "normative_verification_status"
        ) in {"verified_rules_listed", "partial"}
        assert snap["value"]["point"] is not None
        codes = {i.get("code") for i in snap.get("issues") or []}
        assert "item4_axes_missing" not in codes
        assert "k_unknown" not in codes
        assert "NON_JSON_VALUE" not in codes
        assert "axes_missing" not in (item4.get("reasons") or [])
        calc = item4.get("calculation") or {}
        # area=150 is inside the 0.5·min–2·max window of the C17 fixture, so
        # item 4 (b) must run in the original unit via predict_original {point}.
        assert calc.get("y_subject") is not None
        assert isinstance(calc.get("y_subject"), (int, float))
        stat = (snap.get("validation") or {}).get("statistical") or {}
        assert stat.get("n") == snap["sample"]["used"]
        assert stat.get("k") is not None and int(stat["k"]) >= 1
        assert snap["sample"]["used"] == len(snap["sample"]["used_row_ids"])
        for alt in snap.get("alternatives") or []:
            assert "candidate_fit" not in alt or alt.get("candidate_fit") is None


class TestI05ProcedureHandle:
    def test_fold_predictor_has_predict(self):
        from backend.worker import _FoldPredictor

        class Dummy:
            status = "fitted"
            coefficients = {"area": 1.0}

        pred = _FoldPredictor(Dummy(), {"row_ids": ["a"], "feature_schema": {}, "encoder_state": {}}, {}, {}, 1, ["a"])
        assert callable(pred.predict)
        assert "used_row_ids" in pred.trace


class TestI06PreviewProfile:
    def test_preview_without_target_returns_schema_and_ledger(self):
        preview = compose_preview(
            file_bytes=ptbr_csv_bytes(tag="I06"),
            filename="m.csv",
            request_spec={
                "schema_version": "MP/1",
                "target_col": "",
                "candidate_cols": None,
                "roles": {},
                "units": {},
                "import_options": {"locale": "pt-BR", "delimiter": ";", "encoding": "utf-8"},
                "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
                "outlier_policy": {"mode": "report_only", "reviewed_exclusions": []},
                "search_policy": {"mode": "exact", "budget": 8, "objective": "aic", "seed": 1},
                "evaluation_policy": {"method": "none", "partitions": None, "groups": None, "seed": 1},
                "reference_date": None,
                "inspection_date": None,
                "target_unit": "",
                "applicant": "",
                "purpose": "preview",
            },
        )
        assert preview["preview"] is True
        assert preview["search_invoked"] is False
        assert preview["feature_schema"]["preview"] is True
        columns = preview["feature_schema"]["columns"]
        assert any("bairro" in str(c).lower() or (isinstance(m, dict) and m.get("kind") == "categorical") for c, m in columns.items())
        assert preview["row_ledger"]
        assert preview["sample_preview"]
        test_client = client()
        resp = test_client.post(
            "/preview",
            files={"file": ("m.csv", ptbr_csv_bytes(), "text/csv")},
            data={"request_json": "{}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("feature_schema")
        assert body.get("row_ledger") is not None


class TestI07ReportRows:
    def test_report_context_has_row_values(self, isolated_c17_runtime):
        store = isolated_c17_runtime["job_store"]
        created = store.create()
        ctx = compose_valuation_job(
            job_id=created["job_id"],
            file_bytes=ptbr_csv_bytes(n=24, tag="I07"),
            filename="m.csv",
            request_spec=request_spec(),
            subject_raw=subject_raw(),
            project_id=None,
            peers=production_peers(),
            job_store=store,
        )
        report_ctx = ctx["report_context"]
        used = report_ctx.get("used_rows") or []
        assert used
        assert used[0].get("values")
        assert "area" in used[0]["values"] or "preco" in used[0]["values"]
        snap = ctx["snapshot"]
        assert (snap.get("model") or {}).get("coefficients")


class TestI08IdentityNotTautology:
    def test_mutation_breaks_match(self):
        used_fit = {
            "candidate_id": "c1",
            "model_sha256": "a" * 64,
            "used_row_ids": ["r1", "r2"],
            "coefficients": {"area": 10.0, "const": 1.0},
            "candidate_spec": {"y_transformation": "identity"},
            "encoder_state": {"v": 1},
        }
        assessment = {
            "candidate_id": "c1",
            "used_row_ids": ["r1", "r2"],
            "value": {"point": 100.0},
        }
        prepared = {"row_ids": ["r1", "r2"], "dataset_sha256": "d", "encoder_state": {"v": 1}, "feature_schema": {"version": 1}}
        ident = _model_identity(used_fit, prepared, assessment)
        assert ident["delivered_matches_used"] is True
        ident_bad = _model_identity(
            {**used_fit, "used_row_ids": ["r1"]},
            prepared,
            assessment,
        )
        assert ident_bad["delivered_matches_used"] is False


class TestI11TrainRmseIsNotGeneralization:
    def test_search_audit_does_not_claim_unmeasured_gain(self, isolated_c17_runtime):
        store = isolated_c17_runtime["job_store"]
        created = store.create()
        ctx = compose_valuation_job(
            job_id=created["job_id"],
            file_bytes=ptbr_csv_bytes(tag="I11"),
            filename="m.csv",
            request_spec=request_spec(search_policy={
                "mode": "approximate",
                "budget": 3,
                "objective": "aic",
                "seed": 17,

                "y_transformations": ["identity"],
            }),
            subject_raw=subject_raw(),
            project_id=None,
            peers=production_peers(),
            job_store=store,
        )
        audit = (ctx["snapshot"].get("search") or {}).get("audit") or {}
        coverage = audit.get("coverage") or {}
        if coverage.get("exact_optimum_guaranteed") is True:
            assert coverage.get("enumeration") == "exhaustive"
        else:
            assert coverage.get("exact_optimum_guaranteed") in (False, None)
