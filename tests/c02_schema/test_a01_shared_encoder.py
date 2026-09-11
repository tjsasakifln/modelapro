"""C02-A01: one encoder for sample and subject; original values, not dummies."""

from __future__ import annotations

import pandas as pd

from modules.preprocessing import fit_dataset, transform_subject

from .fixtures import a01_rows, mp1_bundle, mp1_request_spec


def _bairro_meta(prepared):
    groups = prepared.feature_schema["groups"]
    assert "bairro" in groups, "grupo categórico 'bairro' desapareceu do esquema"
    columns = groups["bairro"]["columns"]
    ref = None
    categories = None
    for _name, meta in prepared.feature_schema["columns"].items():
        if meta.get("group_id") == "bairro":
            ref = meta.get("reference_category")
            categories = meta.get("categories")
            break
    return columns, ref, categories


def test_a01_bairro_and_formatted_numeric_share_encoder():
    bundle = mp1_bundle(a01_rows())
    spec = mp1_request_spec()
    prepared = fit_dataset(bundle, spec)

    assert not prepared.X.empty
    assert all(pd.api.types.is_numeric_dtype(prepared.X[c]) for c in prepared.X.columns)

    assert "id_imovel" not in prepared.X.columns
    assert "row_id" not in prepared.X.columns
    assert "data_anuncio" not in prepared.X.columns
    assert "bairro" not in prepared.X.columns

    indicator_cols, reference, categories = _bairro_meta(prepared)
    assert reference == "Centro"
    assert set(categories) == {"Centro", "Norte", "Sul"}
    assert indicator_cols
    assert all(c in prepared.X.columns for c in indicator_cols)
    # reference dropped: 3 levels → 2 indicators
    assert len(indicator_cols) == 2

    # independent pt-BR parse of the fixture literal "1.234,56"
    expected_area = 1234.56
    assert prepared.X.loc["r3", "area"] == expected_area

    # subject uses original names (bairro="Centro"), never bairro_Centro=1
    subject = transform_subject(
        {"bairro": "Centro", "area": "1.234,56"},
        prepared.feature_schema,
        prepared.encoder_state,
    )
    assert list(subject.X.columns) == list(prepared.X.columns)
    assert subject.supported is True
    assert subject.X.iloc[0]["area"] == expected_area
    assert list(subject.X.iloc[0][indicator_cols]) == [0.0] * len(indicator_cols)
    assert "bairro_Centro" not in subject.raw_values
    assert subject.raw_values["bairro"] == "Centro"

    norte = transform_subject(
        {"bairro": "Norte", "area": "100,00"},
        prepared.feature_schema,
        prepared.encoder_state,
    )
    assert norte.supported is True
    assert float(norte.X.iloc[0][indicator_cols].sum()) == 1.0

    date_pending = [i for i in prepared.issues if i["code"] == "date_pending"]
    assert date_pending
    ident = [i for i in prepared.issues if i["code"] == "identifier_excluded"]
    assert ident
