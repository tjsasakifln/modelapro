"""C04-A02: candidates under the same policy share the sample unless a recorded divergence."""

from __future__ import annotations

import pandas as pd

from modules.model_builder import fit_candidate
from tests.c04_fitting.conftest import make_prepared_dataset, make_request, make_spec, linear_market


def test_two_candidates_share_used_row_ids_under_common_policy():
    X, y, row_ids = linear_market(n=36, extra_influence=False)
    prepared = make_prepared_dataset(X, y, row_ids)
    request = make_request()
    fit_a = fit_candidate(prepared, make_spec("only-area", ["area"]), request)
    fit_b = fit_candidate(prepared, make_spec("area-quartos", ["area", "quartos"]), request)

    assert fit_a.status == "fitted"
    assert fit_b.status == "fitted"
    assert fit_a.used_row_ids == fit_b.used_row_ids == row_ids
    assert fit_a.excluded_row_ids == fit_b.excluded_row_ids == []
    assert fit_a.diagnostics["policy_mode"] == fit_b.diagnostics["policy_mode"]
    assert fit_a.diagnostics["r2_naive_comparison_blocked"] is False
    assert fit_b.diagnostics["r2_naive_comparison_blocked"] is False


def test_transform_domain_divergence_blocks_naive_r2_comparison():
    X, y, row_ids = linear_market(n=30, extra_influence=False)
    X = X.copy()
    X.loc[0, "area"] = 0.0
    X.loc[1, "area"] = -4.0
    prepared = make_prepared_dataset(X, y, row_ids)
    request = make_request()
    linear = fit_candidate(prepared, make_spec("linear-area", ["area"]), request)
    logged = fit_candidate(
        prepared,
        make_spec("ln-area", ["area"], x_transformations={"area": "ln"}),
        request,
    )

    assert linear.status == "fitted"
    assert row_ids[0] in linear.used_row_ids
    assert row_ids[1] in linear.used_row_ids
    assert logged.used_row_ids != linear.used_row_ids
    assert row_ids[0] in logged.excluded_row_ids
    assert row_ids[1] in logged.excluded_row_ids
    assert logged.diagnostics["r2_naive_comparison_blocked"] is True
    assert "divergent_sample_prevents_naive_r2_comparison" in logged.diagnostics["comparison_block_reasons"]


def test_reviewed_exclusion_applies_to_both_candidates():
    X, y, row_ids = linear_market(n=28, extra_influence=False)
    prepared = make_prepared_dataset(X, y, row_ids)
    drop_id = row_ids[3]
    request = make_request(
        outlier_policy={
            "mode": "reviewed_exclusions",
            "scenario": "principal",
            "reviewed_exclusions": [
                {
                    "row_id": drop_id,
                    "reason": "duplicata documental",
                    "author": "revisor",
                    "origin": "human_review",
                }
            ],
        }
    )
    fit_a = fit_candidate(prepared, make_spec("a", ["area"]), request)
    fit_b = fit_candidate(prepared, make_spec("b", ["quartos"]), request)
    assert fit_a.used_row_ids == fit_b.used_row_ids
    assert drop_id not in fit_a.used_row_ids
    assert drop_id in fit_a.excluded_row_ids
    assert drop_id in fit_b.excluded_row_ids
