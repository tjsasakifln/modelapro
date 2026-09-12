"""C06 numeric disclosures emitted by the real C02 -> C01 worker pipeline.

The fixtures are synthetic.  These checks prove numeric plumbing and JSON
safety; they do not assert professional review or institutional acceptance.
"""

from __future__ import annotations

import copy
import json
import math

import numpy as np
import pandas as pd

from backend.worker import compose_valuation_job, resolve_peers
from modules.job_store import JobStore
from modules.model_builder import CandidateSpec, _make_predict_original, fit_candidate
from modules.pro_workflow.numeric_disclosure import build_numeric_disclosure
from tests.c17_integration.helpers import fmt_ptbr
from tests.comercial.test_c06_document_flow import _professional_spec


def _noisy_linear_csv(n: int = 30) -> tuple[bytes, np.ndarray, np.ndarray]:
    areas = np.asarray([50.0 + 2.0 * i for i in range(n)], dtype=float)
    noise = np.asarray([((i % 5) - 2) * 1100.0 + ((i * i) % 7) * 137.0 for i in range(n)])
    prices = 180_000.0 + 3_750.0 * areas + noise
    lines = ["id;bairro;area;preco"]
    for i, (area, price) in enumerate(zip(areas, prices)):
        lines.append(
            f"DISC-{i + 1:03d};Centro;{fmt_ptbr(float(area))};{fmt_ptbr(float(price))}"
        )
    return ("\n".join(lines) + "\n").encode("utf-8"), areas, prices


def test_real_worker_emits_independently_checkable_numeric_disclosure(tmp_path):
    csv_bytes, areas, prices = _noisy_linear_csv()
    spec = _professional_spec()
    store = JobStore(tmp_path / "store", recover_abandoned=False)
    created = store.create(request_spec=spec, payload={"filename": "SINTETICO.csv"})

    composed = compose_valuation_job(
        job_id=created["job_id"],
        file_bytes=csv_bytes,
        filename="SINTETICO.csv",
        request_spec=spec,
        subject_raw={"area": 73.5, "bairro": "Centro"},
        project_id=None,
        peers=resolve_peers(),
        job_store=store,
    )
    snapshot = composed["snapshot"]
    # The strict serializer is an independent guard against NaN/Infinity.
    json.dumps(snapshot, allow_nan=False)

    model = snapshot["model"]
    metrics = model["metrics"]
    beta0 = float(model["coefficients"]["const"])
    beta1 = float(model["coefficients"]["area"])
    fitted = beta0 + beta1 * areas
    residuals = prices - fitted
    df_resid = len(areas) - 2
    sigma = math.sqrt(float(residuals @ residuals) / df_resid)

    assert math.isclose(metrics["r"], float(np.corrcoef(prices, fitted)[0, 1]), rel_tol=1e-12)
    assert metrics["r2"] == model["diagnostics"]["r2"]
    assert metrics["r2_adjusted"] == model["diagnostics"]["r2_adjusted"]
    assert metrics["f_statistic"] == model["diagnostics"]["f_statistic"]
    assert metrics["f_pvalue"] == model["diagnostics"]["f_pvalue"]
    assert math.isclose(
        metrics["durbin_watson"],
        float(np.diff(residuals) @ np.diff(residuals) / (residuals @ residuals)),
        rel_tol=1e-9,
    )
    assert math.isclose(
        metrics["r2_relation"]["r_squared"],
        metrics["r2_relation"]["r2"],
        rel_tol=1e-12,
    )
    assert set(model["pvalues"]) == {"const", "area"}
    assert all(math.isfinite(float(value)) for value in model["pvalues"].values())
    assert math.isclose(float(model["vif"]["area"]), 1.0, rel_tol=1e-12)
    assert model["candidate_spec"]["base_variables"] == ["area"]
    assert model["target_transform_state"] in ({}, None)
    assert model["model_sha256"] == model["used"]["model_sha256"]

    diagnostics = snapshot["validation"]["statistical"]["diagnostics"]
    standardized = diagnostics["standardized_residuals"]
    assert standardized["used_row_ids"] == snapshot["sample"]["used_row_ids"]
    assert np.allclose(standardized["values"], residuals / sigma, rtol=1e-9, atol=1e-9)
    assert "studentized" in standardized["definition"].lower()
    assert standardized["is_studentized"] is False

    normal = diagnostics["normal_frequency_comparison"]
    assert [row["z"] for row in normal["intervals"]] == [1.0, 1.64, 1.96]
    for row in normal["intervals"]:
        exact = math.erf(row["z"] / math.sqrt(2.0))
        assert math.isclose(row["nominal_probability"], exact, rel_tol=1e-15)
        observed = int(np.count_nonzero(np.abs(residuals / sigma) <= row["z"]))
        assert row["observed_count"] == observed
        assert row["observed_probability"] == observed / len(residuals)

    corr = diagnostics["correlation_matrix"]
    assert corr["sample"] == "effective_model_sample"
    assert corr["scale"] == "original"
    assert corr["variables"] == ["preco", "area"]
    assert np.allclose(corr["values"], np.corrcoef(np.column_stack([prices, areas]), rowvar=False))

    elasticity = diagnostics["elasticities"]
    assert elasticity["method"] == "central_finite_difference_predict_original"
    area_item = next(item for item in elasticity["items"] if item["variable"] == "area")
    expected_y = beta0 + beta1 * 73.5
    assert math.isclose(area_item["base_prediction"], expected_y, rel_tol=1e-12)
    assert math.isclose(area_item["elasticity"], beta1 * 73.5 / expected_y, rel_tol=1e-7)
    assert area_item["derivative_error"] >= 0.0

    outliers = diagnostics["outlier_count"]
    assert set(outliers) >= {"detected", "excluded", "influential", "definition"}
    assert outliers["excluded"] == 0
    assert outliers["definition"]["influential"]
    assert outliers["definition"]["excluded"]

    normative = json.loads(store.get_artifact(created["job_id"], "normative_assessment.json"))
    assert any("R²" in warning for warning in normative["statistical"]["warnings"])


