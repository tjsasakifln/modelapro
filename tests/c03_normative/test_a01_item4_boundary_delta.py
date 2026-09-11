"""C03-A01: área 50–100, avaliando 150, y=10000×área → |Δfronteira|=50%; item 4 not approved."""

import pytest

from modules.nbr14653_validation import assess_normative
from modules.normative_rules import classify_item4_extrapolacao

from .helpers import a01_axes, a01_context, area_times_10000, independent_boundary_delta


def test_analytical_item4_boundary_delta_is_fifty_percent_not_approved():
    expected = independent_boundary_delta(150.0, 100.0, area_times_10000)
    assert expected == pytest.approx(50.0)

    result = classify_item4_extrapolacao(
        a01_axes(),
        subject_raw={"area": 150.0},
        predict_original=area_times_10000,
    )
    calc = result["calculation"]
    assert calc["boundary_delta_pct"] == pytest.approx(expected)
    assert calc["per_si"]["area"]["delta_pct"] == pytest.approx(expected)
    assert result["grade"] == 0
    assert result["grade"] not in (1, 2, 3)
    assert result["evidence_status"] == "calculated"
    # Grau III is "não admitida" because 150 is outside [50, 100].
    assert "150" in result["detail"] or "não admitida" in result["detail"] or result["grade"] == 0


def test_assess_normative_a01_does_not_approve_item4_from_extended_faixa():
    expected = independent_boundary_delta(150.0, 100.0, area_times_10000)
    assessment = assess_normative(a01_context())
    item4 = next(i for i in assessment["fundamentacao"]["items"] if i["item"] == 4)
    assert item4["calculation"]["boundary_delta_pct"] == pytest.approx(expected)
    assert item4["grade"] == 0
    assert item4["grade"] not in (1, 2, 3)
    assert item4["evidence_status"] == "calculated"
    # Extended measure [25, 200] contains 150 — that must not be a pass.
    measure = item4["calculation"]["measure"]["area"]
    assert measure["position"] == "extended"
    assert measure["ext_min"] == pytest.approx(25.0)
    assert measure["ext_max"] == pytest.approx(200.0)


def test_measure_only_without_callback_does_not_approve_item4():
    result = classify_item4_extrapolacao(
        a01_axes(),
        subject_raw={"area": 150.0},
        predict_original=None,
    )
    assert result["grade"] is None
    assert result["evidence_status"] == "pending"
    assert result["grade"] not in (1, 2, 3)

    assessment = assess_normative(a01_context(predict_original=None))
    item4 = next(i for i in assessment["fundamentacao"]["items"] if i["item"] == 4)
    assert item4["grade"] is None
    assert item4["evidence_status"] == "pending"
    assert assessment["verification_status"] in ("partial", "pending")
