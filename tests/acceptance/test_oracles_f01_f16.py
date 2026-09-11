"""Adversarial unit tests against REAL modules for F01–F16.

Expected values come from tests/fixtures/independent/oracles.py or MP/1
invariants. Failures of production behavior are the honest baseline.
"""
from __future__ import annotations

import inspect
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from modules.data_loader import DataLoader
from modules.model_builder import ModelBuilder
from modules.nbr14653_validation import NBRValidator
from modules.optimal_combination import OptimalCombinationFinder
from modules.results import ModelMetrics, ModelResult, ValidationResult
from modules.transformations import Transformer
from modules.utils import format_currency, safe_float_conversion

from _helpers import (
    fixture_bytes,
    fixture_path,
    oracles,
    require_export,
    try_export,
    unpack_transform,
)


class TestF01MissingTarget:
    def test_observed_target_n_is_not_inflated_by_mean_imputation(self):
        path = fixture_path("f01_missing_target.csv")
        independent = oracles.f01_independent_n(path)
        assert independent["observed_target"] == 25
        assert independent["received"] == 30

        result = DataLoader().load_data(path.read_bytes(), "f01_missing_target.csv")
        assert result.success is True
        loaded = result.dataframe
        n_loaded_target = int(loaded["preco"].notna().sum())
        assert n_loaded_target == independent["observed_target"]
        assert len(loaded) == independent["observed_target"]

        # The 5 missing prices must not equal the observed mean.
        observed_mean = oracles.f01_observed_mean_preco(path)
        raw = pd.read_csv(path)
        missing_areas = raw.loc[raw["preco"].isna(), "area"].tolist()
        assert missing_areas == [50, 75, 100, 125, 150]
        if len(loaded) == 30:
            imputed = loaded.loc[loaded["area"].isin(missing_areas), "preco"]
            assert not np.allclose(imputed, observed_mean), (
                "missing target cells were filled with the observed mean"
            )


class TestF02LocaleParse:
    def test_pt_br_currency_matches_independent_parse(self):
        expected = {
            "R$ 1.234,56": oracles.parse_number("R$ 1.234,56", "pt-BR"),
            "R$ 2.000,00": oracles.parse_number("R$ 2.000,00", "pt-BR"),
            "3.500,50": oracles.parse_number("3.500,50", "pt-BR"),
        }
        assert expected["R$ 1.234,56"] == 1234.56
        path = fixture_path("f02_locale_ptbr.csv")
        result = DataLoader().load_data(path.read_bytes(), "f02_locale_ptbr.csv")
        assert result.success is True
        got = [float(v) for v in result.dataframe["preco"].tolist()]
        assert got == [1234.56, 2000.00, 3500.50]

    def test_en_us_thousands_are_not_parsed_as_pt_br(self):
        expected = [
            oracles.parse_number("1,234.56", "en-US"),
            oracles.parse_number("2,000.00", "en-US"),
            oracles.parse_number("3,500.50", "en-US"),
        ]
        assert expected == [1234.56, 2000.00, 3500.50]
        # Drive the real converter, then the real loader.
        assert safe_float_conversion("1,234.56") == 1234.56
        result = DataLoader().load_data(
            fixture_bytes("f02_locale_enus.csv"), "f02_locale_enus.csv"
        )
        assert result.success is True
        got = [float(v) for v in result.dataframe["preco"].tolist()]
        assert got == expected

    def test_ambiguous_token_is_not_silently_resolved(self):
        assert oracles.is_ambiguous_number("1.234") is True
        ingest = try_export("modules.data_loader", "ingest_market")
        if ingest is None:
            # Legacy converter has no locale argument — silent pt-BR is the defect.
            value = safe_float_conversion("1.234")
            assert value in (None, "pending") or math.isnan(value), (
                f"ambiguous 1.234 silently became {value}; locale is required"
            )
            return
        spec = {
            "schema_version": "MP/1",
            "target_col": "preco",
            "candidate_cols": ["area"],
            "roles": {"preco": "target", "area": "predictor"},
            "units": {},
            "import_options": {"locale": "auto", "delimiter": ",", "encoding": "utf-8"},
            "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
            "outlier_policy": {"mode": "report_only", "reviewed_exclusions": []},
            "search_policy": {"mode": "exhaustive", "budget": None, "objective": "grau", "seed": 16},
            "evaluation_policy": {"method": "holdout", "seed": 16},
            "reference_date": None,
            "inspection_date": None,
            "target_unit": "",
            "applicant": "synthetic-c16",
            "purpose": "ambiguous-locale",
        }
        bundle = ingest(fixture_bytes("f02_ambiguous.csv"), "f02_ambiguous.csv", spec)
        issues = bundle.get("issues") if isinstance(bundle, dict) else getattr(bundle, "issues", [])
        assert issues, "auto locale on an ambiguous token must raise a structured issue"


