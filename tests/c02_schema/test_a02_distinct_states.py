"""C02-A02: unknown, missing, unsupported group and constant are distinct states."""

from __future__ import annotations

from modules.preprocessing import fit_dataset, transform_subject

from .fixtures import mp1_bundle, mp1_request_spec


def test_a02_unknown_missing_unsupported_group_and_constant_are_distinct():
    rows = [
        {"row_id": "r1", "bairro": "Centro", "area": 80.0, "valor": 100000, "id_imovel": "A1", "padrao": "unico", "constante": 5.0, "area_dup": 80.0},
        {"row_id": "r2", "bairro": "Centro", "area": 90.0, "valor": 110000, "id_imovel": "A2", "padrao": "unico", "constante": 5.0, "area_dup": 90.0},
        {"row_id": "r3", "bairro": "Norte", "area": 100.0, "valor": 120000, "id_imovel": "A3", "padrao": "unico", "constante": 5.0, "area_dup": 100.0},
        {"row_id": "r4", "bairro": "Sul", "area": 110.0, "valor": 130000, "id_imovel": "A4", "padrao": "unico", "constante": 5.0, "area_dup": 110.0},
        {"row_id": "r5", "bairro": "Centro", "area": 120.0, "valor": 140000, "id_imovel": "A5", "padrao": "unico", "constante": 5.0, "area_dup": 120.0},
    ]
    spec = mp1_request_spec(
        roles={
            "valor": "target",
            "bairro": "predictor",
            "area": "predictor",
            "id_imovel": "identifier",
            "padrao": "predictor",
            "constante": "predictor",
            "area_dup": "predictor",
        },
        kinds={
            "bairro": "categorical",
            "area": "numeric",
            "padrao": "categorical",
            "constante": "numeric",
            "area_dup": "numeric",
        },
    )
    prepared = fit_dataset(mp1_bundle(rows), spec)

    codes = {i["code"] for i in prepared.issues}
    assert "group_no_support" in codes
    assert "constant_column" in codes
    assert "collinear_columns" in codes
    collinear_issues = [i for i in prepared.issues if i["code"] == "collinear_columns"]
    assert collinear_issues
    assert "area" in prepared.X.columns
    assert "area_dup" in prepared.X.columns
    padrao_issues = [i for i in prepared.issues if i["code"] == "group_no_support" and "padrao" in i["affected_ids"]]
    const_issues = [i for i in prepared.issues if i["code"] == "constant_column"]
    assert padrao_issues
    assert const_issues
    assert padrao_issues[0]["code"] != const_issues[0]["code"]
    assert "padrao" in prepared.feature_schema["groups"]
    assert prepared.feature_schema["groups"]["padrao"]["columns"] == []

    known = {
        "bairro": "Centro",
        "area": 80.0,
        "padrao": "unico",
        "constante": 5.0,
        "area_dup": 80.0,
    }
    reference = transform_subject(known, prepared.feature_schema, prepared.encoder_state)
    assert reference.supported is True

    unknown = transform_subject(
        {**known, "bairro": "ZonaInexistente"},
        prepared.feature_schema,
        prepared.encoder_state,
    )
    missing = transform_subject(
        {"area": 80.0, "padrao": "unico", "constante": 5.0, "area_dup": 80.0},
        prepared.feature_schema,
        prepared.encoder_state,
    )
    assert unknown.supported is False
    assert missing.supported is False
    unk_codes = [i["code"] for i in unknown.issues]
    miss_codes = [i["code"] for i in missing.issues]
    assert "unknown_category" in unk_codes
    assert "predictor_missing" in miss_codes
    assert "unknown_category" not in miss_codes
    assert "predictor_missing" not in unk_codes

    bairro_cols = prepared.feature_schema["groups"]["bairro"]["columns"]
    ref_vals = list(reference.X.iloc[0][bairro_cols])
    unk_vals = list(unknown.X.iloc[0][bairro_cols])
    miss_vals = list(missing.X.iloc[0][bairro_cols])
    assert ref_vals == [0.0] * len(bairro_cols)
    assert unk_vals != ref_vals
    assert miss_vals != ref_vals
    assert all(v != v for v in unk_vals)  # NaN, not reference zeros
    assert all(v != v for v in miss_vals)

    for issue in unknown.issues + missing.issues + padrao_issues + const_issues:
        assert issue["message"]
        assert issue["severity"] in {"info", "warning", "error"}
        assert issue["origin"]
