"""MP-COM/C05-A03 — classificador único e fronteiras exatas.

Todos os valores ESPERADOS abaixo foram calculados À MÃO a partir dos fatos
normativos verificados nas edições licenciadas:

ABNT NBR 14653-2:2011
  Tabela 1 item 2 : n >= 6(k+1) III | 4(k+1) II | 3(k+1) I
  Tabela 1 item 4 : III = não admitida; II uma variável com (a) medida
                    <= 2x max e >= 0,5x min e (b) |Δvalor| <= 15%;
                    I idem com 20%, de per si E simultaneamente.
  Tabela 1 item 5 : pior p <= 10% III | <= 20% II | <= 30% I
  Tabela 1 item 6 : p <= 1% III | <= 2% II | <= 5% I
  9.2.1.6 b)      : Grau I = 1 ponto, II = 2, III = 3
  Tabela 2        : 16/10/6 pontos; itens 2,4,5,6 obrigatórios
                    (III -> 3 nos obrigatórios e >= 2 nos itens 1 e 3;
                     II  -> >= 2 nos obrigatórios e >= 1 nos itens 1 e 3;
                     I   -> todos >= 1)
  Tabela 5        : amplitude do IC 80% <= 30% III | <= 40% II | <= 50% I;
                    acima de 50% NÃO há classificação quanto à precisão.

Nenhuma asserção foi obtida executando o código e copiando a saída.
"""

import math

import pandas as pd
import pytest

from modules import normative_rules as rules
from modules.nbr14653_validation import NBRValidator, assess_normative
from modules.results import ModelMetrics, ModelResult


# ---------------------------------------------------------------------------
# Helpers (ModelResult construído como em tests/test_nbr14653.py)
# ---------------------------------------------------------------------------


def make_metrics(r2=0.80, r2_adjusted=0.78, f_pvalue=0.001, normality_pvalue=0.5,
                 homoscedasticity_pvalue=0.5):
    return ModelMetrics(
        r2=r2, r2_adjusted=r2_adjusted, f_statistic=50, f_pvalue=f_pvalue,
        std_error=0.1, aic=10, bic=12, condition_number=10,
        normality_pvalue=normality_pvalue,
        homoscedasticity_pvalue=homoscedasticity_pvalue,
        autocorrelation_durbin_watson=2.0,
    )


def make_model_result(metrics, pvalues, vif=None, n=20):
    if vif is None:
        vif = {v: 1.2 for v in pvalues if v != "const"}
        vif["const"] = 1.0
    return ModelResult(
        success=True, model_metrics=metrics,
        pvalues=pvalues, vif=vif,
        residuals=[0.1] * n, fitted_values=[1.0] * n,
    )


def quantitative_axis(name="area", sample_min=10.0, sample_max=100.0, value=50.0):
    return {
        "name": name,
        "kind": rules.KIND_QUANTITATIVE,
        "sample_min": sample_min,
        "sample_max": sample_max,
        "avaliando_value": value,
    }


def linear_predictor(name, base_at_frontier, slope, frontier):
    """ŷ = base_at_frontier + slope * (x - frontier). Determinístico, sem mock
    de módulo sob teste: é apenas o modelo do avaliador na unidade original."""

    def _predict(raw):
        return base_at_frontier + slope * (float(raw[name]) - frontier)

    return _predict


# ---------------------------------------------------------------------------
# Tabela 1 item 2 — n >= 3(k+1) / 4(k+1) / 6(k+1)
# ---------------------------------------------------------------------------


