"""C04-A01: influential points stay in the principal analysis; exclusions are documented."""

from __future__ import annotations

import numpy as np
import pandas as pd

from modules.influence_policy import ORIGIN_HUMAN_REVIEW, ORIGIN_PRE_FIT_INPUT_ERROR
from modules.model_builder import ModelBuilder, evaluate_fitted, fit_candidate
from tests.c04_fitting.conftest import make_prepared_dataset, make_request, make_spec, linear_market

SEED = 20260911


def _influence_case():
    X, y, row_ids = linear_market(n=40, seed=SEED, extra_influence=True)
    prepared = make_prepared_dataset(X, y, row_ids)
    spec = make_spec("lin-area", ["area", "quartos"])
    return prepared, spec, row_ids, X, y


def test_principal_fit_keeps_influential_point_and_reports_it():
    prepared, spec, row_ids, X, y = _influence_case()
    influential_id = row_ids[-1]
    fit = fit_candidate(prepared, spec, make_request())

    assert fit.status == "fitted"
    assert influential_id in fit.used_row_ids
    assert influential_id not in fit.excluded_row_ids
    influence = fit.diagnostics["influence"]
    assert influential_id in influence["influential_row_ids"]
    assert influence["influence_authorizes_exclusion"] is False
    assert any(i["code"] == "influence_reported" for i in fit.issues)
    assert fit.diagnostics["n"] == len(row_ids)
    cooks = influence["cooks_distance"][str(influential_id)]
    assert cooks > influence["thresholds"]["cooks_4_over_n"]


def test_documented_exclusion_has_id_reason_author_and_separate_counts():
    prepared, spec, row_ids, X, y = _influence_case()
    target = row_ids[-1]
    request = make_request(
        outlier_policy={
            "mode": "reviewed_exclusions",
            "scenario": "principal",
            "reviewed_exclusions": [
                {
                    "row_id": target,
                    "reason": "erro cadastral confirmado na ficha de origem",
                    "author": "perito.teste",
                    "origin": ORIGIN_HUMAN_REVIEW,
                    "evidence": {"source": "contract-fixture-review"},
                }
            ],
        }
    )
    principal_keep = fit_candidate(prepared, spec, make_request())
    revised = fit_candidate(prepared, spec, request)

    assert target in principal_keep.used_row_ids
    assert target not in revised.used_row_ids
    assert target in revised.excluded_row_ids
    assert len(revised.used_row_ids) == len(principal_keep.used_row_ids) - 1
    assert len(revised.excluded_row_ids) == 1
    records = revised.diagnostics["exclusions"]
    assert len(records) == 1
    rec = records[0]
    assert rec["row_id"] == target
    assert rec["reason"] == "erro cadastral confirmado na ficha de origem"
    assert rec["author"] == "perito.teste"
    assert rec["origin"] == ORIGIN_HUMAN_REVIEW
    assert rec["evidence"]["source"] == "contract-fixture-review"
    assert principal_keep.model_sha256 != revised.model_sha256


def test_exploratory_without_observation_is_separate_from_principal():
    prepared, spec, row_ids, X, y = _influence_case()
    target = row_ids[-1]
    principal = fit_candidate(prepared, spec, make_request())
    exploratory = fit_candidate(
        prepared,
        spec,
        make_request(
            outlier_policy={
                "mode": "reviewed_exclusions",
                "scenario": "exploratory",
                "reviewed_exclusions": [
                    {
                        "row_id": target,
                        "reason": "cenário com/sem observação",
                        "author": "analista",
                        "origin": "exploratory",
                    }
                ],
            }
        ),
    )
    assert principal.diagnostics["scenario"] == "principal"
    assert target in principal.used_row_ids
    assert exploratory.diagnostics["scenario"] == "exploratory"
    assert target in exploratory.excluded_row_ids
    assert any(i["code"] == "exploratory_scenario" for i in exploratory.issues)
    assert exploratory.diagnostics["r2_naive_comparison_blocked"] is True
    # Exploratory result must not be treated as a rewrite of the principal sample.
    assert principal.used_row_ids != exploratory.used_row_ids


def test_pre_fit_input_error_requires_rule_and_evidence():
    prepared, spec, row_ids, X, y = _influence_case()
    target = row_ids[0]
    fit = fit_candidate(
        prepared,
        spec,
        make_request(
            outlier_policy={
                "mode": "report_only",
                "scenario": "principal",
                "pre_fit_rules": [
                    {
                        "row_id": target,
                        "reason": "área negativa na origem, anterior ao ajuste",
                        "origin": ORIGIN_PRE_FIT_INPUT_ERROR,
                        "rule": "area_must_be_positive",
                        "evidence": {"area": float(X.iloc[0]["area"]), "check": "area > 0"},
                    }
                ],
            }
        ),
    )
    assert target in fit.excluded_row_ids
    rec = fit.diagnostics["exclusions"][0]
    assert rec["rule"] == "area_must_be_positive"
    assert rec["evidence"]["check"] == "area > 0"
    assert rec["origin"] == ORIGIN_PRE_FIT_INPUT_ERROR


def test_legacy_remove_outliers_true_does_not_drop_silently():
    X, y, row_ids = linear_market(n=40, seed=SEED, extra_influence=True)
    builder = ModelBuilder()
    result = builder.build_model(X, y, degree=1, remove_outliers=True)
    assert result.success is True
    assert result.outliers_removed == []
    assert len(result.residuals) == len(X)
    warnings = result.validation_result.warnings
    assert any("remove_outliers=True" in w for w in warnings)
    assert any("silêncio" in w or "silencio" in w.lower() for w in warnings)
    assert any("influentes" in w.lower() for w in warnings)


def test_evaluate_fitted_uses_same_ids_as_principal_fit():
    prepared, spec, row_ids, X, y = _influence_case()
    fit = fit_candidate(prepared, spec, make_request())
    subject = {
        "subject_id": "imovel-a",
        "raw_values": {"area": 30.0, "quartos": 3.0},
        "X": pd.DataFrame([{"area": 30.0, "quartos": 3.0}]),
        "supported": True,
        "issues": [],
        "contract_fixture": True,
        "contract_fixture_for": "C02",
    }
    assessment = evaluate_fitted(fit, subject, make_request())
    assert assessment.used_row_ids == fit.used_row_ids
    assert assessment.excluded_row_ids == fit.excluded_row_ids
    assert row_ids[-1] in assessment.used_row_ids