def test_r_is_direct_correlation_even_if_supplied_r2_is_negative():
    x = np.asarray([1.0, 2.0, 3.0, 5.0, 8.0, 13.0], dtype=float)
    y = np.asarray([4.0, 4.7, 6.4, 7.1, 9.8, 12.3], dtype=float)
    prepared = {
        "X": pd.DataFrame({"x": x}),
        "y": pd.Series(y, name="y"),
        "row_ids": [f"r{i}" for i in range(len(x))],
        "feature_schema": {"version": 1, "target": {"column": "y"}},
        "encoder_state": {
            "column_order": ["x"],
            "base_variables": [{"original_name": "x", "kind": "numeric"}],
        },
        "base_frame": pd.DataFrame({"x": x}),
    }
    fit = fit_candidate(
        prepared,
        CandidateSpec(
            candidate_id="negative-r2-guard",
            features=["x"],
            base_variables=["x"],
            feature_groups={},
            x_transformations={},
            y_transformation="identity",
            intercept=True,
        ),
        {},
    )
    assert fit.status == "fitted"
    mutated = copy.copy(fit)
    mutated.diagnostics = dict(fit.diagnostics)
    mutated.diagnostics["r2"] = -0.25
    disclosure = build_numeric_disclosure(
        mutated,
        prepared,
        subject_raw={"x": 5.0},
        predict_original=lambda raw: {"point": 1.0 + 2.0 * float(raw["x"])},
    )
    expected = float(np.corrcoef(y, np.asarray(fit.model_object.fittedvalues))[0, 1])
    assert math.isclose(disclosure["model"]["metrics"]["r"], expected, rel_tol=1e-15)
    assert disclosure["model"]["metrics"]["r2"] == -0.25
    assert "r2_relation" not in disclosure["model"]["metrics"]