class TestF03SubjectCategories:
    def test_unseen_category_is_not_the_reference_encoding(self):
        training_categories = {"Centro", "Norte", "Sul"}
        subject_category = "Industrial"
        assert subject_category not in training_categories

        transform_subject = try_export("modules.preprocessing", "transform_subject")
        fit_dataset = try_export("modules.preprocessing", "fit_dataset")
        ingest = try_export("modules.data_loader", "ingest_market")
        if transform_subject is None or fit_dataset is None or ingest is None:
            src = Path("frontend/components/forms.py").read_text(encoding="utf-8")
            assert "select_dtypes(include=\"number\")" not in src or "bairro" in src, (
                "UNMET_DEPENDENCY:C02 transform_subject; UI also only edits numeric avaliando, "
                "so an unseen categorical subject cannot be expressed"
            )
            # Force the missing-export failure after documenting the UI gap.
            require_export("modules.preprocessing", "transform_subject", "C02")

        # Peer path: Industrial must be unsupported, not all-zero reference.
        spec = {
            "schema_version": "MP/1",
            "target_col": "preco",
            "candidate_cols": ["area", "bairro"],
            "roles": {"preco": "target", "area": "predictor", "bairro": "predictor"},
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
            "purpose": "unseen-category",
        }
        bundle = ingest(fixture_bytes("f03_categories.csv"), "f03_categories.csv", spec)
        prepared = fit_dataset(bundle, spec)
        subject = transform_subject(
            {"area": 100, "bairro": "Industrial"},
            prepared["feature_schema"] if isinstance(prepared, dict) else prepared.feature_schema,
            prepared["encoder_state"] if isinstance(prepared, dict) else prepared.encoder_state,
        )
        supported = subject["supported"] if isinstance(subject, dict) else subject.supported
        assert supported is False


class TestF04ExtrapolationDistinctFromMonetary:
    def test_faixa_ampliada_is_not_efeito_monetario(self):
        path = fixture_path("f04_extrapolation.csv")
        df = pd.read_csv(path)
        sample_min = float(df["area"].min())
        sample_max = float(df["area"].max())
        y_min = float(df["preco"].min())
        y_max = float(df["preco"].max())
        assert sample_min == 50
        assert sample_max == 100
        assert y_min == 50000
        assert y_max == 100000

        subjects = {
            "in_sample": 90.0,
            "extended": 150.0,
            "outside": 250.0,
        }
        independent = {}
        for name, area in subjects.items():
            pred = oracles.linear_price(area)
            independent[name] = {
                "faixa": oracles.faixa_ampliada(area, sample_min, sample_max),
                "efeito": oracles.efeito_monetario(pred, y_min, y_max),
                "predicted": pred,
            }
        assert independent["in_sample"]["faixa"] == "in_sample"
        assert independent["in_sample"]["efeito"] == "price_in_sample"
        assert independent["extended"]["faixa"] == "extended"
        assert independent["extended"]["efeito"] == "price_outside_sample"
        assert independent["outside"]["faixa"] == "outside_extended"
        assert independent["outside"]["efeito"] == "price_outside_sample"

        X = df[["area"]]
        y = df["preco"]
        fitted = ModelBuilder().build_model(X, y, degree=1, remove_outliers=False)
        assert fitted.success is True

        # Drive the real item-4 classifier (predictor interval only today).
        details_extended = [{
            "variable": "area",
            "avaliando_value": 150.0,
            "sample_min": sample_min,
            "sample_max": sample_max,
        }]
        grau, detail = NBRValidator._classify_item4_extrapolacao(details_extended)
        assert independent["extended"]["faixa"] == "extended"
        # SUT must expose monetary effect as a distinct field — not only item 4.
        completed = ModelBuilder().add_precision_and_extrapolation(
            fitted, {"area": 150.0}, df, degree=1
        )
        vr = completed.validation_result
        blob = json.dumps(vr.details, default=str) + " " + " ".join(vr.warnings)
        item4 = next(i for i in vr.item_scores if i.item == 4)
        assert "monet" in blob.lower() or "price_outside_sample" in blob or "efeito_monetario" in blob, (
            f"item 4 grau={item4.grau_achieved} detail={item4.detail!r} reports faixa only; "
            f"independent efeito={independent['extended']['efeito']} predicted="
            f"{independent['extended']['predicted']}"
        )
        assert grau is not None  # classifier ran
        assert oracles.NBR_14653_2["verification_status"] == "pending"


