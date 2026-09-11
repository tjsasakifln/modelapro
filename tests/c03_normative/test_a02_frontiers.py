"""C03-A02: exact frontiers, ε-below/above, one and several variables, units, qualitative."""

import pytest

from modules.nbr14653_validation import assess_normative
from modules.normative_rules import (
    VALUE_LIMIT_GRAU_I,
    VALUE_LIMIT_GRAU_II,
    classify_item4_extrapolacao,
)

from .helpers import linear_predict


def _axis(name, value, vmin, vmax, kind="quantitative", **extra):
    d = {
        "name": name,
        "kind": kind,
        "avaliando_value": value,
        "sample_min": vmin,
        "sample_max": vmax,
    }
    d.update(extra)
    return d


def test_on_sample_frontier_is_grau_iii_no_value_check_needed():
    axes = [_axis("area", 100.0, 50.0, 100.0)]
    result = classify_item4_extrapolacao(axes, subject_raw={"area": 100.0})
    assert result["grade"] == 3
    assert result["calculation"]["measure"]["area"]["position"] == "in_sample"

    axes_min = [_axis("area", 50.0, 50.0, 100.0)]
    result_min = classify_item4_extrapolacao(axes_min, subject_raw={"area": 50.0})
    assert result_min["grade"] == 3


def test_measure_limit_exactly_2_max_uses_value_condition():
    # 200 == 2*100: still (a); (b) with y=10000*area is 100% > 20% → grade 0.
    def predict(s):
        return 10000.0 * float(s["area"])

    axes = [_axis("area", 200.0, 50.0, 100.0)]
    result = classify_item4_extrapolacao(axes, subject_raw={"area": 200.0}, predict_original=predict)
    assert result["calculation"]["measure"]["area"]["position"] == "extended"
    y_av = 10000.0 * 200.0
    y_fr = 10000.0 * 100.0
    expected = abs(y_av - y_fr) / abs(y_fr) * 100.0
    assert result["calculation"]["boundary_delta_pct"] == pytest.approx(expected)
    assert result["grade"] == 0

    axes_over = [_axis("area", 200.0 + 1e-9, 50.0, 100.0)]
    result_over = classify_item4_extrapolacao(
        axes_over, subject_raw={"area": 200.0 + 1e-9}, predict_original=predict
    )
    assert result_over["calculation"]["measure"]["area"]["position"] == "out_of_measure"
    assert result_over["grade"] == 0


def test_measure_limit_exactly_half_min():
    def predict(s):
        return 10000.0 * float(s["area"])

    axes = [_axis("area", 25.0, 50.0, 100.0)]
    result = classify_item4_extrapolacao(axes, subject_raw={"area": 25.0}, predict_original=predict)
    assert result["calculation"]["measure"]["area"]["position"] == "extended"
    y_av = 10000.0 * 25.0
    y_fr = 10000.0 * 50.0
    expected = abs(y_av - y_fr) / abs(y_fr) * 100.0
    assert result["calculation"]["boundary_delta_pct"] == pytest.approx(expected)
    assert expected == pytest.approx(50.0)
    assert result["grade"] == 0

    axes_under = [_axis("area", 25.0 - 1e-9, 50.0, 100.0)]
    result_under = classify_item4_extrapolacao(
        axes_under, subject_raw={"area": 25.0 - 1e-9}, predict_original=predict
    )
    assert result_under["grade"] == 0
    assert result_under["calculation"]["measure"]["area"]["position"] == "out_of_measure"


def test_value_limit_15_percent_exactly_and_epsilon():
    # 50*|b| / |c+100b| = 0.15 with b=1 ⇒ c = 35/0.15
    c_eq = 35.0 / 0.15
    predict_eq = linear_predict(c_eq, {"area": 1.0})
    axes = [_axis("area", 150.0, 50.0, 100.0)]
    r_eq = classify_item4_extrapolacao(axes, subject_raw={"area": 150.0}, predict_original=predict_eq)
    y_av = c_eq + 150.0
    y_fr = c_eq + 100.0
    expected = abs(y_av - y_fr) / abs(y_fr) * 100.0
    assert expected == pytest.approx(VALUE_LIMIT_GRAU_II * 100.0)
    assert r_eq["calculation"]["boundary_delta_pct"] == pytest.approx(expected)
    assert r_eq["grade"] == 2

    c_over = c_eq - 1.0  # smaller intercept → larger relative delta
    predict_over = linear_predict(c_over, {"area": 1.0})
    r_over = classify_item4_extrapolacao(
        axes, subject_raw={"area": 150.0}, predict_original=predict_over
    )
    y_av_o = c_over + 150.0
    y_fr_o = c_over + 100.0
    expected_o = abs(y_av_o - y_fr_o) / abs(y_fr_o) * 100.0
    assert expected_o > VALUE_LIMIT_GRAU_II * 100.0
    assert r_over["grade"] != 2
    # 15% < delta; if still ≤20% then Grau I, else 0
    if expected_o <= VALUE_LIMIT_GRAU_I * 100.0:
        assert r_over["grade"] == 1
    else:
        assert r_over["grade"] == 0


