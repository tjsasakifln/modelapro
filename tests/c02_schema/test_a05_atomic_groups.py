"""C02-A05: indicator groups stay atomic; free parameters and n are traceable."""

from __future__ import annotations

from modules.preprocessing import fit_dataset

from .fixtures import a01_rows, mp1_bundle, mp1_request_spec


def test_a05_groups_are_atomic_and_parameter_counts_are_traceable():
    rows = a01_rows()
    prepared = fit_dataset(mp1_bundle(rows), mp1_request_spec())

    groups = prepared.feature_schema["groups"]
    assert "bairro" in groups
    group = groups["bairro"]
    assert group["base_variable"] == "bairro"
    indicator_cols = group["columns"]
    assert len(indicator_cols) == 2

    for col in indicator_cols:
        meta = prepared.feature_schema["columns"][col]
        assert meta["group_id"] == "bairro"
        assert meta["kind"] == "categorical"
        assert meta["original_name"] == "bairro"
        assert meta["reference_category"] == "Centro"
        assert set(meta["categories"]) == {"Centro", "Norte", "Sul"}

    # Group is not split across unrelated names.
    for name, meta in prepared.feature_schema["columns"].items():
        if meta.get("group_id") == "bairro":
            assert name in indicator_cols
            assert name.startswith("bairro_")

    accounting = prepared.feature_schema["parameter_accounting"]
    assert accounting["n_effective"] == len(rows)
    assert accounting["n_categorical_groups"] == 1
    assert accounting["n_indicator_columns"] == 2
    assert accounting["n_quantitative"] == 1
    assert accounting["n_free_slopes"] == 3  # area + 2 indicators
    assert accounting["groups"]["bairro"]["n_free_parameters"] == 2
    assert accounting["groups"]["bairro"]["atomic"] is True
    assert accounting["groups"]["bairro"]["support"]["Centro"] == 3

    ledger = prepared.sample_ledger
    assert ledger["received"] == len(rows)
    assert ledger["used"] == len(rows)
    assert ledger["n_effective"] == len(rows)
    assert ledger["excluded"] == 0
    assert ledger["used_row_ids"] == [r["row_id"] for r in rows]
    assert ledger["n_free_slopes"] == 3