class TestItem2Fronteiras:
    """Mínimos calculados à mão:
       k=1 -> I=6,  II=8,  III=12
       k=3 -> I=12, II=16, III=24
       k=5 -> I=18, II=24, III=36
    """

    @pytest.mark.parametrize(
        "k, t1, t2, t3",
        [(1, 6, 8, 12), (3, 12, 16, 24), (5, 18, 24, 36)],
    )
    def test_thresholds_exposed_match_hand_computation(self, k, t1, t2, t3):
        res = rules.classify_item2_quantidade_dados(t3, k)
        assert res["thresholds"] == {"grau_i": t1, "grau_ii": t2, "grau_iii": t3}

    @pytest.mark.parametrize(
        "k, t1, t2, t3",
        [(1, 6, 8, 12), (3, 12, 16, 24), (5, 18, 24, 36)],
    )
    def test_exact_boundaries_and_one_below_each(self, k, t1, t2, t3):
        # n exatamente 3(k+1) -> Grau I; um abaixo -> nenhum grau (0)
        assert rules.classify_item2_quantidade_dados(t1, k)["grade"] == 1
        assert rules.classify_item2_quantidade_dados(t1 - 1, k)["grade"] == 0
        # n exatamente 4(k+1) -> Grau II; um abaixo -> Grau I
        assert rules.classify_item2_quantidade_dados(t2, k)["grade"] == 2
        assert rules.classify_item2_quantidade_dados(t2 - 1, k)["grade"] == 1
        # n exatamente 6(k+1) -> Grau III; um abaixo -> Grau II
        assert rules.classify_item2_quantidade_dados(t3, k)["grade"] == 3
        assert rules.classify_item2_quantidade_dados(t3 - 1, k)["grade"] == 2

    def test_k_zero_thresholds(self):
        # k=0 -> 3, 4, 6
        assert rules.classify_item2_quantidade_dados(3, 0)["grade"] == 1
        assert rules.classify_item2_quantidade_dados(2, 0)["grade"] == 0
        assert rules.classify_item2_quantidade_dados(4, 0)["grade"] == 2
        assert rules.classify_item2_quantidade_dados(6, 0)["grade"] == 3

    def test_absence_is_not_approval(self):
        for n, k in ((None, 3), (30, None), (None, None)):
            res = rules.classify_item2_quantidade_dados(n, k)
            assert res["grade"] is None
            assert res["evidence_status"] == rules.EVIDENCE_PENDING
            assert res["thresholds"] is None

    def test_negative_inputs_are_pending_not_graded(self):
        assert rules.classify_item2_quantidade_dados(-1, 2)["grade"] is None
        assert rules.classify_item2_quantidade_dados(30, -1)["grade"] is None

    def test_non_finite_n_is_pending(self):
        assert rules.classify_item2_quantidade_dados(float("nan"), 2)["grade"] is None
        assert rules.classify_item2_quantidade_dados(float("inf"), 2)["grade"] is None


# ---------------------------------------------------------------------------
# Tabela 1 item 5 — pior p-valor dos regressores: 10% / 20% / 30%
# ---------------------------------------------------------------------------


class TestItem5Fronteiras:
    @pytest.mark.parametrize(
        "p, expected",
        [
            (0.10, 3),        # exatamente 10% -> Grau III
            (0.100001, 2),    # logo acima -> Grau II
            (0.20, 2),        # exatamente 20% -> Grau II
            (0.200001, 1),    # logo acima -> Grau I
            (0.30, 1),        # exatamente 30% -> Grau I
            (0.300001, 0),    # logo acima -> nenhum grau
        ],
    )
    def test_exact_boundaries(self, p, expected):
        res = rules.classify_item5_significancia_regressores({"x": p})
        assert res["grade"] == expected
        assert res["worst_p"] == pytest.approx(p)

    def test_worst_regressor_governs_and_intercept_is_excluded(self):
        # pior regressor = 0.25 -> Grau I. O intercepto (0.99) não conta.
        res = rules.classify_item5_significancia_regressores(
            {"const": 0.99, "x1": 0.01, "x2": 0.25}
        )
        assert res["grade"] == 1
        assert res["worst_p"] == pytest.approx(0.25)

    def test_non_finite_pvalues_are_pending_not_zero(self):
        res = rules.classify_item5_significancia_regressores({"x": float("nan")})
        assert res["grade"] is None
        assert res["evidence_status"] == rules.EVIDENCE_PENDING

    def test_automatic_selection_does_not_move_the_tabled_threshold(self):
        auto = rules.classify_item5_significancia_regressores(
            {"x": 0.10}, automatic_selection=True
        )
        plain = rules.classify_item5_significancia_regressores({"x": 0.10})
        assert auto["grade"] == plain["grade"] == 3
        assert auto["limitations"] and not plain["limitations"]


# ---------------------------------------------------------------------------
# Tabela 1 item 6 — teste F: 1% / 2% / 5%
# ---------------------------------------------------------------------------


class TestItem6Fronteiras:
    @pytest.mark.parametrize(
        "p, expected",
        [
            (0.01, 3),        # exatamente 1% -> Grau III
            (0.010001, 2),
            (0.02, 2),        # exatamente 2% -> Grau II
            (0.020001, 1),
            (0.05, 1),        # exatamente 5% -> Grau I
            (0.050001, 0),
        ],
    )
    def test_exact_boundaries(self, p, expected):
        res = rules.classify_item6_significancia_global(p)
        assert res["grade"] == expected

    def test_absence_is_not_approval(self):
        for bad in (None, float("nan"), float("inf"), "abc"):
            res = rules.classify_item6_significancia_global(bad)
            assert res["grade"] is None
            assert res["evidence_status"] == rules.EVIDENCE_PENDING


# ---------------------------------------------------------------------------
# Tabela 2 — cantos exatos de pontuação e itens obrigatórios
# ---------------------------------------------------------------------------