def test_value_limit_20_percent_exactly_and_epsilon():
    # 50b / (c+100b) = 0.20 with b=1 ⇒ c = 150
    predict_eq = linear_predict(150.0, {"area": 1.0})
    axes = [_axis("area", 150.0, 50.0, 100.0)]
    r_eq = classify_item4_extrapolacao(axes, subject_raw={"area": 150.0}, predict_original=predict_eq)
    expected = abs((150.0 + 150.0) - (150.0 + 100.0)) / abs(150.0 + 100.0) * 100.0
    assert expected == pytest.approx(VALUE_LIMIT_GRAU_I * 100.0)
    assert r_eq["grade"] == 1  # 20% fails II (15%) but meets I

    predict_over = linear_predict(149.0, {"area": 1.0})
    r_over = classify_item4_extrapolacao(
        axes, subject_raw={"area": 150.0}, predict_original=predict_over
    )
    expected_o = abs((149.0 + 150.0) - (149.0 + 100.0)) / abs(149.0 + 100.0) * 100.0
    assert expected_o > VALUE_LIMIT_GRAU_I * 100.0
    assert r_over["grade"] == 0


def test_two_variables_simultaneous_and_per_si():
    # x in extended, z in extended. Grau II impossible.
    # y = 1000 + 0.01*x + 0.01*z → small deltas → Grau I.
    predict = linear_predict(1000.0, {"x": 0.01, "z": 0.01})
    axes = [
        _axis("x", 25.0, 5.0, 19.0),
        _axis("z", 3.0, 5.0, 10.0),
    ]
    subject = {"x": 25.0, "z": 3.0}
    result = classify_item4_extrapolacao(axes, subject_raw=subject, predict_original=predict)
    assert result["grade"] == 1
    assert set(result["calculation"]["extrapolated"]) == {"x", "z"}
    assert result["calculation"]["simultaneous"]["limit_ok_i"] is True
    assert all(result["calculation"]["per_si"][n]["limit_ok_i"] for n in ("x", "z"))

    # Simultaneous fails 20% even if per-si would pass: steep joint effect.
    def predict_joint(s):
        # Large product-like sensitivity when both off-frontier.
        return 100.0 + 10.0 * float(s["x"]) + 10.0 * float(s["z"])

    r_fail = classify_item4_extrapolacao(axes, subject_raw=subject, predict_original=predict_joint)
    # per-si x: ŷ(25,3) vs ŷ(19,3) = (100+250+30) vs (100+190+30) = 380 vs 320 → 18.75%
    # per-si z: ŷ(25,3) vs ŷ(25,5) = 380 vs 100+250+50=400 → 5%
    # simultaneous: ŷ(25,3) vs ŷ(19,5) = 380 vs 100+190+50=340 → 11.76%
    # 18.75% ≤ 20% and sim 11.76% ≤ 20% → actually Grau I still.
    # Need a case where simultaneous exceeds 20% or one per-si exceeds.
    def predict_sim_bad(s):
        # Penalty when both deviate: y = 10 + x*z
        return 10.0 + float(s["x"]) * float(s["z"])

    r_sim = classify_item4_extrapolacao(axes, subject_raw=subject, predict_original=predict_sim_bad)
    y_s = 10.0 + 25.0 * 3.0  # 85
    y_x = 10.0 + 19.0 * 3.0  # 67  delta 26.87%
    y_z = 10.0 + 25.0 * 5.0  # 135 delta 37.0% vs wait |85-135|/135
    y_both = 10.0 + 19.0 * 5.0  # 105
    d_x = abs(y_s - y_x) / abs(y_x) * 100.0
    d_z = abs(y_s - y_z) / abs(y_z) * 100.0
    d_b = abs(y_s - y_both) / abs(y_both) * 100.0
    assert r_sim["calculation"]["per_si"]["x"]["delta_pct"] == pytest.approx(d_x)
    assert r_sim["calculation"]["per_si"]["z"]["delta_pct"] == pytest.approx(d_z)
    assert r_sim["calculation"]["simultaneous"]["delta_pct"] == pytest.approx(d_b)
    # At least one of per-si or simultaneous exceeds 20% in this construction.
    assert d_x > 20.0 or d_z > 20.0 or d_b > 20.0
    assert r_sim["grade"] == 0