def test_zero_scale_and_categorical_inputs_are_explicitly_not_computable():
    x = np.arange(1.0, 9.0)
    y = 3.0 + 2.0 * x
    prepared = {
        "X": pd.DataFrame({"x": x}),
        "y": pd.Series(y, name="y"),
        "row_ids": [f"r{i}" for i in range(len(x))],
        "feature_schema": {"version": 1, "target": {"column": "y"}},
        "encoder_state": {
            "column_order": ["x"],
            "base_variables": [
                {"original_name": "x", "kind": "numeric"},
                {"original_name": "kind", "kind": "categorical"},
            ],
        },
        "base_frame": pd.DataFrame({"x": x, "kind": ["A", "B"] * 4}),
    }
    fit = fit_candidate(
        prepared,
        CandidateSpec(
            candidate_id="exact-fit",
            features=["x"],
            base_variables=["x", "kind"],
            feature_groups={},
            x_transformations={},
            y_transformation="identity",
            intercept=True,
        ),
        {},
    )
    disclosure = build_numeric_disclosure(
        fit,
        prepared,
        subject_raw={"x": 0.0, "kind": "A"},
        predict_original=lambda raw: {"point": 3.0 + 2.0 * float(raw["x"])},
    )
    encoded = json.dumps(disclosure, allow_nan=False)
    assert "Infinity" not in encoded and "NaN" not in encoded
    standardized = disclosure["diagnostics"]["standardized_residuals"]
    assert standardized["available"] is False
    assert standardized["values"] == []
    assert "exact_fit" in standardized["reason"]
    outlier_count = disclosure["diagnostics"]["outlier_count"]
    assert outlier_count["available"] is False
    assert outlier_count["detected"] is None
    assert outlier_count["influential"] is None
    elasticities = disclosure["diagnostics"]["elasticities"]
    assert elasticities["items"] == []
    assert any("zero_base_value" in warning for warning in elasticities["warnings"])
    assert any("categorical" in warning for warning in elasticities["warnings"])


def test_elasticity_uses_frozen_prediction_with_x_and_y_transformations():
    x = np.linspace(20.0, 80.0, 24)
    y = 3.25 * np.power(x, 1.7)
    prepared = {
        "X": pd.DataFrame({"x": x}),
        "y": pd.Series(y, name="price"),
        "row_ids": [f"r{i}" for i in range(len(x))],
        "feature_schema": {
            "version": 1,
            "columns": {"x": {"original_name": "x", "kind": "numeric"}},
            "target": {"column": "price"},
        },
        "encoder_state": {
            "column_order": ["x"],
            "base_variables": [{"original_name": "x", "kind": "numeric"}],
        },
        "base_frame": pd.DataFrame({"x": x}),
    }
    fit = fit_candidate(
        prepared,
        CandidateSpec(
            candidate_id="log-log-elasticity",
            features=["x"],
            base_variables=["x"],
            feature_groups={},
            x_transformations={"x": "ln"},
            y_transformation="log",
            intercept=True,
        ),
        {},
    )
    assert fit.status == "fitted"
    disclosure = build_numeric_disclosure(
        fit,
        prepared,
        subject_raw={"x": 40.0},
        predict_original=_make_predict_original(fit, {}),
    )
    item = disclosure["diagnostics"]["elasticities"]["items"][0]
    assert math.isclose(item["elasticity"], 1.7, rel_tol=1e-7)
    assert math.isclose(item["derivative"], 1.7 * item["base_prediction"] / 40.0, rel_tol=1e-7)
    assert disclosure["model"]["target_transform_state"]["name"] == "log"
    design = disclosure["diagnostics"]["correlation_matrix"]["design"]
    assert design["scale"] == "design"
    assert design["target_transformation"] == "log"


