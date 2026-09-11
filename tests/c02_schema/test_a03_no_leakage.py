"""C02-A03: encoder/imputation/categories fit only on train_row_ids."""

from __future__ import annotations

from modules.preprocessing import fit_dataset, transform_subject

from .fixtures import mp1_bundle, mp1_request_spec


def test_a03_reserved_extreme_does_not_leak_into_train_schema():
    # Independent expected mean from the TRAIN literals only: (10+20+30)/3 = 20.
    train_areas = [10.0, 20.0, 30.0]
    expected_train_mean = (10.0 + 20.0 + 30.0) / 3.0
    reserved_area = 1_000_000.0
    reserved_category = "ZonaReservada"

    rows = [
        {"row_id": "t1", "bairro": "Centro", "area": train_areas[0], "valor": 100.0, "id_imovel": "A1"},
        {"row_id": "t2", "bairro": "Norte", "area": train_areas[1], "valor": 200.0, "id_imovel": "A2"},
        {"row_id": "t3", "bairro": "Sul", "area": train_areas[2], "valor": 300.0, "id_imovel": "A3"},
        {"row_id": "t4", "bairro": "Centro", "area": None, "valor": 150.0, "id_imovel": "A4"},
        {"row_id": "t5", "bairro": "Centro", "area": 40.0, "valor": None, "id_imovel": "A5"},
        {"row_id": "h1", "bairro": reserved_category, "area": reserved_area, "valor": 999.0, "id_imovel": "H1"},
    ]
    train_ids = ["t1", "t2", "t3", "t4", "t5"]
    spec = mp1_request_spec(
        missing_policy={"target": "never_impute", "predictors": "mean"},
        roles={
            "valor": "target",
            "bairro": "predictor",
            "area": "predictor",
            "id_imovel": "identifier",
        },
    )
    bundle = mp1_bundle(rows)
    prepared = fit_dataset(bundle, spec, train_row_ids=train_ids)

    bairro_bv = next(
        bv for bv in prepared.encoder_state["base_variables"] if bv["original_name"] == "bairro"
    )
    seen = set(bairro_bv["categories"] or [])
    assert reserved_category not in seen
    assert seen <= {"Centro", "Norte", "Sul"}

    area_bv = next(
        bv for bv in prepared.encoder_state["base_variables"] if bv["original_name"] == "area"
    )
    assert area_bv["impute_value"] == expected_train_mean
    assert area_bv["train_mean"] == expected_train_mean

    # Missing-target train row is not filled and not used.
    assert "t5" not in prepared.row_ids
    assert prepared.y.isna().sum() == 0

    # Held-out row is not in the used sample.
    assert "h1" not in prepared.row_ids
    assert "h1" in prepared.sample_ledger["excluded_row_ids"]

    subject_missing_area = transform_subject(
        {"bairro": "Centro", "area": None},
        prepared.feature_schema,
        prepared.encoder_state,
    )
    assert subject_missing_area.X.iloc[0]["area"] == expected_train_mean

    train_only_rows = [r for r in rows if r["row_id"] in {"t1", "t2", "t3", "t4", "t5"}]
    prepared_only = fit_dataset(mp1_bundle(train_only_rows), spec, train_row_ids=None)
    assert list(prepared.feature_schema["columns"].keys()) == list(
        prepared_only.feature_schema["columns"].keys()
    )
    only_bairro = next(
        bv for bv in prepared_only.encoder_state["base_variables"] if bv["original_name"] == "bairro"
    )
    assert set(only_bairro["categories"] or []) == seen
    only_area = next(
        bv for bv in prepared_only.encoder_state["base_variables"] if bv["original_name"] == "area"
    )
    assert only_area["train_mean"] == expected_train_mean


def test_a03_empty_candidate_cols_is_explicit_error():
    rows = [
        {"row_id": "t1", "bairro": "Centro", "area": 10.0, "valor": 100.0, "id_imovel": "A1"},
        {"row_id": "t2", "bairro": "Norte", "area": 20.0, "valor": 200.0, "id_imovel": "A2"},
    ]
    spec = mp1_request_spec(candidate_cols=[])
    prepared = fit_dataset(mp1_bundle(rows), spec)
    assert any(i["code"] == "empty_candidates" and i["severity"] == "error" for i in prepared.issues)
    assert prepared.X.empty or list(prepared.X.columns) == []
    assert prepared.row_ids == []
