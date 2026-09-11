"""C03-A04: independent sourced cases for Tabela 1 items 2/4/5/6, Tabela 2, Tabela 5."""

import pytest

from modules.nbr14653_validation import NBRValidator, assess_normative
from modules.normative_rules import (
    EDITION_PART2,
    classify_fundamentacao,
    classify_item2_quantidade_dados,
    classify_item5_significancia_regressores,
    classify_item6_significancia_global,
    classify_precisao,
)


SOURCE = EDITION_PART2


def test_item2_formulas_cite_edition():
    # ABNT NBR 14653-2:2011 Tabela 1 item 2: 3(k+1) / 4(k+1) / 6(k+1)
    for k in (0, 1, 2, 4):
        r_fail = classify_item2_quantidade_dados(3 * (k + 1) - 1, k)
        r_i = classify_item2_quantidade_dados(3 * (k + 1), k)
        r_ii = classify_item2_quantidade_dados(4 * (k + 1), k)
        r_iii = classify_item2_quantidade_dados(6 * (k + 1), k)
        assert r_fail["grade"] == 0
        assert r_i["grade"] == 1
        assert r_ii["grade"] == 2
        assert r_iii["grade"] == 3
        assert r_i["source"]["edition"] == SOURCE
        assert r_i["source"]["clause"] == "Tabela 1 item 2"


def test_item2_missing_k_is_pending_not_shape_guess():
    r = classify_item2_quantidade_dados(20, None)
    assert r["grade"] is None
    assert r["evidence_status"] == "pending"


def test_item5_worst_p_not_average_sourced():
    # Tabela 1 item 5: 10% / 20% / 30% on the worst regressor p-value.
    r = classify_item5_significancia_regressores({"const": 0.001, "x1": 0.01, "x2": 0.29})
    assert r["worst_p"] == pytest.approx(0.29)
    assert r["grade"] == 1
    assert r["source"]["edition"] == SOURCE
    r0 = classify_item5_significancia_regressores({"x1": 0.01, "x2": 0.35})
    assert r0["grade"] == 0
    r3 = classify_item5_significancia_regressores({"x1": 0.05})
    assert r3["grade"] == 3
    r2 = classify_item5_significancia_regressores({"x1": 0.15})
    assert r2["grade"] == 2


def test_item5_automatic_selection_does_not_change_thresholds():
    r = classify_item5_significancia_regressores(
        {"x1": 0.09}, automatic_selection=True
    )
    assert r["grade"] == 3  # 9% still ≤10%; thresholds unchanged
    assert r["limitations"]


def test_item6_f_test_boundaries_sourced():
    # Tabela 1 item 6: 1% / 2% / 5%
    assert classify_item6_significancia_global(0.005)["grade"] == 3
    assert classify_item6_significancia_global(0.01)["grade"] == 3
    assert classify_item6_significancia_global(0.015)["grade"] == 2
    assert classify_item6_significancia_global(0.02)["grade"] == 2
    assert classify_item6_significancia_global(0.03)["grade"] == 1
    assert classify_item6_significancia_global(0.05)["grade"] == 1
    assert classify_item6_significancia_global(0.051)["grade"] == 0
    assert classify_item6_significancia_global(0.03)["source"]["edition"] == SOURCE


def test_tabela2_points_and_obrigatorios_sourced():
    # Tabela 2: III pontos≥16 e {2,4,5,6}≥3 e {1,3}≥2; II ≥10 e obrig.≥2; I ≥6 todos≥1
    g3, p3 = NBRValidator._classify_fundamentacao({1: 2, 2: 3, 3: 2, 4: 3, 5: 3, 6: 3})
    assert (g3, p3) == (3, 16)
    g2 = classify_fundamentacao({1: 1, 2: 2, 3: 1, 4: 2, 5: 2, 6: 2})
    assert g2["grade"] == 2 and g2["points"] == 10
    g1 = classify_fundamentacao({1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1})
    assert g1["grade"] == 1
    # Points for III but item 4 only 2 → II
    down = classify_fundamentacao({1: 3, 2: 3, 3: 3, 4: 2, 5: 3, 6: 3})
    assert down["points"] == 17
    assert down["grade"] == 2
    none = classify_fundamentacao({1: 3, 2: 1, 3: 1, 4: 0, 5: 1, 6: 1})
    assert none["grade"] is None
    pending = classify_fundamentacao({1: 3, 2: 3, 3: 3, 4: None, 5: 3, 6: 3})
    assert pending["grade"] is None
    assert pending["evidence_status"] == "pending"
    assert down["source"]["edition"] == SOURCE


def test_tabela5_amplitude_30_40_50_sourced():
    # Tabela 5: ≤30 III; ≤40 II; ≤50 I; >50 não classificável
    cases = [
        (10.0, 3, "classified"),
        (30.0, 3, "classified"),
        (30.01, 2, "classified"),
        (40.0, 2, "classified"),
        (40.01, 1, "classified"),
        (50.0, 1, "classified"),
        (50.01, None, "unclassified"),
        (75.0, None, "unclassified"),
    ]
    for amp, grade, status in cases:
        r = classify_precisao(amp)
        assert r["grade"] == grade
        assert r["status"] == status
        assert r["source"]["edition"] == SOURCE
        assert "Tabela 5" in r["source"]["clause"]


def test_legacy_item4_adapter_does_not_keep_measure_only_error():
    grade, detail = NBRValidator._classify_item4_extrapolacao(
        [{"variable": "area", "avaliando_value": 150, "sample_min": 50, "sample_max": 100}]
    )
    assert grade == 0
    assert "predict_original" in detail or "não" in detail.lower()