class TestF05ExclusionEffects:
    def test_default_outlier_policy_does_not_silently_drop_rows(self):
        sig = inspect.signature(ModelBuilder.build_model)
        default_remove = sig.parameters["remove_outliers"].default
        assert default_remove is False, (
            "MP/1 outlier_policy default is report_only; "
            f"build_model.remove_outliers defaults to {default_remove}"
        )
        df = pd.read_csv(fixture_path("f05_exclusions.csv"))
        n_received = len(df)
        assert n_received == 30
        fitted = ModelBuilder().build_model(
            df[["area"]], df["preco"], degree=1, remove_outliers=True
        )
        assert fitted.success is True
        n_used = len(fitted.fitted_values)
        # Even when removal is requested, exclusions must be identified.
        if n_used != n_received:
            assert fitted.outliers_removed, "rows vanished without outliers_removed"


class TestF06RankingScale:
    def test_ranking_prefers_grau_over_higher_r2(self):
        low_r2_high_grau = ModelResult(
            success=True,
            model_metrics=ModelMetrics(
                r2=0.55, r2_adjusted=0.50, f_statistic=10, f_pvalue=0.01,
                std_error=1, aic=1, bic=1, condition_number=1,
                normality_pvalue=0.5, homoscedasticity_pvalue=0.5,
                autocorrelation_durbin_watson=2,
            ),
            validation_result=ValidationResult(success=True, grau_fundamentacao=2),
        )
        high_r2_low_grau = ModelResult(
            success=True,
            model_metrics=ModelMetrics(
                r2=0.99, r2_adjusted=0.99, f_statistic=10, f_pvalue=0.01,
                std_error=1, aic=1, bic=1, condition_number=1,
                normality_pvalue=0.5, homoscedasticity_pvalue=0.5,
                autocorrelation_durbin_watson=2,
            ),
            validation_result=ValidationResult(success=True, grau_fundamentacao=1),
        )
        assert OptimalCombinationFinder._score_key(low_r2_high_grau) > OptimalCombinationFinder._score_key(
            high_r2_low_grau
        )

    def test_search_result_distinguishes_enumeration_from_ranking(self):
        search_models = try_export("modules.optimal_combination", "search_models")
        df = pd.read_csv(fixture_path("market_minimal.csv"))
        if search_models is None:
            result = OptimalCombinationFinder().find_best_model(
                df, "preco", degree=1, candidate_cols=["area", "quartos"],
                avaliando_raw={"area": 100.0, "quartos": 3.0},
            )
            assert result.success is True
            audit = getattr(result, "search_audit", None)
            assert isinstance(audit, dict), (
                "search_audit missing: combinations_tested="
                f"{result.combinations_tested} exhaustive={result.exhaustive} "
                "does not distinguish possible/generated/evaluated/rejected"
            )
            for key in ("possible", "generated", "evaluated", "rejected", "objective"):
                assert key in audit
            return
        require_export("modules.preprocessing", "fit_dataset", "C02")


