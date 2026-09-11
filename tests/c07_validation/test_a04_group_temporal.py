"""C07-A04: group/time splits do not cross; seed reproduces; no invented groups."""

from __future__ import annotations

from datetime import date, timedelta

from modules.model_evaluation import evaluate_procedure

from contract_fixtures import (
    labeled_fit_select_predictor,
    make_input_bundle,
    make_request_spec,
)


def _duplicate_property_rows():
    rows = []
    idx = 0
    for prop in range(12):
        for copy in range(2):
            area = 60.0 + prop * 8
            rows.append(
                {
                    "row_id": f"p{prop:02d}c{copy}",
                    "property_id": f"imovel-{prop:02d}",
                    "area": area + copy,
                    "quartos": 1 + (prop % 4),
                    "bairro": "Centro" if prop % 2 == 0 else "Norte",
                    "preco": 1000.0 * area + 70000.0,
                }
            )
            idx += 1
    return rows


def test_group_split_keeps_duplicate_properties_on_one_side_and_is_reproducible():
    bundle = make_input_bundle(_duplicate_property_rows(), input_sha256="synthetic-group")
    spec = make_request_spec(
        roles={
            "preco": "target",
            "area": "predictor",
            "quartos": "predictor",
            "bairro": "predictor",
            "property_id": "source",
            "row_id": "identifier",
        },
        evaluation_policy={
            "method": "group",
            "group_column": "property_id",
            "test_size": 0.25,
            "n_splits": 1,
            "mode": "fast",
            "stability": False,
        },
    )
    fit = labeled_fit_select_predictor(bundle, spec, leak=False)
    a = evaluate_procedure(bundle, spec, fit, 21)
    b = evaluate_procedure(bundle, spec, fit, 21)
    c = evaluate_procedure(bundle, spec, fit, 22)

    fold_a = a["partition"]["folds"][0]
    fold_b = b["partition"]["folds"][0]
    assert fold_a["train_row_ids"] == fold_b["train_row_ids"]
    assert fold_a["reserved_row_ids"] == fold_b["reserved_row_ids"]
    assert a["partition"]["invented_groups"] is False
    assert a["partition"]["group_column"] == "property_id"

    parsed = bundle["parsed_frame"].set_index("row_id")
    train_groups = {parsed.loc[rid, "property_id"] for rid in fold_a["train_row_ids"]}
    reserved_groups = {parsed.loc[rid, "property_id"] for rid in fold_a["reserved_row_ids"]}
    assert train_groups.isdisjoint(reserved_groups)
    assert fold_a["group_ids_train"] is not None
    assert set(fold_a["group_ids_train"]) == train_groups
    assert set(fold_a["group_ids_reserved"]) == reserved_groups

    # Same seed, same partition; a different seed is allowed to differ.
    fold_c = c["partition"]["folds"][0]
    assert fold_c["train_row_ids"] != fold_a["train_row_ids"] or fold_c["reserved_row_ids"] != fold_a["reserved_row_ids"]


def test_temporal_split_does_not_put_the_future_in_train():
    rows = []
    start = date(2019, 6, 1)
    for i in range(30):
        rows.append(
            {
                "row_id": f"d{i:03d}",
                "area": float(50 + i),
                "quartos": 2,
                "bairro": "Centro",
                "preco": 1000.0 * (50 + i) + 50000.0,
                "data": (start + timedelta(days=10 * i)).isoformat(),
            }
        )
    bundle = make_input_bundle(rows, input_sha256="synthetic-temporal")
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
            "test_size": 0.3,
            "n_splits": 1,
            "mode": "fast",
            "stability": False,
        },
    )
    fit = labeled_fit_select_predictor(bundle, spec, leak=False)
    first = evaluate_procedure(bundle, spec, fit, 9)
    second = evaluate_procedure(bundle, spec, fit, 9)
    fold = first["partition"]["folds"][0]
    assert fold["train_row_ids"] == second["partition"]["folds"][0]["train_row_ids"]
    assert fold["reserved_row_ids"] == second["partition"]["folds"][0]["reserved_row_ids"]

    parsed = bundle["parsed_frame"].set_index("row_id")
    train_dates = [parsed.loc[rid, "data"] for rid in fold["train_row_ids"]]
    reserved_dates = [parsed.loc[rid, "data"] for rid in fold["reserved_row_ids"]]
    assert train_dates and reserved_dates
    assert max(train_dates) <= min(reserved_dates)
    assert set(train_dates).isdisjoint(set(reserved_dates))
    assert first["partition"]["time_column"] == "data"
    assert fold["time_cut"] is not None


def test_without_group_metadata_groups_are_not_invented():
    rows = []
    for i in range(20):
        rows.append(
            {
                "row_id": f"x{i:03d}",
                "area": float(40 + i),
                "quartos": 2,
                "bairro": "Centro",
                "preco": 800.0 * (40 + i) + 40000.0,
            }
        )
    bundle = make_input_bundle(rows, input_sha256="synthetic-nometadata")
    spec = make_request_spec(
        evaluation_policy={
            "method": "random",
            "test_size": 0.25,
            "n_splits": 1,
            "mode": "fast",
            "stability": False,
        }
    )
    fit = labeled_fit_select_predictor(bundle, spec, leak=False)
    result = evaluate_procedure(bundle, spec, fit, 4)
    assert result["partition"]["invented_groups"] is False
    assert result["partition"]["group_column"] is None
    assert result["partition"]["folds"][0]["group_ids_train"] is None
    assert result["status"] == "completed"


def test_group_method_without_column_does_not_invent_and_does_not_evaluate_silently():
    rows = [
        {
            "row_id": f"g{i:03d}",
            "area": float(50 + i),
            "quartos": 2,
            "bairro": "Centro",
            "preco": 1000.0 * (50 + i),
        }
        for i in range(16)
    ]
    bundle = make_input_bundle(rows, input_sha256="synthetic-group-missing")
    spec = make_request_spec(
        evaluation_policy={
            "method": "group",
            "test_size": 0.25,
            "n_splits": 1,
            "mode": "fast",
            "stability": False,
        }
    )
    fit = labeled_fit_select_predictor(bundle, spec, leak=False)
    result = evaluate_procedure(bundle, spec, fit, 4)
    assert result["partition"]["invented_groups"] is False
    assert result["status"] == "error"
    codes = {issue["code"] for issue in result["issues"]}
    assert "c07.no_group_metadata" in codes
    assert result["metrics"]["mae"] is None