def test_coherent_unit_change_does_not_flip_conclusion():
    def predict_m2(s):
        return 10000.0 * float(s["area"])

    def predict_cm2(s):
        # 1 m² = 10_000 cm²; y = 10000 * area_m2 = area_cm2
        return 1.0 * float(s["area"])

    r_m2 = classify_item4_extrapolacao(
        [_axis("area", 150.0, 50.0, 100.0, unit="m2")],
        subject_raw={"area": 150.0},
        predict_original=predict_m2,
    )
    r_cm2 = classify_item4_extrapolacao(
        [_axis("area", 1_500_000.0, 500_000.0, 1_000_000.0, unit="cm2")],
        subject_raw={"area": 1_500_000.0},
        predict_original=predict_cm2,
    )
    assert r_m2["grade"] == r_cm2["grade"] == 0
    assert r_m2["calculation"]["boundary_delta_pct"] == pytest.approx(
        r_cm2["calculation"]["boundary_delta_pct"]
    )
    assert r_m2["calculation"]["boundary_delta_pct"] == pytest.approx(50.0)


def test_dichotomous_and_codes_do_not_get_invented_faixa():
    dummy = classify_item4_extrapolacao(
        [
            _axis(
                "vista_mar",
                1.0,
                0.0,
                0.0,
                kind="dichotomous",
                sample_values=[0.0],
            )
        ],
        subject_raw={"vista_mar": 1.0},
        predict_original=lambda s: 1000.0 + 100.0 * float(s["vista_mar"]),
    )
    assert dummy["grade"] == 0
    assert dummy["evidence_status"] == "not_applicable"
    assert dummy["calculation"]["measure"]["vista_mar"]["faixa_ampliada"] == "not_applicable"

    dummy_ok = classify_item4_extrapolacao(
        [
            _axis(
                "vista_mar",
                1.0,
                0.0,
                1.0,
                kind="dichotomous",
                sample_values=[0.0, 1.0],
            )
        ],
        subject_raw={"vista_mar": 1.0},
    )
    assert dummy_ok["grade"] == 3

    allocated = classify_item4_extrapolacao(
        [
            _axis(
                "padrao",
                5.0,
                1.0,
                3.0,
                kind="allocated_code",
                sample_values=[1, 2, 3],
            )
        ],
        subject_raw={"padrao": 5.0},
    )
    assert allocated["grade"] == 0
    assert "A.6" in allocated["detail"] or allocated["evidence_status"] == "not_applicable"

    adjusted = classify_item4_extrapolacao(
        [
            _axis(
                "padrao",
                2.5,
                1.0,
                3.0,
                kind="adjusted_code",
                sample_values=[1.0, 2.0, 3.0],
            )
        ],
        subject_raw={"padrao": 2.5},
    )
    assert adjusted["grade"] == 0
    assert adjusted["evidence_status"] == "not_applicable"

    categorical = classify_item4_extrapolacao(
        [
            {
                "name": "bairro",
                "kind": "categorical",
                "avaliando_value": "X",
                "sample_values": ["A", "B"],
                "categories": ["A", "B"],
            }
        ],
        subject_raw={"bairro": "X"},
    )
    assert categorical["grade"] == 0
    assert categorical["evidence_status"] in ("not_applicable", "pending")


def test_negative_domain_does_not_invent_half_min_extension():
    result = classify_item4_extrapolacao(
        [_axis("saldo", -30.0, -20.0, 20.0)],
        subject_raw={"saldo": -30.0},
        predict_original=lambda s: 100.0 + float(s["saldo"]),
    )
    assert result["grade"] not in (1, 2, 3)
    assert result["evidence_status"] in ("pending", "not_applicable", "calculated")
    if result["evidence_status"] == "calculated":
        assert result["grade"] == 0
    assert result["calculation"]["measure"]["saldo"]["position"] in (
        "not_applicable",
        "out_of_measure",
        "pending",
    )


def test_assess_normative_frontiers_match_classifier():
    predict = linear_predict(35.0 / 0.15, {"area": 1.0})
    assessment = assess_normative(
        {
            "n": 20,
            "k": 1,
            "intercept": True,
            "axes": [_axis("area", 150.0, 50.0, 100.0)],
            "subject_raw": {"area": 150.0},
            "predict_original": predict,
            "pvalues": {"area": 0.01},
            "f_pvalue": 0.001,
            "amplitude_pct": 20.0,
            "documentary": {
                "item1": {"grade": 1, "provenance": {"source": "test"}},
                "item3": {"grade": 1, "provenance": {"source": "test"}},
            },
        }
    )
    item4 = next(i for i in assessment["fundamentacao"]["items"] if i["item"] == 4)
    assert item4["grade"] == 2
