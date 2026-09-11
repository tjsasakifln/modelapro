"""C07-A01: sentinel detects holdout contamination; the correct procedure passes."""

from __future__ import annotations

from datetime import date, timedelta

from modules.model_evaluation import detect_preprocessing_leak, evaluate_procedure

from contract_fixtures import (
    CONTRACT_FIXTURE_LABEL,
    labeled_fit_select_predictor,
    make_input_bundle,
    make_request_spec,
)


def _temporal_bundle_with_holdout_only_category():
    """Last quarter of dated rows carries a category and extreme x unseen earlier."""
    rows = []
    start = date(2020, 1, 1)
    n = 40
    n_hold = 10
    for i in range(n):
        is_future = i >= n - n_hold
        rows.append(
            {
                "row_id": f"t{i:03d}",
                "area": 1000.0 if is_future else 80.0 + (i % 10),
                "quartos": 3,
                "bairro": "LEAK_CAT" if is_future else ("Centro" if i % 2 == 0 else "Norte"),
                "preco": 1000.0 * (80.0 + (i % 10)) + 80000.0,
                "data": (start + timedelta(days=i)).isoformat(),
            }
        )
    bundle = make_input_bundle(rows, input_sha256="synthetic-a01")
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
            "seed": 7,
        },
    )
    return bundle, spec


def test_evaluate_procedure_passes_only_train_ids_to_callback():
    bundle, spec = _temporal_bundle_with_holdout_only_category()
    seen = []

    inner = labeled_fit_select_predictor(bundle, spec, leak=False)

    def wrapped(train_row_ids, seed):
        seen.append(list(train_row_ids))
        return inner(train_row_ids, seed)

    result = evaluate_procedure(bundle, spec, wrapped, 7)
    assert result["status"] in {"completed", "partial"}
    assert seen, "fit_select_predictor must be called"
    reserved = set(result["partition"]["folds"][0]["reserved_row_ids"])
    train = set(result["partition"]["folds"][0]["train_row_ids"])
    assert train.isdisjoint(reserved)
    for batch in seen:
        assert set(batch).isdisjoint(reserved)
        assert set(batch) <= train
    assert result["usable_for_model_selection"] is False
    assert result["winner_retrained_on_full_data"] is False
    assert result["reserved_filtered_by_error"] is False


def test_correct_procedure_does_not_encode_holdout_category_or_full_mean():
    bundle, spec = _temporal_bundle_with_holdout_only_category()
    fit = labeled_fit_select_predictor(bundle, spec, leak=False)
    result = evaluate_procedure(bundle, spec, fit, 7)

    fold = result["partition"]["folds"][0]
    train_ids = fold["train_row_ids"]
    reserved_ids = fold["reserved_row_ids"]
    assert train_ids
    assert reserved_ids
    assert set(train_ids).isdisjoint(set(reserved_ids))

    parsed = bundle["parsed_frame"]
    train_bairros = set(parsed.loc[parsed["row_id"].isin(train_ids), "bairro"])
    reserved_bairros = set(parsed.loc[parsed["row_id"].isin(reserved_ids), "bairro"])
    holdout_only = reserved_bairros - train_bairros
    assert "LEAK_CAT" in holdout_only

    train_area = parsed.loc[parsed["row_id"].isin(train_ids), "area"].astype(float)
    train_mean = float(train_area.mean())

    trace = result["fold_traces"][0]["trace"]
    report = detect_preprocessing_leak(
        trace,
        reserved_row_ids=reserved_ids,
        holdout_only_categories={"bairro": ["LEAK_CAT"]},
        train_only_impute={"area": train_mean},
    )
    assert report["leaked"] is False, report
    assert "LEAK_CAT" not in (trace.get("categories") or {}).get("bairro", [])
    assert fit.contract_fixture_label == CONTRACT_FIXTURE_LABEL


def test_sentinel_detects_leaky_imputation_and_category():
    bundle, spec = _temporal_bundle_with_holdout_only_category()
    leaky = labeled_fit_select_predictor(bundle, spec, leak=True)
    result = evaluate_procedure(bundle, spec, leaky, 7)

    fold = result["partition"]["folds"][0]
    train_ids = fold["train_row_ids"]
    reserved_ids = fold["reserved_row_ids"]
    parsed = bundle["parsed_frame"]
    train_mean = float(parsed.loc[parsed["row_id"].isin(train_ids), "area"].astype(float).mean())
    full_mean = float(parsed["area"].astype(float).mean())
    assert abs(full_mean - train_mean) > 1.0

    trace = result["fold_traces"][0]["trace"]
    report = detect_preprocessing_leak(
        trace,
        reserved_row_ids=reserved_ids,
        holdout_only_categories={"bairro": ["LEAK_CAT"]},
        train_only_impute={"area": train_mean},
    )
    assert report["leaked"] is True, report
    kinds = {item["kind"] for item in report["leaks"]}
    assert "holdout_category_in_encoder" in kinds or "impute_not_train_only" in kinds or "used_reserved_rows" in kinds
    assert "LEAK_CAT" in (trace.get("categories") or {}).get("bairro", [])
    # evaluate_procedure itself still did not pass reserved ids.
    # The leak is inside the callback closing over the bundle — the sentinel catches it.
    used = set(trace.get("used_row_ids") or [])
    assert used & set(reserved_ids)


def test_reserved_rows_are_not_dropped_for_large_residual():
    bundle, spec = _temporal_bundle_with_holdout_only_category()
    fit = labeled_fit_select_predictor(bundle, spec, leak=False)
    result = evaluate_procedure(bundle, spec, fit, 7)
    reserved = result["coverage"]["reserved_row_ids"]
    predicted_ids = [p["row_id"] for p in result["predictions"]]
    assert set(reserved) <= set(predicted_ids)
    # Failures stay in the coverage denominator; they are not deleted because error is large.
    assert result["coverage"]["failed_remain_in_denominator"] is True
    assert result["metrics"]["n_reserved"] == len(reserved)