def test_partial_elasticity_and_matrix_coverage_are_never_available():
    x = np.arange(1.0, 13.0)
    y = 5.0 + 2.0 * x + np.asarray([0.0, 0.2, -0.1] * 4)
    prepared = {
        "X": pd.DataFrame({"x": x}),
        "y": pd.Series(y, name="y"),
        "row_ids": [f"r{i}" for i in range(len(x))],
        "feature_schema": {"version": 1, "target": {"column": "y"}},
        "encoder_state": {
            "column_order": ["x"],
            "base_variables": [{"original_name": "x", "kind": "numeric"}],
        },
        "base_frame": pd.DataFrame({"x": x}),
    }
    fit = fit_candidate(
        prepared,
        CandidateSpec(
            candidate_id="coverage",
            features=["x"],
            base_variables=["x"],
            feature_groups={},
            x_transformations={},
            y_transformation="identity",
            intercept=True,
        ),
        {},
    )
    partial = copy.copy(fit)
    partial.candidate_spec = CandidateSpec(
        candidate_id="coverage",
        features=["x"],
        base_variables=["x", "z"],
        feature_groups={},
        x_transformations={},
        y_transformation="identity",
        intercept=True,
    )
    partial.encoder_state = {
        "column_order": ["x"],
        "base_variables": [
            {"original_name": "x", "kind": "numeric"},
            {"original_name": "z", "kind": "numeric"},
        ],
    }

    def predictor(raw):
        if float(raw["z"]) != 2.0:
            raise ValueError("synthetic unsupported z perturbation")
        return {"point": 5.0 + 2.0 * float(raw["x"])}

    disclosure = build_numeric_disclosure(
        partial,
        prepared,
        subject_raw={"x": 5.0, "z": 2.0},
        predict_original=predictor,
    )
    elasticities = disclosure["diagnostics"]["elasticities"]
    assert [item["variable"] for item in elasticities["items"]] == ["x"]
    assert elasticities["available"] is False
    assert elasticities["status"] == "partial"
    assert elasticities["coverage"]["missing_variables"] == ["z"]

    matrix = disclosure["diagnostics"]["correlation_matrix"]
    assert matrix["values"]  # one valid pair is still insufficient coverage
    assert matrix["available"] is False
    assert matrix["status"] == "partial"
    assert matrix["missing_variables"] == [
        {"variable": "z", "reason": "missing_from_effective_base_frame"}
    ]


def test_finite_difference_refuses_underflow_and_unresolved_roundoff():
    x = np.arange(1.0, 9.0)
    prepared = {
        "X": pd.DataFrame({"x": x}),
        "y": pd.Series(3.0 + 2.0 * x, name="y"),
        "row_ids": [f"r{i}" for i in range(len(x))],
        "feature_schema": {"version": 1, "target": {"column": "y"}},
        "encoder_state": {
            "column_order": ["x"],
            "base_variables": [{"original_name": "x", "kind": "numeric"}],
        },
        "base_frame": pd.DataFrame({"x": x}),
    }
    fit = fit_candidate(
        prepared,
        CandidateSpec(
            candidate_id="finite-difference-guards",
            features=["x"],
            base_variables=["x"],
            feature_groups={},
            x_transformations={},
            y_transformation="identity",
            intercept=True,
        ),
        {},
    )
    underflow = build_numeric_disclosure(
        fit,
        prepared,
        subject_raw={"x": float.fromhex("0x0.0000000000001p-1022")},
        predict_original=lambda raw: {"point": 1.0 + float(raw["x"])},
    )["diagnostics"]["elasticities"]
    assert underflow["available"] is False
    assert any("step_not_representable" in warning for warning in underflow["warnings"])

    unresolved = build_numeric_disclosure(
        fit,
        prepared,
        subject_raw={"x": 10.0},
        predict_original=lambda raw: {"point": 1e20 + 1e-8 * float(raw["x"])},
    )["diagnostics"]["elasticities"]
    assert unresolved["items"] == []
    assert unresolved["available"] is False
    assert any("resolution_insufficient" in warning for warning in unresolved["warnings"])


def test_partial_studentized_residual_map_does_not_emit_outlier_count():
    x = np.arange(1.0, 13.0)
    y = 4.0 + 1.5 * x + np.asarray([0.0, 0.4, -0.2, 0.1] * 3)
    prepared = {
        "X": pd.DataFrame({"x": x}),
        "y": pd.Series(y, name="y"),
        "row_ids": [f"r{i}" for i in range(len(x))],
        "feature_schema": {"version": 1, "target": {"column": "y"}},
        "encoder_state": {
            "column_order": ["x"],
            "base_variables": [{"original_name": "x", "kind": "numeric"}],
        },
        "base_frame": pd.DataFrame({"x": x}),
    }
    fit = fit_candidate(
        prepared,
        CandidateSpec(
            candidate_id="partial-influence",
            features=["x"],
            base_variables=["x"],
            feature_groups={},
            x_transformations={},
            y_transformation="identity",
            intercept=True,
        ),
        {},
    )
    partial = copy.copy(fit)
    partial.diagnostics = copy.deepcopy(fit.diagnostics)
    missing_id = str(fit.used_row_ids[-1])
    partial.diagnostics["influence"]["studentized_residuals"].pop(missing_id)
    outliers = build_numeric_disclosure(
        partial,
        prepared,
        subject_raw={"x": 5.0},
        predict_original=lambda raw: {"point": 4.0 + 1.5 * float(raw["x"])},
    )["diagnostics"]["outlier_count"]
    assert outliers["available"] is False
    assert outliers["detected"] is None
    assert outliers["influential"] is None
    assert outliers["coverage"]["missing_row_ids"] == [missing_id]


