"""Categorical groups stay grouped; domain exclusions are dropped from the space."""
import numpy as np
import pandas as pd

from modules.optimal_combination import search_models
from modules.search_space import parse_feature_name, search_units_from_prepared

from tests.c05_search.helpers import make_prepared, request_spec


def test_categorical_group_is_one_unit_without_indicator_transforms():
    rng = np.random.RandomState(8)
    n = 24
    area = rng.uniform(40, 120, n)
    bairro_a = np.array([1, 0] * (n // 2))
    bairro_b = 1 - bairro_a
    y = 800 * area + 5000 * bairro_a + 20000 + rng.normal(0, 100, n)
    df = pd.DataFrame(
        {"area": area, "bairro_A": bairro_a.astype(float), "bairro_B": bairro_b.astype(float), "y": y}
    )
    groups = {
        "bairro": {"columns": ["bairro_A", "bairro_B"], "base_variable": "bairro"},
    }
    prepared = make_prepared(df, "y", groups=groups)
    # Authorized names include the group base and area.
    prepared["feature_schema"]["columns"]["bairro"] = {
        "original_name": "bairro",
        "role": "predictor",
        "kind": "categorical",
        "unit": None,
        "group_id": "bairro",
        "categories": ["A", "B"],
        "reference_category": "B",
    }
    units, _ = search_units_from_prepared(prepared, ["area", "bairro"])
    kinds = {u.unit_id: u.kind for u in units}
    assert kinds["bairro"] == "group"
    assert kinds["area"] == "quantitative"
    group_unit = next(u for u in units if u.kind == "group")
    assert group_unit.options == ("encoded",)
    spec = request_spec("y", search_policy={"mode": "exact", "budget": 500})
    result = search_models(prepared, None, spec)
    for entry in result["search_audit"]["history"]:
        vars_ = entry.get("variables") or []
        has_a = "bairro_A" in vars_
        has_b = "bairro_B" in vars_
        assert has_a == has_b, "group indicators must be included together"
        for v in vars_:
            trans, base = parse_feature_name(v)
            if base.startswith("bairro"):
                assert trans == "linear"


def test_domain_invalid_transform_for_subject_is_not_in_space():
    rng = np.random.RandomState(1)
    n = 24
    idade = rng.uniform(1, 50, n)
    y = 100 - 2 * idade + rng.normal(0, 1, n)
    df = pd.DataFrame({"idade": idade, "y": y})
    prepared = make_prepared(df, "y")
    subject = {"raw_values": {"idade": 0.0}, "X": None, "issues": [], "supported": True}
    spec = request_spec("y", search_policy={"mode": "exact", "budget": 200})
    result = search_models(prepared, subject, spec)
    for entry in result["search_audit"]["history"]:
        for v in entry.get("variables") or []:
            assert not v.startswith("ln(")
            assert not v.startswith("sqrt(")
            assert not v.startswith("inv_sqrt(")
            assert not v.startswith("inverse(")
            assert not v.startswith("inv_sqr(")
    codes = [i["code"] for i in result["issues"]]
    assert "domain_exclusion" in codes