class TestTabela2Cantos:
    def test_grau_iii_exact_corner_16_points(self):
        # obrigatórios (2,4,5,6) = 3 -> 12 pontos; itens 1 e 3 = 2 -> 4 pontos.
        # Total = 16 = mínimo do Grau III, e "os demais no mínimo Grau II" ok.
        scores = {1: 2, 2: 3, 3: 2, 4: 3, 5: 3, 6: 3}
        res = rules.classify_fundamentacao(scores)
        assert res["points"] == 16
        assert res["grade"] == 3
        assert res["pending_items"] == []

    def test_obligatory_items_at_three_but_complementares_at_grau_i_is_not_grau_iii(self):
        # 1 + 3 + 1 + 3 + 3 + 3 = 14 pontos: abaixo de 16 E os itens 1 e 3 estão
        # em Grau I (a Tabela 2 exige "os demais no mínimo no Grau II" para III).
        # Grau II: pontos 14 >= 10, obrigatórios >= 2, demais >= 1 -> Grau II.
        scores = {1: 1, 2: 3, 3: 1, 4: 3, 5: 3, 6: 3}
        res = rules.classify_fundamentacao(scores)
        assert res["points"] == 14
        assert res["grade"] == 2

    def test_sixteen_points_but_one_obligatory_below_three_is_not_grau_iii(self):
        # 3 + 2 + 3 + 3 + 3 + 3 = 17 pontos (>= 16) mas o item 2 (obrigatório)
        # está em Grau II -> III é vedado; cai em Grau II.
        scores = {1: 3, 2: 2, 3: 3, 4: 3, 5: 3, 6: 3}
        res = rules.classify_fundamentacao(scores)
        assert res["points"] == 17
        assert res["grade"] == 2

    def test_grau_ii_exact_corner_10_points(self):
        # obrigatórios em Grau II (2x4=8) + itens 1 e 3 em Grau I (1x2=2) = 10.
        scores = {1: 1, 2: 2, 3: 1, 4: 2, 5: 2, 6: 2}
        res = rules.classify_fundamentacao(scores)
        assert res["points"] == 10
        assert res["grade"] == 2

    def test_one_obligatory_at_grau_i_drops_to_grau_i(self):
        # 1 + 2 + 1 + 2 + 2 + 1 = 9 pontos. Grau II exige obrigatórios >= 2:
        # o item 6 está em Grau I -> não é II. Grau I: todos >= 1 e 9 >= 6 -> I.
        scores = {1: 1, 2: 2, 3: 1, 4: 2, 5: 2, 6: 1}
        res = rules.classify_fundamentacao(scores)
        assert res["points"] == 9
        assert res["grade"] == 1

    def test_grau_i_exact_corner_6_points(self):
        scores = {i: 1 for i in range(1, 7)}
        res = rules.classify_fundamentacao(scores)
        assert res["points"] == 6
        assert res["grade"] == 1

    def test_grade_zero_on_complementary_item_blocks_grau_i_despite_high_points(self):
        # 0 + 3 + 3 + 3 + 3 + 3 = 15 pontos. III exige 16 -> não.
        # II exige "os demais no mínimo Grau I": item 1 = 0 -> não.
        # I exige todos >= 1: item 1 = 0 -> não. Logo não classificado.
        scores = {1: 0, 2: 3, 3: 3, 4: 3, 5: 3, 6: 3}
        res = rules.classify_fundamentacao(scores)
        assert res["points"] == 15
        assert res["grade"] is None

    def test_grade_zero_on_obligatory_item_blocks_grau_i_despite_high_points(self):
        # 3 + 3 + 3 + 3 + 3 + 0 = 15 pontos; item 6 (obrigatório) = 0.
        scores = {1: 3, 2: 3, 3: 3, 4: 3, 5: 3, 6: 0}
        res = rules.classify_fundamentacao(scores)
        assert res["points"] == 15
        assert res["grade"] is None

    def test_tabled_point_minimums_are_the_normative_ones(self):
        assert rules.TABELA2_PONTOS_III == 16
        assert rules.TABELA2_PONTOS_II == 10
        assert rules.TABELA2_PONTOS_I == 6


# ---------------------------------------------------------------------------
# Autoridade única / sem fallback
# ---------------------------------------------------------------------------