def test_reviewed_exclusion_is_distinct_and_non_finite_values_become_null():
    x = np.arange(1.0, 13.0)
    y = 4.0 + 1.5 * x + np.asarray([0.0, 0.4, -0.2, 0.1] * 3)
    row_ids = [f"r{i}" for i in range(len(x))]
    prepared = {
        "X": pd.DataFrame({"x": x}),
        "y": pd.Series(y, name="y"),
        "row_ids": row_ids,
        "feature_schema": {"version": 1, "target": {"column": "y"}},
        "encoder_state": {
            "column_order": ["x"],
            "base_variables": [{"original_name": "x", "kind": "numeric"}],
        },
        "base_frame": pd.DataFrame({"x": x}),
    }
    fit = fit_candidate(
        prepared,
        CandidateSpec(
            candidate_id="reviewed-exclusion",
            features=["x"],
            base_variables=["x"],
            feature_groups={},
            x_transformations={},
            y_transformation="identity",
            intercept=True,
        ),
        {
            "outlier_policy": {
                "mode": "reviewed_exclusions",
                "reviewed_exclusions": [
                    {
                        "row_id": "r0",
                        "reason": "TESTE: exclusão previamente revisada",
                        "author": "PROFISSIONAL TESTE",
                    }
                ],
            }
        },
    )
    assert fit.status == "fitted"
    mutated = copy.copy(fit)
    mutated.diagnostics = dict(fit.diagnostics)
    mutated.diagnostics["f_statistic"] = float("inf")
    mutated.coefficient_records = copy.deepcopy(fit.coefficient_records)
    mutated.coefficient_records[0]["pvalue"] = float("nan")
    disclosure = build_numeric_disclosure(
        mutated,
        prepared,
        subject_raw={"x": float("inf")},
        predict_original=lambda raw: {"point": float("inf")},
    )
    json.dumps(disclosure, allow_nan=False)
    assert disclosure["model"]["metrics"]["f_statistic"] is None
    assert disclosure["model"]["pvalues"]["const"] is None
    outliers = disclosure["diagnostics"]["outlier_count"]
    assert outliers["excluded"] == 1
    assert outliers["excluded_row_ids"] == ["r0"]
    assert outliers["influence_authorizes_exclusion"] is False
    assert disclosure["diagnostics"]["elasticities"]["available"] is False


def _row_contract_fit():
    x = np.arange(1.0, 13.0)
    prepared = {
        "X": pd.DataFrame({"x": x}),
        "y": pd.Series(5 + 2 * x + np.asarray([0, .2, -.1] * 4), name="y"),
        "row_ids": [f"r{i}" for i in range(len(x))],
        "feature_schema": {"version": 1, "target": {"column": "y"}},
        "encoder_state": {"column_order": ["x"], "base_variables": [
            {"original_name": "x", "kind": "numeric"}]},
        "base_frame": pd.DataFrame({"x": x}),
    }
    fit = fit_candidate(prepared, CandidateSpec(
        candidate_id="row-contract", features=["x"], base_variables=["x"],
        feature_groups={}, x_transformations={}, y_transformation="identity", intercept=True,
    ), {})
    assert fit.status == "fitted"
    return fit, prepared


