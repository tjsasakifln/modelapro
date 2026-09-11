"""C03-A05: precisão statuses distinct; documentary provenance; grau ≠ emissão; no VIF/R² gate."""

import pandas as pd
import pytest

from modules.nbr14653_validation import NBRValidator, assess_normative
from modules.normative_rules import classify_precisao, interval_roles
from modules.results import ModelMetrics, ModelResult

from .helpers import a01_context, area_times_10000


def test_precisao_four_statuses_are_distinct():
    missing = classify_precisao(None)
    classified = classify_precisao(25.0)
    unclassified = classify_precisao(60.0)
    error = classify_precisao(float("inf"))
    assert missing["status"] == "not_computed" and missing["grade"] is None
    assert classified["status"] == "classified" and classified["grade"] == 3
    assert unclassified["status"] == "unclassified" and unclassified["grade"] is None
    assert error["status"] == "error" and error["grade"] is None
    assert error["amplitude_pct"] is None
    statuses = {missing["status"], classified["status"], unclassified["status"], error["status"]}
    assert statuses == {"not_computed", "classified", "unclassified", "error"}


def test_assess_normative_propagates_precisao_status():
    a = assess_normative(a01_context(amplitude_pct=None))
    assert a["precisao"]["status"] == "not_computed"
    b = assess_normative(a01_context(amplitude_pct=35.0))
    assert b["precisao"]["status"] == "classified" and b["precisao"]["grade"] == 2
    c = assess_normative(a01_context(amplitude_pct=51.0))
    assert c["precisao"]["status"] == "unclassified" and c["precisao"]["grade"] is None
    d = assess_normative(a01_context(amplitude_pct=float("nan")))
    assert d["precisao"]["status"] == "error" and d["precisao"]["grade"] is None


def test_documentary_without_provenance_is_not_verified():
    assessment = assess_normative(
        a01_context(
            documentary={
                "item1": {"grade": 3},  # selectbox-like, no provenance
                "item3": {"grade": 3},
            }
        )
    )
    doc = assessment["documentary"]
    assert doc["item1"]["evidence_status"] == "declared"
    assert doc["item1"]["evidence_status"] != "verified"
    assert doc["item1"]["provenance"] is None
    item1 = next(i for i in assessment["fundamentacao"]["items"] if i["item"] == 1)
    assert item1["evidence_status"] == "declared"
    assert item1["evidence_status"] != "verified"


def test_documentary_missing_is_pending_not_approval():
    assessment = assess_normative(
        {
            "n": 20,
            "k": 1,
            "intercept": True,
            "axes": a01_context()["axes"],
            "subject_raw": {"area": 80.0},  # in sample
            "predict_original": area_times_10000,
            "pvalues": {"area": 0.01},
            "f_pvalue": 0.001,
            "amplitude_pct": 20.0,
        }
    )
    item1 = next(i for i in assessment["fundamentacao"]["items"] if i["item"] == 1)
    assert item1["grade"] is None
    assert item1["evidence_status"] == "pending"
    assert assessment["fundamentacao"]["grade"] is None  # Tabela 2 not approved by absence


def test_vif_and_r2_are_warnings_not_normative_cut():
    assessment = assess_normative(
        a01_context(
            statistical={
                "r2_adjusted": 0.2,
                "vif": {"area": 150.0, "const": 1.0},
                "normality_pvalue": 0.01,
            },
            subject_raw={"area": 80.0},
            axes=[
                {
                    "name": "area",
                    "kind": "quantitative",
                    "avaliando_value": 80.0,
                    "sample_min": 50.0,
                    "sample_max": 100.0,
                }
            ],
        )
    )
    warnings = assessment["statistical"]["warnings"]
    assert any("VIF" in w for w in warnings)
    assert any("R²" in w or "R2" in w for w in warnings)
    item4 = next(i for i in assessment["fundamentacao"]["items"] if i["item"] == 4)
    assert item4["grade"] == 3  # in sample; VIF did not zero the item
    assert assessment["fundamentacao"]["grade"] is not None


