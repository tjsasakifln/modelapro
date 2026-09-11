"""C07-A03: unseen category is a coverage failure, not a silent metric win."""

from __future__ import annotations

from datetime import date, timedelta

from modules.model_evaluation import evaluate_procedure

from contract_fixtures import (
    labeled_fit_select_predictor,
    make_input_bundle,
    make_request_spec,
)


def _bundle():
    rows = []
    start = date(2021, 1, 1)
    n = 32
    for i in range(n):
        # Only the last three dated rows carry the unseen category so
        # coverage can be strictly between 0 and 1 (failures remain in the
        # denominator instead of vanishing).
        unseen = i >= n - 3
        rows.append(
            {
                "row_id": f"u{i:03d}",
                "area": float(70 + i),
                "quartos": 2 + (i % 3),
                "bairro": "UNSEEN_Z" if unseen else ("Centro" if i % 2 == 0 else "Norte"),
                "preco": 1000.0 * (70 + i) + 90000.0,
                "data": (start + timedelta(days=7 * i)).isoformat(),
            }
        )
    bundle = make_input_bundle(rows, input_sha256="synthetic-a03")
    spec = make_request_spec(
        roles={
            "preco": "target",
            "area": "predictor",
            "quartos": "predictor",
            "bairro": "predictor",
            "data": "date",
            "row_id": "identifier",
        },
        evaluation_policy={
            "method": "temporal",
            "time_column": "data",
            "test_size": 0.25,
            "n_splits": 1,
            "mode": "fast",
            "stability": False,
        },
    )
    return bundle, spec


def test_unseen_category_stays_in_coverage_denominator_and_is_not_zero():
    bundle, spec = _bundle()
    fit = labeled_fit_select_predictor(bundle, spec, leak=False)
    result = evaluate_procedure(bundle, spec, fit, 1)

    reserved = result["coverage"]["reserved_row_ids"]
    failed = result["coverage"]["failed_row_ids"]
    covered = result["coverage"]["covered_row_ids"]
    assert reserved, "temporal split must reserve future rows"
    assert failed, "unseen category must produce prediction failures"
    assert set(failed).issubset(set(reserved))
    assert set(covered).isdisjoint(set(failed))

    unseen_rows = [p for p in result["predictions"] if p["row_id"] in set(failed)]
    assert unseen_rows
    for row in unseen_rows:
        assert row["y_pred"] is None
        assert row["y_pred"] != 0
        assert row["status"] == "failed"
        issue = row.get("issue") or {}
        assert issue.get("code") == "c07.unseen_category"

    metrics = result["metrics"]
    # Denominator is reserved-with-target, not the covered subset.
    assert metrics["n_reserved"] == len(reserved)
    assert metrics["n_failed"] == len(failed)
    assert metrics["n_covered"] == len(covered)
    assert metrics["n_covered"] + metrics["n_failed"] == metrics["n_with_target"]
    assert metrics["coverage_denominator_n"] == metrics["n_with_target"]
    assert metrics["failed_remain_in_denominator"] is True
    assert metrics["coverage"] == metrics["n_covered"] / metrics["n_with_target"]
    assert metrics["coverage"] < 1.0

    # MAE is scoped to covered cases AND the result still carries the failures,
    # so dropping UNSEEN_Z cannot be mistaken for a smaller, better sample.
    assert metrics["metrics_scope"] == "covered_cases_only"
    assert result["coverage"]["silent_drop"] is False
    assert metrics["n_failed"] == len(result["coverage"]["failures"])

    cheating_n = metrics["n_covered"]
    assert metrics["n_reserved"] > cheating_n
    assert "UNSEEN_Z" in {
        bundle["parsed_frame"].set_index("row_id").loc[rid, "bairro"] for rid in failed
    }


def test_out_of_support_is_not_a_zero_prediction():
    bundle, spec = _bundle()
    fit = labeled_fit_select_predictor(bundle, spec, leak=False)
    result = evaluate_procedure(bundle, spec, fit, 1)
    zeros = [
        p
        for p in result["predictions"]
        if p["status"] == "failed" and p["y_pred"] == 0
    ]
    assert zeros == []