def test_correlation_joins_frozen_sample_by_row_identity_and_rejects_ambiguous_rows():
    fit, prepared = _row_contract_fit()
    expected = build_numeric_disclosure(fit, prepared)["diagnostics"]["correlation_matrix"]
    fit.base_frame = fit.base_frame.iloc[::-1]
    reordered = build_numeric_disclosure(fit, prepared)["diagnostics"]["correlation_matrix"]
    assert reordered["available"] is True
    assert np.allclose(reordered["values"], expected["values"])
    for invalid_index in (["NOT_USED"] + fit.used_row_ids[1:], [fit.used_row_ids[1]] + fit.used_row_ids[1:]):
        fit.base_frame.index = invalid_index
        invalid = build_numeric_disclosure(fit, prepared)["diagnostics"]["correlation_matrix"]
        assert invalid["available"] is False
        assert invalid["reason"] == "effective_sample_row_identity_mismatch"


def test_outlier_counts_require_all_finite_maps_and_exact_used_row_coverage():
    fit, prepared = _row_contract_fit()
    valid = build_numeric_disclosure(fit, prepared)["diagnostics"]["outlier_count"]
    assert valid["available"] is True
    original = copy.deepcopy(fit.diagnostics["influence"])
    for field in ("cooks_distance", "leverage", "studentized_residuals"):
        for mutation in ("missing", "extra", "nonfinite"):
            changed = copy.deepcopy(original)
            if mutation == "missing":
                changed.pop(field)
            elif mutation == "extra":
                changed[field]["NOT_USED"] = 999
            else:
                changed[field][fit.used_row_ids[0]] = float("nan")
            fit.diagnostics["influence"] = changed
            result = build_numeric_disclosure(fit, prepared)["diagnostics"]["outlier_count"]
            assert result["available"] is False, (field, mutation)
            assert result["coverage"]["complete"] is False
            assert result["coverage"]["influence_union_valid"] is False
            assert result["detected"] is None and result["influential"] is None
    for mutation in ("missing", "extra", "incorrect_union"):
        changed = copy.deepcopy(original)
        if mutation == "missing":
            changed.pop("influential_row_ids")
        elif mutation == "extra":
            changed["influential_row_ids"].append("NOT_USED")
        else:
            changed["influential_row_ids"] = list(fit.used_row_ids)
        fit.diagnostics["influence"] = changed
        result = build_numeric_disclosure(fit, prepared)["diagnostics"]["outlier_count"]
        assert result["available"] is False, mutation


def test_material_disclosure_change_invalidates_review_of_real_worker_result(tmp_path):
    from modules.pro_workflow.report_context import build_output_manifest
    from modules.valuation_policy.qualification import reassess_qualification_context

    spec = _professional_spec()
    store = JobStore(tmp_path / "store", recover_abandoned=False)
    job = store.create(request_spec=spec, payload={"filename": "SINTETICO.csv"})
    snapshot = compose_valuation_job(
        job_id=job["job_id"], file_bytes=_noisy_linear_csv()[0], filename="SINTETICO.csv",
        request_spec=spec, subject_raw={"area": 73.5, "bairro": "Centro"},
        project_id=None, peers=resolve_peers(), job_store=store,
    )["snapshot"]
    normative = json.loads(store.get_artifact(job["job_id"], "normative_assessment.json"))
    report_context = json.loads(store.get_artifact(job["job_id"], "report_context.json"))
    manifest = build_output_manifest(snapshot, report_context)

    def assess(subject, reviews=()):
        return reassess_qualification_context(
            snapshot=subject, request_spec=spec, output_manifest=manifest,
            report_content_fingerprint="a" * 64, normative_assessment=normative,
            review_events=reviews,
        )

    baseline = assess(snapshot)
    event = {"fingerprint": baseline["result_fingerprint"], "professional_id": "TESTE",
             "motive": "Revisão sintética", "version": "TESTE-1", "decision": "approved"}
    assert assess(snapshot, [event])["stale_review_events"] == []
    for name in ("standardized_residuals", "normal_frequency_comparison", "correlation_matrix",
                 "elasticities", "outlier_count"):
        changed = copy.deepcopy(snapshot)
        changed["validation"]["statistical"]["diagnostics"].pop(name)
        assessment = assess(changed, [event])
        assert assessment["result_fingerprint"] != baseline["result_fingerprint"], name
        assert assessment["stale_review_events"] == [event], name