class TestF07WarningsStates:
    def test_api_does_not_treat_upload_ack_as_calculation_success(self):
        from fastapi.testclient import TestClient
        from backend.api import app

        client = TestClient(app)
        response = client.post(
            "/upload",
            files={"file": ("bad.txt", b"not-a-spreadsheet", "text/plain")},
            data={"degree": 1, "target_col": "preco"},
        )
        # Fast ack is allowed; calculation success is a later job state.
        body = response.json()
        job_id = body.get("job_id")
        assert job_id, (
            f"ack without job_id cannot be distinguished from success: {body}"
        )
        status = client.get(f"/jobs/{job_id}")
        assert status.status_code == 200
        payload = status.json()
        assert payload.get("state") in {
            "queued", "running", "succeeded", "failed", "cancelled", "interrupted",
        }
        assert payload.get("state") != "succeeded"


class TestF08SamplesAnnexes:
    def test_pdf_or_bundle_keeps_all_rows_or_discloses_and_archives(self):
        from modules.results_generator import ResultsGenerator

        df = pd.read_csv(fixture_path("market_minimal.csv"))
        fitted = ModelBuilder().build_model(
            df[["area"]], df["preco"], degree=1, remove_outliers=False
        )
        market_250 = pd.DataFrame({
            "area": list(range(50, 300)),
            "preco": [1000 * a for a in range(50, 300)],
            "id_sintetico": [f"S{i:03d}" for i in range(250)],
        })
        assert len(market_250) == 250
        pdf = ResultsGenerator.generate_pdf_report(
            fitted, target_col="preco", market_data=market_250,
        )
        assert pdf is not None and pdf[:4] == b"%PDF"
        bundle_fn = try_export("modules.evidence_bundle", "build_evidence_bundle")
        if bundle_fn is None:
            # Truncation without an evidence bundle that holds all 250 rows.
            from pypdf import PdfReader
            import io
            text = ""
            try:
                reader = PdfReader(io.BytesIO(pdf))
                text = "\n".join((p.extract_text() or "") for p in reader.pages)
            except Exception:
                text = pdf.decode("latin-1", errors="ignore")
            has_all_ids = all(f"S{i:03d}" in text for i in range(250))
            assert has_all_ids, (
                "UNMET_DEPENDENCY:C12 build_evidence_bundle; PDF truncated "
                f"market_data at 200 without integral annex (ids in pdf={ 'S000' in text })"
            )


class TestF09DatesUnits:
    def test_unknown_unit_is_not_assumed_brl(self):
        formatted = format_currency(1234.56)
        assert formatted.startswith("R$")
        freeze = try_export("modules.result_contract", "freeze_result_snapshot")
        if freeze is None:
            raise AssertionError(
                "UNMET_DEPENDENCY:C10 freeze_result_snapshot; unknown target_unit "
                f"must stay pending, not {formatted!r}"
            )


class TestF10CentralResult:
    def test_failed_calculation_is_null_not_zero(self):
        finder = OptimalCombinationFinder()
        df = pd.DataFrame({"preco": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]})
        result = finder.find_best_model(df, "preco", degree=1, candidate_cols=["area"])
        assert result.success is False
        freeze = try_export("modules.result_contract", "freeze_result_snapshot")
        if freeze is None:
            raise AssertionError(
                "UNMET_DEPENDENCY:C10 freeze_result_snapshot; failure must serialize "
                "value.point=null + issue, never 0"
            )


class TestF11CostCoverage:
    def test_search_audit_coverage_fields(self):
        df = pd.read_csv(fixture_path("market_minimal.csv"))
        result = OptimalCombinationFinder().find_best_model(
            df, "preco", degree=1, candidate_cols=["area"],
            avaliando_raw={"area": 100.0},
        )
        assert result.success is True
        audit = getattr(result, "search_audit", None)
        assert isinstance(audit, dict)
        for key in ("possible", "generated", "evaluated", "rejected", "budget", "coverage"):
            assert key in audit, f"search_audit missing {key}; tested={result.combinations_tested}"


class TestF12SqrtZero:
    def test_transformer_sqrt_zero(self):
        transformed, success = unpack_transform(
            Transformer.apply_transformation(pd.Series([0.0]), "sqrt")
        )
        assert success is True
        assert float(transformed.iloc[0]) == math.sqrt(0.0)

    def test_ln_zero_remains_undefined(self):
        _transformed, success = unpack_transform(
            Transformer.apply_transformation(pd.Series([0.0]), "ln")
        )
        assert success is False