class TestAutoridadeUnicaSemFallback:
    @pytest.mark.parametrize("missing", [1, 2, 3, 4, 5, 6])
    def test_any_missing_item_yields_none_grade_and_is_listed_as_pending(self, missing):
        scores = {i: 3 for i in range(1, 7)}
        scores[missing] = None
        res = rules.classify_fundamentacao(scores)
        assert res["grade"] is None, f"item {missing} pendente não pode gerar grau"
        assert res["pending_items"] == [missing]
        assert res["evidence_status"] == rules.EVIDENCE_PENDING

    @pytest.mark.parametrize("missing", [2, 4])
    def test_points_never_license_a_grade_when_an_obligatory_item_is_pending(self, missing):
        # Cinco itens em Grau III = 15 pontos, muito acima do mínimo do Grau II
        # (10) e do Grau I (6). Ainda assim o grau tem de ser None.
        scores = {i: 3 for i in range(1, 7)}
        scores[missing] = None
        res = rules.classify_fundamentacao(scores)
        assert res["points"] == 15
        assert res["points"] >= rules.TABELA2_PONTOS_II
        assert res["grade"] is None

    def test_pending_item_is_not_silently_replaced_by_zero_grade(self):
        pending = rules.classify_fundamentacao({1: 3, 2: None, 3: 3, 4: 3, 5: 3, 6: 3})
        zeroed = rules.classify_fundamentacao({1: 3, 2: 0, 3: 3, 4: 3, 5: 3, 6: 3})
        # Mesma pontuação, mas a ausência precisa ser rastreável como pendência.
        assert pending["points"] == zeroed["points"] == 15
        assert pending["pending_items"] == [2]
        assert zeroed["pending_items"] == []
        assert pending["grade"] is zeroed["grade"] is None

    def test_missing_item_key_altogether_is_also_pending(self):
        res = rules.classify_fundamentacao({1: 3, 3: 3, 4: 3, 5: 3, 6: 3})
        assert res["grade"] is None
        assert res["pending_items"] == [2]

    def test_adapter_fundamentacao_agrees_with_rules(self):
        for scores in (
            {1: 2, 2: 3, 3: 2, 4: 3, 5: 3, 6: 3},
            {1: 1, 2: 3, 3: 1, 4: 3, 5: 3, 6: 3},
            {1: 1, 2: 2, 3: 1, 4: 2, 5: 2, 6: 2},
            {i: 1 for i in range(1, 7)},
            {1: 0, 2: 3, 3: 3, 4: 3, 5: 3, 6: 3},
            {1: 3, 2: None, 3: 3, 4: 3, 5: 3, 6: 3},
        ):
            expected = rules.classify_fundamentacao(scores)
            grade, points = NBRValidator._classify_fundamentacao(scores)
            assert grade == expected["grade"]
            assert points == expected["points"]

    def test_adapter_item2_agrees_with_rules_and_coerces_pending_to_zero(self):
        for n, k in ((5, 1), (6, 1), (8, 1), (12, 1), (23, 3), (24, 3), (36, 5)):
            assert (
                NBRValidator._classify_item2_quantidade_dados(n, k)
                == rules.classify_item2_quantidade_dados(n, k)["grade"]
            )
        # Coerção conservadora: pendente vira 0 ponto, nunca um grau.
        assert rules.classify_item2_quantidade_dados(None, 3)["grade"] is None
        assert NBRValidator._classify_item2_quantidade_dados(None, 3) == 0

    def test_adapter_item5_agrees_with_rules(self):
        for p in (0.10, 0.100001, 0.20, 0.200001, 0.30, 0.300001):
            expected = rules.classify_item5_significancia_regressores({"x": p})
            grade, worst = NBRValidator._classify_item5_significancia_regressores({"x": p})
            assert grade == expected["grade"]
            assert worst == pytest.approx(expected["worst_p"])
        # Pendente -> 0 (conservador), worst_p NaN, nunca um grau.
        grade, worst = NBRValidator._classify_item5_significancia_regressores(
            {"x": float("nan")}
        )
        assert rules.classify_item5_significancia_regressores({"x": float("nan")})["grade"] is None
        assert grade == 0
        assert math.isnan(worst)

    def test_adapter_item6_agrees_with_rules(self):
        for p in (0.01, 0.010001, 0.02, 0.020001, 0.05, 0.050001):
            assert (
                NBRValidator._classify_item6_significancia_global(p)
                == rules.classify_item6_significancia_global(p)["grade"]
            )
        assert rules.classify_item6_significancia_global(None)["grade"] is None
        assert NBRValidator._classify_item6_significancia_global(None) == 0

    def test_adapter_precisao_agrees_with_rules(self):
        for amp in (30.0, 30.000001, 40.0, 50.0, 50.01, None):
            grade, _detail = NBRValidator._classify_precisao(amp)
            assert grade == rules.classify_precisao(amp)["grade"]

    def test_assess_normative_uses_the_same_single_authority(self):
        ctx = {
            "n": 24,
            "k": 3,
            "intercept": True,
            "pvalues": {"const": 0.001, "x1": 0.05, "x2": 0.08, "x3": 0.02},
            "f_pvalue": 0.005,
            "axes": [quantitative_axis()],
            "grau_item1": 2,
            "grau_item3": 2,
            "item1_provenance": {"source": "laudo/vistoria", "ref": "fixture"},
            "item3_provenance": {"source": "planilha", "ref": "fixture"},
            "amplitude_pct": 28.0,
        }
        out = assess_normative(ctx)
        item_grades = {it["item"]: it["grade"] for it in out["fundamentacao"]["items"]}

        # Graus por item recalculados à mão:
        #   item 1 = 2 (declarado), item 3 = 2 (declarado)
        #   item 2: n=24, k=3 -> 6(k+1)=24 -> Grau III
        #   item 4: avaliando dentro de [min, max] -> Grau III
        #   item 5: pior p = 0.08 <= 0.10 -> Grau III
        #   item 6: p = 0.005 <= 0.01 -> Grau III
        #   pontos = 2 + 3 + 2 + 3 + 3 + 3 = 16 -> Grau III
        assert item_grades == {1: 2, 2: 3, 3: 2, 4: 3, 5: 3, 6: 3}
        assert out["fundamentacao"]["points"] == 16
        assert out["fundamentacao"]["grade"] == 3
        assert out["precisao"]["grade"] == 3
        assert out["precisao"]["status"] == rules.PRECISAO_CLASSIFIED

        # A mesma autoridade: os classificadores diretos reproduzem tudo.
        assert rules.classify_item2_quantidade_dados(24, 3)["grade"] == 3
        assert rules.classify_item5_significancia_regressores(ctx["pvalues"])["grade"] == 3
        assert rules.classify_item6_significancia_global(0.005)["grade"] == 3
        assert rules.classify_fundamentacao(item_grades)["grade"] == 3

    def test_assess_normative_pending_item2_does_not_consult_any_alternative(self):
        ctx = {
            "n": None,
            "k": None,
            "pvalues": {"const": 0.001, "x1": 0.001},
            "f_pvalue": 0.001,
            "axes": [quantitative_axis()],
            "grau_item1": 3,
            "grau_item3": 3,
            "item1_provenance": {"ref": "fixture"},
            "item3_provenance": {"ref": "fixture"},
        }
        out = assess_normative(ctx)
        item_grades = {it["item"]: it["grade"] for it in out["fundamentacao"]["items"]}
        assert item_grades[2] is None
        assert out["fundamentacao"]["grade"] is None
        assert 2 in out["fundamentacao"]["pending_items"]
        # Cinco itens em Grau III = 15 pontos: acima do mínimo do Grau II (10)
        # e do Grau I (6). Nenhum classificador alternativo pode licenciar grau.
        assert out["fundamentacao"]["points"] == 15
        assert out["verification_status"] in (rules.VS_PARTIAL, rules.VS_PENDING)

    def test_assess_normative_pending_item4_does_not_consult_any_alternative(self):
        # Sem eixos do avaliando o item 4 é pendente por construção.
        ctx = {
            "n": 24,
            "k": 3,
            "intercept": True,
            "pvalues": {"const": 0.001, "x1": 0.001, "x2": 0.001, "x3": 0.001},
            "f_pvalue": 0.001,
            "grau_item1": 3,
            "grau_item3": 3,
            "item1_provenance": {"ref": "fixture"},
            "item3_provenance": {"ref": "fixture"},
        }
        out = assess_normative(ctx)
        item_grades = {it["item"]: it["grade"] for it in out["fundamentacao"]["items"]}
        assert item_grades[4] is None
        assert out["fundamentacao"]["grade"] is None
        assert out["fundamentacao"]["pending_items"] == [4]
        assert out["fundamentacao"]["points"] == 15


