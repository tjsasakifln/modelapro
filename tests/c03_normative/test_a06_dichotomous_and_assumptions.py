"""NBR 14653-2:2011 Anexo A.5, A.2 a) n_i and A.2 c)/d) on the fitted pipeline.

A variable observed with only two values is dichotomous: Tabela 1 item 4 must
never admit interpolation (0.5) or extrapolation (2) for it, the n_i leg of
micronumerosity must be checked per level, and the homoscedasticity/normality
assumptions must receive p-values from the tests the norm cites.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
from statsmodels.stats.diagnostic import het_white

from modules.model_builder import (
    CandidateSpec,
    _white_test_pvalue,
    evaluate_fitted,
    fit_candidate,
)
from modules.preprocessing import fit_dataset, transform_subject


def _sample(n=60, seed=7, pool_zero=None):
    rng = np.random.default_rng(seed)
    area = rng.uniform(50, 200, n)
    piscina = rng.integers(0, 2, n)
    if pool_zero is not None:
        piscina = np.ones(n, dtype=int)
        piscina[:pool_zero] = 0
    preco = 3000 * area + 40000 * piscina + rng.normal(0, 15000, n)
    frame = pd.DataFrame({"preco": preco, "area": area, "piscina": piscina})
    frame.insert(0, "row_id", [str(i + 1) for i in range(n)])
    return frame


def _assess(frame, subject):
    features = ["area", "piscina"]
    spec = {
        "schema_version": "MP/1",
        "target_col": "preco",
        "candidate_cols": features,
        "roles": {k: "predictor" for k in features},
        "kinds": {k: "numeric" for k in features},
        "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
        "outlier_policy": {"mode": "report_only", "scenario": "principal"},
    }
    prepared = fit_dataset({"parsed_frame": frame}, spec)
    fit = fit_candidate(
        prepared,
        CandidateSpec(
            candidate_id="a5",
            features=features,
            base_variables=features,
            feature_groups={},
            x_transformations={},
            y_transformation="identity",
            intercept=True,
        ),
        spec,
    )
    assert fit.status == "fitted"
    design = transform_subject(subject, prepared.feature_schema, prepared.encoder_state)
    return evaluate_fitted(fit, design, spec)


def _item4(assessment):
    items = assessment.normative["fundamentacao"]["items"]
    return next(i for i in items if i["item"] == 4)


@pytest.mark.parametrize("value", [0.5, 2.0, -1.0])
def test_dichotomous_interpolation_and_extrapolation_are_not_admitted(value):
    item4 = _item4(_assess(_sample(), {"area": 120.0, "piscina": value}))
    assert item4["grade"] == 0
    assert "piscina" in item4["calculation"]["forbidden"]


@pytest.mark.parametrize("value", [0.0, 1.0])
def test_dichotomous_observed_levels_are_in_sample(value):
    item4 = _item4(_assess(_sample(), {"area": 120.0, "piscina": value}))
    assert item4["grade"] == 3
    assert "piscina" in item4["calculation"]["in_sample"]


def test_quantitative_axis_keeps_measure_window():
    item4 = _item4(_assess(_sample(), {"area": 120.0, "piscina": 1.0}))
    assert item4["calculation"]["measure"]["area"]["kind"] == "quantitative"


def test_ni_per_dichotomous_level_is_checked():
    ok = _assess(_sample(), {"area": 120.0, "piscina": 1.0}).normative["micronumerosidade"]
    assert ok["status"] == "ok"
    assert ok["checked_characteristics"] == ["piscina=0.0", "piscina=1.0"]
    # n = 60 -> n_i >= 6 (Anexo A.2 a); three data without pool violate it.
    bad = _assess(_sample(pool_zero=3), {"area": 120.0, "piscina": 1.0}).normative["micronumerosidade"]
    assert any(v.get("characteristic") == "piscina=0.0" for v in bad["violations"])


def test_homoscedasticity_and_normality_receive_cited_test_pvalues():
    pressupostos = {
        p["id"]: p for p in _assess(_sample(), {"area": 120.0, "piscina": 1.0}).normative["pressupostos"]
    }
    for pid in ("anexoA.2.c.homocedasticidade", "anexoA.2.d.normalidade"):
        assert pressupostos[pid]["status"] in {"satisfied", "violated"}
        assert isinstance(pressupostos[pid]["observed"], float)


def test_white_matches_statsmodels_on_full_rank_design_and_survives_dummies():
    frame = _sample()
    model = sm.OLS(frame["preco"], sm.add_constant(frame[["area"]])).fit()
    ours = _white_test_pvalue(np.asarray(model.resid), np.asarray(model.model.exog))
    assert ours == pytest.approx(het_white(model.resid, model.model.exog)[1], rel=1e-12)
    with_dummy = sm.OLS(frame["preco"], sm.add_constant(frame[["area", "piscina"]])).fit()
    p = _white_test_pvalue(np.asarray(with_dummy.resid), np.asarray(with_dummy.model.exog))
    assert p is not None and 0.0 <= p <= 1.0
