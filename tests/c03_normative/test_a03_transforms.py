"""C03-A03: original-unit predictions; singular/zero/NaN/inf/unsupported get no grau."""

import math

import pytest

from modules.nbr14653_validation import assess_normative
from modules.normative_rules import classify_item4_extrapolacao, relative_difference_pct

from .helpers import a01_axes, a01_context, area_times_10000


def test_relative_difference_undefined_cases():
    assert relative_difference_pct(150.0, 0.0) == (None, "zero_denominator")
    assert relative_difference_pct(float("nan"), 100.0)[0] is None
    assert relative_difference_pct(100.0, float("inf"))[0] is None
    assert relative_difference_pct(None, 100.0)[0] is None


def test_transformed_x_pipeline_still_uses_original_unit():
    # Internal model uses ln(area) but predict_original inverts to y=10000*area.
    def predict_original(subject):
        area = float(subject["area"])
        ln_area = math.log(area)
        ln_y = math.log(10000.0) + ln_area  # ln(y) = ln(10000) + ln(area)
        return math.exp(ln_y)

    result = classify_item4_extrapolacao(
        a01_axes(),
        subject_raw={"area": 150.0},
        predict_original=predict_original,
    )
    expected = abs(10000.0 * 150.0 - 10000.0 * 100.0) / abs(10000.0 * 100.0) * 100.0
    assert result["calculation"]["boundary_delta_pct"] == pytest.approx(expected)
    assert expected == pytest.approx(50.0)
    # A log-scale |ln(150)-ln(100)|/|ln(100)| would be ~8.8% and would wrongly
    # look like Grau II. Original-unit 50% must not approve.
    log_scale_trap = abs(math.log(150.0) - math.log(100.0)) / abs(math.log(100.0)) * 100.0
    assert log_scale_trap < 15.0
    assert result["grade"] == 0


def test_transformed_y_pipeline_original_unit():
    def predict_original(subject):
        # Fit on ln(y); inverse exp.
        return math.exp(math.log(10000.0 * float(subject["area"])))

    assessment = assess_normative(
        a01_context(predict_original=predict_original)
    )
    item4 = next(i for i in assessment["fundamentacao"]["items"] if i["item"] == 4)
    assert item4["calculation"]["boundary_delta_pct"] == pytest.approx(50.0)
    assert item4["grade"] == 0


def test_zero_frontier_prediction_no_grade():
    def predict(subject):
        # Frontier clamp to 100 yields 0; avaliando 150 yields 50.
        return float(subject["area"]) - 100.0

    result = classify_item4_extrapolacao(
        a01_axes(),
        subject_raw={"area": 150.0},
        predict_original=predict,
    )
    assert result["grade"] is None
    assert result["evidence_status"] == "pending"
    assert result["calculation"]["per_si"]["area"]["error"] == "zero_denominator"


def test_nan_inf_and_exception_do_not_get_grade():
    def predict_nan(_s):
        return float("nan")

    def predict_inf(_s):
        return float("inf")

    def predict_raise(_s):
        raise ZeroDivisionError("singular inverse")

    for fn in (predict_nan, predict_inf, predict_raise):
        result = classify_item4_extrapolacao(
            a01_axes(),
            subject_raw={"area": 150.0},
            predict_original=fn,
        )
        assert result["grade"] is None
        assert result["evidence_status"] == "pending"


def test_negative_and_categorical_mixed_does_not_approve():
    axes = a01_axes() + [
        {
            "name": "bairro",
            "kind": "categorical",
            "avaliando_value": "Z",
            "sample_values": ["A", "B"],
        }
    ]
    result = classify_item4_extrapolacao(
        axes,
        subject_raw={"area": 150.0, "bairro": "Z"},
        predict_original=area_times_10000,
    )
    assert result["grade"] not in (1, 2, 3)


def test_several_axes_outside_sample_without_support():
    axes = [
        {
            "name": "area",
            "kind": "quantitative",
            "avaliando_value": 150.0,
            "sample_min": 50.0,
            "sample_max": 100.0,
        },
        {
            "name": "frente",
            "kind": "quantitative",
            "avaliando_value": None,
            "sample_min": 10.0,
            "sample_max": 20.0,
        },
    ]
    result = classify_item4_extrapolacao(
        axes,
        subject_raw={"area": 150.0},
        predict_original=area_times_10000,
    )
    assert result["grade"] not in (1, 2, 3)


def test_assess_normative_error_precisao_not_a_grade():
    assessment = assess_normative(a01_context(amplitude_pct=float("nan")))
    assert assessment["precisao"]["status"] == "error"
    assert assessment["precisao"]["grade"] is None
    assert assessment["precisao"]["amplitude_pct"] is None