class TestF13NotificationLoss:
    def test_completed_result_is_recoverable_without_websocket(self):
        import inspect
        from backend.api import app
        from modules.websocket_notifier import WebSocketNotifier
        from _helpers import route_paths

        paths = route_paths(app)
        assert any("/jobs/" in p and p.rstrip("/").endswith("/result") for p in paths), (
            "GET /jobs/{id}/result is not registered; the UI recovers results only via /ws"
        )
        src = inspect.getsource(WebSocketNotifier.send_notification)
        # Dropping the payload when idle means a completed job is unrecoverable
        # without a live socket (F13). Persistence must exist besides WS.
        if "if not self.active_connections" in src and "return" in src:
            JobStore = try_export("modules.job_store", "JobStore")
            assert JobStore is not None, (
                "send_notification returns without clients and JobStore is absent; "
                "completed payloads are discarded"
            )


class TestF14Isolation:
    def test_job_store_exists_and_two_jobs_do_not_share_dataframe(self):
        JobStore = try_export("modules.job_store", "JobStore")
        if JobStore is None:
            from backend.worker import Worker
            w = Worker()
            assert not hasattr(w.data_loader, "df") or True
            raise AssertionError("UNMET_DEPENDENCY:C11 JobStore")
        store = JobStore()
        a = store.create({"project_id": "p1"})
        b = store.create({"project_id": "p2"})
        assert a != b


class TestF15CleanInstallConsumesC15:
    def test_c15_process_is_consumed_not_reimplemented(self):
        c15_scripts = Path("scripts/c15_local")
        c15_docs = Path("docs/campaigns/MP-20260911/C15")
        if not c15_scripts.exists() and not c15_docs.exists():
            raise AssertionError(
                "UNMET_DEPENDENCY:C15 clean-install process not published "
                "(scripts/c15_local or docs/campaigns/MP-20260911/C15)"
            )
        # Consume, do not re-pack: if a runner exists, it must be C15's file.
        runners = list(c15_scripts.glob("*")) if c15_scripts.exists() else []
        assert runners or (c15_docs / "acceptance.json").exists()


class TestF16EmptySelection:
    def test_empty_list_is_not_all_columns(self):
        df = pd.read_csv(fixture_path("f16_empty_selection.csv"))
        result = OptimalCombinationFinder().find_best_model(
            df, "preco", degree=1, candidate_cols=[],
        )
        assert result.success is False
        assert result.best_model is None
        # If it succeeded, it treated [] as all columns — the audited defect.
        if result.success:
            used = {
                OptimalCombinationFinder._base_name(c)
                for c in (result.best_model.coefficients or {})
                if c != "const"
            }
            assert used == set(), f"[] authorized predictors {used}"


class TestMp1ExportsPresent:
    def test_named_exports_exist(self):
        expected = [
            ("modules.data_loader", "ingest_market", "C01"),
            ("modules.preprocessing", "fit_dataset", "C02"),
            ("modules.preprocessing", "transform_subject", "C02"),
            ("modules.nbr14653_validation", "assess_normative", "C03"),
            ("modules.model_builder", "fit_candidate", "C04"),
            ("modules.optimal_combination", "search_models", "C05"),
            ("modules.target_transform", "fit_target_transform", "C06"),
            ("modules.model_evaluation", "evaluate_procedure", "C07"),
            ("modules.results_generator", "render_report", "C08"),
            ("modules.result_contract", "freeze_result_snapshot", "C10"),
            ("modules.evidence_bundle", "build_evidence_bundle", "C12"),
            ("modules.decision_support", "recommend_next_actions", "C13"),
            ("modules.valuation_batch", "evaluate_batch", "C14"),
            ("modules.job_store", "JobStore", "C11"),
            ("modules.project_store", "ProjectStore", "C11"),
            ("modules.local_task_runner", "LocalTaskRunner", "C11"),
        ]
        missing = []
        for mod, attr, owner in expected:
            if try_export(mod, attr) is None:
                missing.append(f"{owner}:{mod}.{attr}")
        assert not missing, "UNMET_DEPENDENCY:" + ",".join(missing)