# ---------------------------------------------------------------------------
# Tabela 5 — grau de precisão
# ---------------------------------------------------------------------------


class TestPrecisaoFronteiras:
    @pytest.mark.parametrize(
        "amp, grade",
        [
            (0.0, 3),
            (30.0, 3),        # exatamente 30% -> Grau III
            (30.000001, 2),
            (40.0, 2),        # exatamente 40% -> Grau II
            (40.000001, 1),
            (50.0, 1),        # exatamente 50% -> Grau I
        ],
    )
    def test_classified_boundaries(self, amp, grade):
        res = rules.classify_precisao(amp)
        assert res["status"] == rules.PRECISAO_CLASSIFIED
        assert res["grade"] == grade

    def test_above_fifty_is_unclassified_not_a_grade(self):
        for amp in (50.01, 50.000001, 80.0, 500.0):
            res = rules.classify_precisao(amp)
            assert res["status"] == rules.PRECISAO_UNCLASSIFIED
            assert res["grade"] is None

    def test_absent_amplitude_is_not_computed(self):
        res = rules.classify_precisao(None)
        assert res["status"] == rules.PRECISAO_NOT_COMPUTED
        assert res["grade"] is None
        assert res["amplitude_pct"] is None

    def test_non_finite_amplitude_is_error(self):
        for amp in (float("nan"), float("inf"), float("-inf"), "abc"):
            res = rules.classify_precisao(amp)
            assert res["status"] == rules.PRECISAO_ERROR
            assert res["grade"] is None

    def test_negative_amplitude_is_error(self):
        res = rules.classify_precisao(-0.0001)
        assert res["status"] == rules.PRECISAO_ERROR
        assert res["grade"] is None

    def test_tabled_limits_are_the_normative_ones(self):
        assert rules.PRECISAO_LIM_III == 30.0
        assert rules.PRECISAO_LIM_II == 40.0
        assert rules.PRECISAO_LIM_I == 50.0


