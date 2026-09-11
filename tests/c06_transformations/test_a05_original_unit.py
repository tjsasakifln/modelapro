"""C06-A05: consumers receive original-unit values; identity is not regressed."""
import numpy as np
import pandas as pd

from modules.target_transform import (
    fit_target_transform,
    inverse_target_prediction,
    transform_target,
)
from modules.transformations import Transformer


def test_inverse_declares_original_unit_and_limitations():
    y = np.array([100000.0, 250000.0, 400000.0])
    state = fit_target_transform(y, "log")
    z = transform_target(y, state)
    inv = inverse_target_prediction(z, state)
    assert inv["unit"] == "original"
    assert inv["comparison_scale"] == "original"
    assert inv["estimand"]
    assert inv["method"]
    assert inv["assumptions"]
    assert inv["limitations"]
    assert state["inverse"]["invocation"] == "modules.target_transform.inverse_target_prediction"
    assert state["domain"]["requires_positive"] is True
    np.testing.assert_allclose(np.asarray(inv["point"], dtype=float), y, rtol=1e-12)


def test_identity_matches_untransformed_legacy_y():
    y = np.array([10.0, 20.0, 30.0, 0.0, -4.0])
    state = fit_target_transform(y, "identity")
    z = transform_target(y, state)
    inv = inverse_target_prediction(
        {"point": 21.0, "mean_ci80": {"lower": 18.0, "upper": 24.0}},
        state,
    )
    np.testing.assert_allclose(np.asarray(z, dtype=float), y)
    assert float(inv["point"]) == 21.0
    assert inv["estimand"] == "E[Y|X]"
    assert inv["value"]["mean_ci80"] == {"lower": 18.0, "upper": 24.0}
    assert inv["normative_classification"]["status"] != "unavailable"
    assert state["domain"]["includes_zero"] is True
    assert state["inverse"]["invocation"] == "modules.target_transform.inverse_target_prediction"


def test_sqrt_on_x_still_works_when_log_y_interval_is_experimental():
    x = pd.Series([0.0, 1.0, 4.0])
    transformed, success = Transformer.apply_transformation(x, "sqrt")
    assert success is True
    np.testing.assert_allclose(transformed.to_numpy(dtype=float), [0.0, 1.0, 2.0])

    y = np.array([1.0, 2.0, 4.0])
    state = fit_target_transform(y, "log")
    inv = inverse_target_prediction(
        {"point": 0.0, "mean_ci80": {"lower": -0.1, "upper": 0.1}},
        state,
    )
    assert inv["normative_classification"]["status"] == "unavailable"
    assert inv["value"]["mean_ci80"] is None


def test_x_normality_is_not_a_quality_ranking():
    rng = np.random.default_rng(7)
    series = pd.Series(rng.lognormal(0.0, 0.8, size=40))
    results = Transformer.test_transformations(series, "x")
    names = [r.transformation_type for r in results]
    expected = [n for n in Transformer.TRANSFORMATIONS if n in names]
    assert names == expected
    p_after = [r.normality_score_after for r in results]
    ranked_by_p = [n for n, _ in sorted(zip(names, p_after), key=lambda t: t[1], reverse=True)]
    if ranked_by_p != expected:
        assert names != ranked_by_p
