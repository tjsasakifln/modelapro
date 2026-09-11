"""Boundary cases: undeclared policy, high cardinality encoded not refused."""

from __future__ import annotations

from modules.preprocessing import fit_dataset

from .fixtures import mp1_bundle, mp1_request_spec


def test_undeclared_missing_policy_is_structured_error():
    rows = [
        {"row_id": "t1", "bairro": "Centro", "area": 10.0, "valor": 100.0, "id_imovel": "A1"},
        {"row_id": "t2", "bairro": "Norte", "area": 20.0, "valor": 200.0, "id_imovel": "A2"},
    ]
    spec = mp1_request_spec()
    spec.pop("missing_policy")
    prepared = fit_dataset(mp1_bundle(rows), spec)
    assert any(i["code"] == "missing_policy_undeclared" and i["severity"] == "error" for i in prepared.issues)
    assert prepared.row_ids == []


def test_high_cardinality_is_encoded_not_refused():
    rows = []
    for i in range(25):
        rows.append(
            {
                "row_id": f"t{i}",
                "bairro": f"B{i}",
                "area": float(50 + i),
                "valor": float(1000 + i),
                "id_imovel": f"A{i}",
            }
        )
    prepared = fit_dataset(mp1_bundle(rows), mp1_request_spec())
    assert "bairro" in prepared.feature_schema["groups"]
    n_ind = len(prepared.feature_schema["groups"]["bairro"]["columns"])
    assert n_ind == 24  # 25 levels, one reference
    assert n_ind == prepared.X.shape[1] - 1  # plus area
    assert any(i["code"] == "high_cardinality" for i in prepared.issues)
    assert not any("impossibilidade" in (i["message"] or "").lower() and i["severity"] == "error" for i in prepared.issues)