# ---------------------------------------------------------------------------
# Tabela 1 item 4 — extrapolação
# ---------------------------------------------------------------------------


class TestItem4Extrapolacao:
    def test_in_sample_subject_is_grau_iii(self):
        res = rules.classify_item4_extrapolacao([quantitative_axis(value=50.0)])
        assert res["grade"] == 3
        assert res["calculation"]["extrapolated"] == []
        assert res["calculation"]["in_sample"] == ["area"]

    @pytest.mark.parametrize("value", [10.0, 100.0])
    def test_subject_exactly_on_the_sample_frontier_is_in_sample(self, value):
        res = rules.classify_item4_extrapolacao([quantitative_axis(value=value)])
        assert res["grade"] == 3

    def test_exactly_twice_the_sample_max_is_still_inside_the_measure_window(self):
        # MEASURE_UPPER_FACTOR = 2.0: 2 x 100 = 200 é admissível quanto à medida,
        # mas sem a condição (b) o item permanece pendente (nunca aprovado).
        res = rules.classify_item4_extrapolacao([quantitative_axis(value=200.0)])
        assert res["calculation"]["out_of_measure"] == []
        assert res["calculation"]["extrapolated"] == ["area"]
        assert res["grade"] is None

    def test_beyond_twice_the_sample_max_is_out_of_measure_and_not_approved(self):
        res = rules.classify_item4_extrapolacao([quantitative_axis(value=250.0)])
        assert res["calculation"]["out_of_measure"] == ["area"]
        assert res["grade"] == 0
        assert res["grade"] != 3

    def test_below_half_the_sample_min_is_out_of_measure(self):
        # MEASURE_LOWER_FACTOR = 0.5: metade de 10 = 5. 4.9 está fora.
        res = rules.classify_item4_extrapolacao([quantitative_axis(value=4.9)])
        assert res["calculation"]["out_of_measure"] == ["area"]
        assert res["grade"] == 0
        # Exatamente a metade do mínimo ainda satisfaz (a).
        on_bound = rules.classify_item4_extrapolacao([quantitative_axis(value=5.0)])
        assert on_bound["calculation"]["out_of_measure"] == []
        assert on_bound["calculation"]["extrapolated"] == ["area"]

    def test_measure_admissible_extrapolation_without_predict_original_is_pending(self):
        res = rules.classify_item4_extrapolacao([quantitative_axis(value=150.0)])
        assert res["grade"] is None
        assert res["evidence_status"] == rules.EVIDENCE_PENDING
        assert res["calculation"]["value_check"] == "missing_predict_original"
        codes = [i["code"] for i in res["issues"]]
        assert "item4_missing_predict_original" in codes

    def test_measure_factors_are_the_recorded_interpretation(self):
        assert rules.MEASURE_UPPER_FACTOR == 2.0
        assert rules.MEASURE_LOWER_FACTOR == 0.5
        assert rules.VALUE_LIMIT_GRAU_II == 0.15
        assert rules.VALUE_LIMIT_GRAU_I == 0.20

    def test_delta_ten_percent_on_one_variable_is_grau_ii(self):
        # avaliando area=150, fronteira=100.
        # ŷ(150) = 100 + 0.2*(150-100) = 110 ; ŷ(100) = 100
        # |Δ| = 10/100 = 10% <= 15% -> Grau II (uma única variável).
        axis = quantitative_axis(value=150.0)
        predict = linear_predictor("area", 100.0, 0.2, 100.0)
        res = rules.classify_item4_extrapolacao([axis], predict_original=predict)
        assert res["calculation"]["per_si"]["area"]["delta_pct"] == pytest.approx(10.0)
        assert res["grade"] == 2

    def test_delta_exactly_fifteen_percent_is_grau_ii(self):
        # ŷ(150) = 100 + 0.3*50 = 115 -> |Δ| = 15% exatamente -> Grau II.
        axis = quantitative_axis(value=150.0)
        predict = linear_predictor("area", 100.0, 0.3, 100.0)
        res = rules.classify_item4_extrapolacao([axis], predict_original=predict)
        assert res["calculation"]["per_si"]["area"]["delta_pct"] == pytest.approx(15.0)
        assert res["grade"] == 2

    def test_delta_eighteen_percent_is_grau_i(self):
        # ŷ(150) = 100 + 0.36*50 = 118 -> |Δ| = 18%.
        # 18% > 15% (II reprovado) e <= 20% de per si e simultaneamente -> Grau I.
        axis = quantitative_axis(value=150.0)
        predict = linear_predictor("area", 100.0, 0.36, 100.0)
        res = rules.classify_item4_extrapolacao([axis], predict_original=predict)
        assert res["calculation"]["per_si"]["area"]["delta_pct"] == pytest.approx(18.0)
        assert res["grade"] == 1

    def test_delta_exactly_twenty_percent_is_grau_i(self):
        axis = quantitative_axis(value=150.0)
        predict = linear_predictor("area", 100.0, 0.4, 100.0)
        res = rules.classify_item4_extrapolacao([axis], predict_original=predict)
        assert res["calculation"]["per_si"]["area"]["delta_pct"] == pytest.approx(20.0)
        assert res["grade"] == 1

    def test_delta_twenty_five_percent_is_not_admitted(self):
        # ŷ(150) = 100 + 0.5*50 = 125 -> |Δ| = 25% > 20% -> não admitida.
        axis = quantitative_axis(value=150.0)
        predict = linear_predictor("area", 100.0, 0.5, 100.0)
        res = rules.classify_item4_extrapolacao([axis], predict_original=predict)
        assert res["calculation"]["per_si"]["area"]["delta_pct"] == pytest.approx(25.0)
        assert res["grade"] == 0

    def test_any_extrapolation_forbids_grau_iii(self):
        axis = quantitative_axis(value=150.0)
        for slope in (0.0, 0.2, 0.36, 0.5):
            predict = linear_predictor("area", 100.0, slope, 100.0)
            res = rules.classify_item4_extrapolacao([axis], predict_original=predict)
            assert res["grade"] != 3, "Grau III = extrapolação NÃO ADMITIDA"

    def test_two_extrapolated_variables_cannot_reach_grau_ii(self):
        # Grau II admite extrapolação de APENAS UMA variável.
        # Com duas variáveis extrapoladas, mesmo com |Δ| pequeno, o teto é Grau I.
        axes = [
            quantitative_axis(name="area", sample_min=10.0, sample_max=100.0, value=110.0),
            quantitative_axis(name="frente", sample_min=5.0, sample_max=20.0, value=22.0),
        ]

        def predict(raw):
            # ŷ = 1000 + 1*(area-100) + 1*(frente-20)
            return 1000.0 + (float(raw["area"]) - 100.0) + (float(raw["frente"]) - 20.0)

        # ŷ(avaliando) = 1000 + 10 + 2 = 1012
        # fronteira de per si (area=100) -> 1000 + 0 + 2 = 1002 -> |Δ| = 10/1002 ~ 0.998%
        # fronteira de per si (frente=20) -> 1000 + 10 + 0 = 1010 -> |Δ| = 2/1010 ~ 0.198%
        # fronteira simultânea -> 1000 -> |Δ| = 12/1000 = 1.2% <= 20%
        res = rules.classify_item4_extrapolacao(axes, predict_original=predict)
        assert sorted(res["calculation"]["extrapolated"]) == ["area", "frente"]
        assert res["calculation"]["simultaneous"]["delta_pct"] == pytest.approx(1.2)
        assert res["grade"] == 1

    def test_axes_absent_is_pending_not_approval(self):
        for axes in (None, []):
            res = rules.classify_item4_extrapolacao(axes)
            assert res["grade"] is None
            assert res["evidence_status"] == rules.EVIDENCE_PENDING

    def test_predict_original_failure_is_pending_not_a_grade(self):
        def boom(raw):
            raise RuntimeError("modelo singular")

        res = rules.classify_item4_extrapolacao(
            [quantitative_axis(value=150.0)], predict_original=boom
        )
        assert res["grade"] is None
        assert res["evidence_status"] == rules.EVIDENCE_PENDING

    def test_non_finite_prediction_is_pending_not_a_grade(self):
        res = rules.classify_item4_extrapolacao(
            [quantitative_axis(value=150.0)],
            predict_original=lambda raw: float("nan"),
        )
        assert res["grade"] is None
        assert res["evidence_status"] == rules.EVIDENCE_PENDING

    def test_measure_only_pass_cannot_be_reenabled_by_the_caller(self):
        axis = quantitative_axis(value=150.0)
        forced = rules.classify_item4_extrapolacao([axis], allow_measure_only_pass=True)
        assert forced["grade"] is None


