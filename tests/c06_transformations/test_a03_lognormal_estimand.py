"""C06-A03: log inverse respects the declared estimand on a synthetic lognormal."""
import numpy as np

from modules.target_transform import (
    fit_target_transform,
    inverse_target_prediction,
    transform_target,
)


def test_lognormal_median_and_mean_are_not_interchanged():
    rng = np.random.default_rng(20260911)
    mu = 1.0
    sigma = 0.5
    analytic_median = float(np.exp(mu))
    analytic_mean = float(np.exp(mu + (sigma ** 2) / 2.0))
    assert analytic_median != analytic_mean

    y = rng.lognormal(mean=mu, sigma=sigma, size=8000)
    state = fit_target_transform(y, "log")
    z = np.asarray(transform_target(y, state), dtype=float)
    log_scale_mean = float(np.mean(z))

    inv_default = inverse_target_prediction(log_scale_mean, state)
    default_point = float(np.asarray(inv_default["point"]).reshape(-1)[0])

    assert inv_default["estimand"] == "exp(E[log Y|X])"
    assert np.isclose(default_point, float(np.exp(log_scale_mean)), rtol=1e-12)
    assert np.isclose(default_point, analytic_median, rtol=0.05)
    assert not np.isclose(default_point, analytic_mean, rtol=0.01)
    assert inv_default["estimand"] != "E[Y|X]"

    train_resid = z - log_scale_mean
    inv_mean = inverse_target_prediction(
        log_scale_mean,
        state,
        residual_context={
            "origin": "train",
            "residuals": train_resid,
            "correction": "lognormal",
        },
    )
    mean_point = float(np.asarray(inv_mean["point"]).reshape(-1)[0])
    assert inv_mean["estimand"] == "E[Y|X]"
    assert inv_mean["method"] == "lognormal_mean"
    assert np.isclose(mean_point, analytic_mean, rtol=0.05)
    assert mean_point != default_point
    assert inv_mean["value"]["mean_ci80"] is None

    inv_smear = inverse_target_prediction(
        log_scale_mean,
        state,
        residual_context={
            "origin": "train",
            "residuals": train_resid,
            "correction": "smearing",
        },
    )
    assert inv_smear["method"] == "smearing"
    assert inv_smear["estimand"] == "E[Y|X]"
    assert inv_smear["method"] != inv_default["method"]
    assert inv_smear["method"] != inv_mean["method"]


def test_exponentiated_log_interval_is_not_mean_ci80():
    y = np.array([1.0, 2.0, 4.0, 8.0])
    state = fit_target_transform(y, "log")
    pred = {"point": 1.0, "mean_ci80": {"lower": 0.5, "upper": 1.5}}
    inv = inverse_target_prediction(pred, state)
    assert inv["value"]["mean_ci80"] is None
    assert inv["estimand"] == "exp(E[log Y|X])"
    assert inv.get("interval_interpretation") != "mean_ci80"
    assert float(np.asarray(inv["point"]).reshape(-1)[0]) == float(np.exp(1.0))
