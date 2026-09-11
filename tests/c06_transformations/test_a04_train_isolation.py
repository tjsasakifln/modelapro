"""C06-A04: train-only state; holdout must not mutate or supply corrections."""
import copy

import numpy as np

from modules.target_transform import (
    fit_target_transform,
    inverse_target_prediction,
    transform_target,
)


def test_reserved_sample_does_not_mutate_train_state():
    rng = np.random.default_rng(11)
    train = np.exp(rng.normal(1.0, 0.3, size=40))
    reserved = np.exp(rng.normal(3.0, 1.2, size=40))
    state = fit_target_transform(train, "log")
    snapshot = copy.deepcopy(state)

    other = fit_target_transform(reserved, "log")
    transform_target(reserved, state)
    inverse_target_prediction(np.mean(np.log(reserved)), state)

    assert state == snapshot
    assert other is not state
    assert other.get("parameters") != state.get("parameters") or other["n_train"] == len(reserved)


def test_holdout_residuals_are_not_used_for_correction():
    rng = np.random.default_rng(12)
    train = rng.lognormal(mean=1.0, sigma=0.4, size=200)
    reserved = rng.lognormal(mean=1.0, sigma=0.4, size=200)
    state = fit_target_transform(train, "log")
    z_train = np.asarray(transform_target(train, state), dtype=float)
    pred = float(np.mean(z_train))
    train_resid = z_train - pred
    z_hold = np.asarray(transform_target(reserved, state), dtype=float)
    hold_resid = z_hold - float(np.mean(z_hold))

    baseline = inverse_target_prediction(pred, state)
    with_holdout = inverse_target_prediction(
        pred,
        state,
        residual_context={
            "origin": "holdout",
            "residuals": hold_resid,
            "correction": "lognormal",
        },
    )
    with_train = inverse_target_prediction(
        pred,
        state,
        residual_context={
            "origin": "train",
            "residuals": train_resid,
            "correction": "lognormal",
        },
    )

    assert float(np.asarray(with_holdout["point"]).reshape(-1)[0]) == float(
        np.asarray(baseline["point"]).reshape(-1)[0]
    )
    assert with_holdout["estimand"] == baseline["estimand"]
    assert with_holdout["method"] != "lognormal_mean"
    assert with_train["method"] == "lognormal_mean"
    assert float(np.asarray(with_train["point"]).reshape(-1)[0]) != float(
        np.asarray(baseline["point"]).reshape(-1)[0]
    )
    assert state["parameters"] == copy.deepcopy(state)["parameters"]


def test_unvalidated_interval_is_not_labeled_mean_ci80():
    y = np.array([2.0, 4.0, 8.0, 16.0])
    state = fit_target_transform(y, "log")
    inv = inverse_target_prediction(
        {"point": 1.2, "mean_ci80": {"lower": 0.8, "upper": 1.6}},
        state,
    )
    assert inv["value"]["mean_ci80"] is None
    assert inv["precisao"]["status"] in {"not_computed", "unclassified"}
    assert inv["precisao"].get("grade") is None
    assert inv["normative_classification"]["status"] == "unavailable"