# ---------------------------------------------------------------------------
# A03 — correção documental em NBRValidator.validate_model
# ---------------------------------------------------------------------------


class TestValidateModelDocumentaryFix:
    @staticmethod
    def _fixture():
        # n = 20, k = 1 -> item 2: 6(k+1)=12 <= 20 -> Grau III
        # p regressor = 0.01 <= 0.10 -> item 5 Grau III
        # f_pvalue = 0.001 <= 0.01 -> item 6 Grau III
        metrics = make_metrics(f_pvalue=0.001)
        model_result = make_model_result(metrics, {"const": 0.001, "x": 0.01})
        X = pd.DataFrame({"const": 1, "x": range(20)})
        y = pd.Series(range(20))
        return model_result, X, y

    def test_no_documentary_arguments_scores_items_1_and_3_as_zero(self):
        model_result, X, y = self._fixture()
        res = NBRValidator.validate_model(model_result, X, y, degree=1)
        scores = {i.item: i.grau_achieved for i in res.item_scores}

        assert scores[1] == 0, "ausência de declaração não vale Grau I (item 1)"
        assert scores[3] == 0, "ausência de declaração não vale Grau I (item 3)"
        # Itens calculados, à mão: 2 -> III, 5 -> III, 6 -> III; item 4 = 0
        # (não avaliado nesta etapa, conservador).
        assert scores[2] == 3
        assert scores[4] == 0
        assert scores[5] == 3
        assert scores[6] == 3
        # pontos = 0 + 3 + 0 + 0 + 3 + 3 = 9
        assert res.grau_fundamentacao_pontos == 9
        # 9 < 16; Grau II exige obrigatórios >= 2 (item 4 = 0);
        # Grau I exige todos >= 1 (itens 1, 3 e 4 = 0) -> não classificado.
        assert res.grau_fundamentacao is None
        assert res.is_valid is False

    def test_declared_documentary_items_with_provenance_are_scored_as_declared(self):
        model_result, X, y = self._fixture()
        res = NBRValidator.validate_model(
            model_result, X, y, degree=1,
            grau_item1=2, grau_item3=3,
            item1_provenance={"source": "laudo/vistoria", "ref": "fixture"},
            item3_provenance={"source": "planilha de dados", "ref": "fixture"},
        )
        scores = {i.item: i.grau_achieved for i in res.item_scores}
        assert scores[1] == 2
        assert scores[3] == 3
        # pontos = 2 + 3 + 3 + 0 + 3 + 3 = 14
        assert res.grau_fundamentacao_pontos == 14
        # Ainda assim o item 4 vale 0 nesta etapa -> nenhum grau é licenciado.
        assert res.grau_fundamentacao is None

    def test_declared_grade_zero_is_not_upgraded(self):
        model_result, X, y = self._fixture()
        res = NBRValidator.validate_model(
            model_result, X, y, degree=1,
            grau_item1=0, grau_item3=0,
            item1_provenance={"ref": "fixture"},
            item3_provenance={"ref": "fixture"},
        )
        scores = {i.item: i.grau_achieved for i in res.item_scores}
        assert scores[1] == 0
        assert scores[3] == 0
        assert res.grau_fundamentacao is None

    def test_documentary_declaration_without_provenance_is_not_verified_evidence(self):
        declared = rules.classify_documentary_item(
            1, 3, None, description="Caracterização do imóvel avaliando"
        )
        assert declared["grade"] == 3
        assert declared["provenance_verified"] is False
        assert declared["evidence_status"] == rules.EVIDENCE_DECLARED

        with_prov = rules.classify_documentary_item(
            1, 3, {"source": "vistoria", "ref": "fixture"},
            description="Caracterização do imóvel avaliando",
        )
        assert with_prov["provenance_verified"] is True

    def test_undeclared_documentary_item_is_pending_not_grau_i(self):
        for item in (1, 3):
            res = rules.classify_documentary_item(
                item, None, {"ref": "algo"}, description="x"
            )
            assert res["grade"] is None
            assert res["points"] is None
            assert res["evidence_status"] == rules.EVIDENCE_PENDING

    def test_out_of_range_declared_grade_is_pending(self):
        for bad in (-1, 4, "III", 2.5e300):
            res = rules.classify_documentary_item(1, bad, {"ref": "x"}, description="x")
            assert res["grade"] is None
