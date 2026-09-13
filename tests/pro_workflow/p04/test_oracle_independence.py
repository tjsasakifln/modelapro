"""Oracle independence and convention checks. No product helper under test."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import numpy as np
import pytest

from tests.fixtures.pro_workflow import ols_oracle as oracle

ORACLE_PATH = Path(inspect.getfile(oracle)).resolve()
FORBIDDEN_IMPORT_PREFIXES = ("modules.", "backend.", "frontend.")


def test_oracle_source_does_not_import_product():
    tree = ast.parse(ORACLE_PATH.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    product = {"modules", "backend", "frontend"}
    bad = [name for name in imported if name.startswith(FORBIDDEN_IMPORT_PREFIXES) or name in product]
    assert not bad, f"oracle imports product code: {bad}"


def test_qr_ols_matches_statsmodels_mean_and_prediction_interval():
    x = np.linspace(10.0, 40.0, 30)
    rng = np.random.default_rng(20260911)
    y = 1000.0 * x + rng.normal(0.0, 50.0, size=x.shape)
    cols = {"area": x.tolist()}
    fit = oracle.fit_ols(y, cols)
    pred = oracle.predict_intervals(fit, {"area": 22.5})
    sm = oracle.statsmodels_crosscheck(y, cols, {"area": 22.5})
    assert oracle.close(pred["point"], sm["point"], abs_tol=1e-8, rel_tol=1e-8)
    assert oracle.interval_close(pred["mean_ci"], sm["mean_ci"], abs_tol=1e-6, rel_tol=1e-8)
    assert oracle.interval_close(pred["prediction_interval"], sm["prediction_interval"], abs_tol=1e-6, rel_tol=1e-8)
    width_mean = pred["mean_ci"]["upper"] - pred["mean_ci"]["lower"]
    width_pred = pred["prediction_interval"]["upper"] - pred["prediction_interval"]["lower"]
    assert width_pred > width_mean
    assert pred["mean_ci"]["level"] == 0.80
    assert pred["convention"] == "two_sided_student_t"


def test_percent_band_is_not_a_statistical_interval():
    x = [10.0, 20.0, 30.0, 40.0]
    y = [10.0, 20.0, 30.0, 40.0]
    fit = oracle.fit_ols(y, {"area": x})
    pred = oracle.predict_intervals(fit, {"area": 25.0})
    point = pred["point"]
    band = {"lower": point * 0.9, "upper": point * 1.1}
    assert not oracle.interval_close(band, pred["mean_ci"], abs_tol=1e-9, rel_tol=0.0)


def test_unknown_category_is_unsupported_not_reference():
    encoded = oracle.encode_treatment(
        ["Centro", "Sul", "Centro", "Industrial"],
        training_mask=[True, True, True, False],
        column="bairro",
    )
    assert encoded["reference"] == "Centro"
    assert "Industrial" not in encoded["levels"]
    assert encoded["supported"] == [True, True, True, False]
    assert encoded["columns"]["bairro=Sul"] == [0.0, 1.0, 0.0, 0.0]


def test_holdout_partition_is_deterministic_and_independent():
    ids = [f"HO-{i + 1:03d}" for i in range(40)]
    a = oracle.holdout_reserved_ids(ids, seed=17, test_size=0.2)
    b = oracle.holdout_reserved_ids(ids, seed=17, test_size=0.2)
    c = oracle.holdout_reserved_ids(ids, seed=18, test_size=0.2)
    assert a == b
    assert a != c
    assert 1 <= len(a) <= 39
    assert set(a).issubset(set(ids))


def test_cook_distance_flags_the_planted_outlier():
    x = np.linspace(50.0, 89.0, 40)
    y = 1000.0 * x
    y[7] = 2_400_000.0
    fit = oracle.fit_ols(y, {"area": x.tolist()})
    d = oracle.cook_distance(fit)
    assert int(np.argmax(d)) == 7


def test_faixa_and_efeito_are_distinct():
    assert oracle.faixa_ampliada(90.0, 50.0, 100.0) == "in_sample"
    assert oracle.faixa_ampliada(150.0, 50.0, 100.0) == "extended"
    assert oracle.faixa_ampliada(250.0, 50.0, 100.0) == "outside_extended"
    assert oracle.efeito_monetario(150000.0, 50000.0, 100000.0) == "price_outside_sample"
    assert oracle.efeito_monetario(90000.0, 50000.0, 100000.0) == "price_in_sample"


def test_oracle_rejects_rank_deficient_design():
    with pytest.raises(oracle.OracleError):
        oracle.fit_ols([1.0, 2.0, 3.0], {"a": [1.0, 1.0, 1.0], "b": [1.0, 1.0, 1.0]})