def test_intervals_distinct_and_admissible_requires_use_condition():
    pending = interval_roles(
        central_estimate=1000.0,
        mean_ci80={"lower": 900.0, "upper": 1100.0},
        prediction_interval={"lower": 700.0, "upper": 1300.0},
    )
    assert pending["arbitration_interval"]["lower"] == pytest.approx(850.0)
    assert pending["arbitration_interval"]["upper"] == pytest.approx(1150.0)
    assert pending["admissible_status"] == "pending"
    assert pending["mean_ci80"] is not None
    assert pending["prediction_interval"] is not None

    ok = interval_roles(
        central_estimate=1000.0,
        mean_ci80={"lower": 900.0, "upper": 1100.0},
        prediction_interval={"lower": 700.0, "upper": 1300.0},
        estimand="market_value",
        adopted_estimator="central_tendency",
    )
    assert ok["admissible_status"] == "calculated"
    assert ok["admissible_interval"]["via"] == "mean_ci80"
    # campo ±15% = [850, 1150]; CI [900, 1100] → intersection [900, 1100]
    assert ok["admissible_interval"]["lower"] == pytest.approx(900.0)
    assert ok["admissible_interval"]["upper"] == pytest.approx(1100.0)

    price = interval_roles(
        central_estimate=1000.0,
        mean_ci80={"lower": 900.0, "upper": 1100.0},
        prediction_interval={"lower": 800.0, "upper": 1050.0},
        estimand="price",
        adopted_estimator="central_tendency",
    )
    assert price["admissible_interval"]["via"] == "prediction_interval"
    assert price["admissible_interval"]["lower"] == pytest.approx(850.0)
    assert price["admissible_interval"]["upper"] == pytest.approx(1050.0)


def test_grau_does_not_mean_issuance():
    assessment = assess_normative(
        a01_context(
            subject_raw={"area": 80.0},
            axes=[
                {
                    "name": "area",
                    "kind": "quantitative",
                    "avaliando_value": 80.0,
                    "sample_min": 50.0,
                    "sample_max": 100.0,
                }
            ],
        )
    )
    assert assessment["fundamentacao"]["grade"] in (1, 2, 3)
    codes = {i["code"] for i in assessment["issues"]}
    assert "grau_nao_e_emissao" in codes
    note = assessment["issuance_note"].lower()
    assert "ready_for_professional_review" in note
    assert "não é inferido" in note or "nao e inferido" in note or "não autoriza" in note


def test_legacy_high_vif_still_does_not_block_is_valid():
    metrics = ModelMetrics(
        r2=0.3,
        r2_adjusted=0.25,
        f_statistic=50,
        f_pvalue=0.001,
        std_error=0.1,
        aic=10,
        bic=12,
        condition_number=10,
        normality_pvalue=0.5,
        homoscedasticity_pvalue=0.5,
        autocorrelation_durbin_watson=2.0,
    )
    model_result = ModelResult(
        success=True,
        model_metrics=metrics,
        pvalues={"x": 0.01, "const": 0.01},
        vif={"x": 150.0, "const": 1.0},
        residuals=[0.1] * 20,
        fitted_values=[1.0] * 20,
    )
    X = pd.DataFrame({"const": 1, "x": range(20)})
    y = pd.Series(range(20))
    res = NBRValidator.validate_model(model_result, X, y, degree=1)
    res = NBRValidator.finalize_precision_and_extrapolation(
        res,
        amplitude_pct=25.0,
        extrapolation_details=[
            {"variable": "x", "avaliando_value": 10, "sample_min": 0, "sample_max": 19}
        ],
        degree=1,
    )
    assert res.grau_fundamentacao is not None
    assert res.is_valid is True
    assert any("VIF" in w for w in res.warnings)
    assert not any("VIF" in m for m in res.messages)
