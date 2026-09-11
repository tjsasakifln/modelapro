"""Composed predict_original over a tiny OLS pipeline (not a full search)."""

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from modules.nbr14653_validation import assess_normative
from modules.normative_rules import classify_item4_extrapolacao

from .helpers import independent_boundary_delta


def test_composed_ols_pipeline_original_unit_matches_analytical_a01():
    area = np.linspace(50.0, 100.0, 20)
    y = 10000.0 * area
    df = pd.DataFrame({"area": area, "y": y})
    X = sm.add_constant(df["area"])
    model = sm.OLS(df["y"], X).fit()

    def predict_original(subject):
        row = pd.DataFrame([{"const": 1.0, "area": float(subject["area"])}])
        return float(model.predict(row).iloc[0])

    axes = [
        {
            "name": "area",
            "kind": "quantitative",
            "avaliando_value": 150.0,
            "sample_min": float(df["area"].min()),
            "sample_max": float(df["area"].max()),
        }
    ]
    expected = independent_boundary_delta(150.0, 100.0, lambda s: 10000.0 * s["area"])
    result = classify_item4_extrapolacao(
        axes, subject_raw={"area": 150.0}, predict_original=predict_original
    )
    assert result["calculation"]["boundary_delta_pct"] == pytest.approx(expected, rel=1e-6)
    assert result["grade"] == 0

    assessment = assess_normative(
        {
            "n": 20,
            "k": 1,
            "intercept": True,
            "axes": axes,
            "subject_raw": {"area": 150.0},
            "predict_original": predict_original,
            "pvalues": {"area": 0.01, "const": 0.01},
            "f_pvalue": 0.001,
            "amplitude_pct": 20.0,
            "documentary": {
                "item1": {"grade": 1, "provenance": {"source": "synthetic-ols"}},
                "item3": {"grade": 1, "provenance": {"source": "synthetic-ols"}},
            },
        }
    )
    item4 = next(i for i in assessment["fundamentacao"]["items"] if i["item"] == 4)
    assert item4["grade"] == 0
    assert item4["calculation"]["boundary_delta_pct"] == pytest.approx(expected, rel=1e-6)
