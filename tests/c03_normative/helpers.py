"""Synthetic labeled fixtures for C03. Not market data."""


def area_times_10000(subject):
    """Analytical original-unit pipeline: y = 10000 × área."""
    return 10000.0 * float(subject["area"])


def linear_predict(intercept, slopes):
    def predict(subject):
        total = float(intercept)
        for name, slope in slopes.items():
            total += float(slope) * float(subject[name])
        return total

    return predict


def a01_axes():
    return [
        {
            "name": "area",
            "kind": "quantitative",
            "avaliando_value": 150.0,
            "sample_min": 50.0,
            "sample_max": 100.0,
            "unit": "m2",
        }
    ]


def a01_context(**overrides):
    ctx = {
        "n": 20,
        "k": 1,
        "intercept": True,
        "subject_raw": {"area": 150.0},
        "predict_original": area_times_10000,
        "axes": a01_axes(),
        "pvalues": {"area": 0.01, "const": 0.01},
        "f_pvalue": 0.001,
        "amplitude_pct": 25.0,
        "documentary": {
            "item1": {"grade": 1, "provenance": {"source": "synthetic-test", "method": "declared"}},
            "item3": {"grade": 1, "provenance": {"source": "synthetic-test", "method": "declared"}},
        },
        "statistical": {"r2_adjusted": 0.8, "vif": {"area": 1.2, "const": 1.0}},
        "estimand": "market_value",
        "adopted_estimator": "central_tendency",
        "central_estimate": 1_500_000.0,
        "mean_ci80": {"lower": 1_400_000.0, "upper": 1_600_000.0},
    }
    ctx.update(overrides)
    return ctx


def independent_boundary_delta(avaliando, frontier, predict):
    y_av = predict({"area": avaliando})
    y_fr = predict({"area": frontier})
    return abs(y_av - y_fr) / abs(y_fr) * 100.0
