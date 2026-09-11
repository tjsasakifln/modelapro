import pytest
import pandas as pd
import numpy as np
from modules.nbr14653_validation import NBRValidator
from modules.results import ModelResult, ModelMetrics
from modules.config_manager import config


def make_metrics(r2=0.80, r2_adjusted=0.78, f_pvalue=0.001, normality_pvalue=0.5,
                  homoscedasticity_pvalue=0.5):
    return ModelMetrics(
        r2=r2, r2_adjusted=r2_adjusted, f_statistic=50, f_pvalue=f_pvalue,
        std_error=0.1, aic=10, bic=12, condition_number=10,
        normality_pvalue=normality_pvalue, homoscedasticity_pvalue=homoscedasticity_pvalue,
        autocorrelation_durbin_watson=2.0,
    )


def make_model_result(metrics, pvalues, vif=None, n=20):
    if vif is None:
        vif = {v: 1.2 for v in pvalues if v != 'const'}
        vif['const'] = 1.0
    return ModelResult(
        success=True, model_metrics=metrics,
        pvalues=pvalues, vif=vif,
        residuals=[0.1] * n, fitted_values=[1.0] * n,
    )


class TestItem6SignificanciaGlobal:
    """Item 6 (teste F): f_pvalue entre 0.02 e 0.05 deve pontuar Grau I (1),
    não mais ser aprovado incondicionalmente."""

    def test_classifier_boundaries(self):
        assert NBRValidator._classify_item6_significancia_global(0.005) == 3
        assert NBRValidator._classify_item6_significancia_global(0.01) == 3
        assert NBRValidator._classify_item6_significancia_global(0.015) == 2
        assert NBRValidator._classify_item6_significancia_global(0.02) == 2
        # The specific case requested: strictly between 0.02 and 0.05 -> Grau I
        assert NBRValidator._classify_item6_significancia_global(0.03) == 1
        assert NBRValidator._classify_item6_significancia_global(0.049) == 1
        assert NBRValidator._classify_item6_significancia_global(0.05) == 1
        assert NBRValidator._classify_item6_significancia_global(0.051) == 0
        assert NBRValidator._classify_item6_significancia_global(0.5) == 0

    def test_integration_item6_grau1_not_auto_approved_for_higher_degree(self):
        metrics = make_metrics(f_pvalue=0.03)
        model_result = make_model_result(metrics, {'x': 0.01, 'const': 0.01})
        X = pd.DataFrame({'const': 1, 'x': range(20)})
        y = pd.Series(range(20))

        res = NBRValidator.validate_model(model_result, X, y, degree=1)
        item6 = next(i for i in res.item_scores if i.item == 6)
        assert item6.grau_achieved == 1

        # Requesting Degree II should NOT be satisfied since item 6 only
        # reaches Grau I (Tabela 2 requires obrigatorios >= 2 for Grau II).
        res_deg2 = NBRValidator.validate_model(model_result, X, y, degree=2)
        item6_deg2 = next(i for i in res_deg2.item_scores if i.item == 6)
        assert item6_deg2.grau_achieved == 1
        assert res_deg2.is_valid is False


class TestLowR2DoesNotBlock:
    """MIN_R2 não é usado como critério de reprovação (Anexo A.4)."""

    def test_low_r2_does_not_fail_model_that_passes_items(self):
        metrics = make_metrics(r2=0.3, r2_adjusted=0.25, f_pvalue=0.001)
        model_result = make_model_result(metrics, {'x': 0.01, 'const': 0.01})
        X = pd.DataFrame({'const': 1, 'x': range(20)})
        y = pd.Series(range(20))

        res = NBRValidator.validate_model(model_result, X, y, degree=1)
        # Finalize with an in-range avaliando so item 4 is fully scored.
        res = NBRValidator.finalize_precision_and_extrapolation(
            res, amplitude_pct=25.0,
            extrapolation_details=[
                {"variable": "x", "avaliando_value": 10, "sample_min": 0, "sample_max": 19}
            ],
            degree=1,
        )

        assert res.grau_fundamentacao is not None
        assert res.grau_fundamentacao >= 1
        assert res.is_valid is True
        assert not any("R²" in m or "R2" in m for m in res.messages)
        assert any("R²" in w for w in res.warnings)
        # MIN_R2 must not be referenced as a live gate anywhere outside its
        # own definition in config_manager.py (kept only for reference).
        import subprocess
        grep = subprocess.run(
            ["grep", "-rn", "MIN_R2", "modules", "backend"],
            cwd=__file__.rsplit("/tests/", 1)[0], capture_output=True, text=True,
        )
        hits = [l for l in grep.stdout.splitlines() if "config_manager.py" not in l]
        assert hits == [], f"MIN_R2 referenced outside config_manager.py: {hits}"


class TestClassifyFundamentacao:
    """Tabela 2: pontos mínimos E itens obrigatórios devem ser satisfeitos."""

    def test_grau_iii(self):
        scores = {1: 2, 2: 3, 3: 2, 4: 3, 5: 3, 6: 3}
        grau, pontos = NBRValidator._classify_fundamentacao(scores)
        assert grau == 3
        assert pontos == 16

    def test_grau_ii(self):
        scores = {1: 1, 2: 2, 3: 1, 4: 2, 5: 2, 6: 2}
        grau, pontos = NBRValidator._classify_fundamentacao(scores)
        assert grau == 2
        assert pontos == 10

    def test_grau_i(self):
        scores = {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1}
        grau, pontos = NBRValidator._classify_fundamentacao(scores)
        assert grau == 1
        assert pontos == 6

    def test_none_when_below_all_thresholds(self):
        scores = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
        grau, pontos = NBRValidator._classify_fundamentacao(scores)
        assert grau is None
        assert pontos == 0

    def test_points_enough_but_required_item_downgrades_from_iii_to_ii(self):
        # Enough points for Grau III (17 >= 16) but item 4 (obrigatorio) only
        # reaches 2 (< 3 required for III) -> must be downgraded to Grau II,
        # not rejected outright, since Grau II's requirements are still met.
        scores = {1: 3, 2: 3, 3: 3, 4: 2, 5: 3, 6: 3}
        grau, pontos = NBRValidator._classify_fundamentacao(scores)
        assert pontos == 17
        assert grau == 2

    def test_points_enough_but_required_item_zero_yields_none(self):
        # Points sufficient for Grau I (7 >= 6) but item 4 = 0 fails the
        # "all items >= 1" requirement -> no classification at all, despite
        # having enough total points.
        scores = {1: 3, 2: 1, 3: 1, 4: 0, 5: 1, 6: 1}
        grau, pontos = NBRValidator._classify_fundamentacao(scores)
        assert pontos == 7
        assert grau is None


class TestItem2QuantidadeDados:
    """Item 2: fórmulas 3(k+1) / 4(k+1) / 6(k+1)."""

    @pytest.mark.parametrize("k", [0, 1, 2, 4])
    def test_formula_boundaries(self, k):
        grau1_min = 3 * (k + 1)
        grau2_min = 4 * (k + 1)
        grau3_min = 6 * (k + 1)

        assert NBRValidator._classify_item2_quantidade_dados(grau1_min - 1, k) == 0
        assert NBRValidator._classify_item2_quantidade_dados(grau1_min, k) == 1
        assert NBRValidator._classify_item2_quantidade_dados(grau2_min - 1, k) == 1
        assert NBRValidator._classify_item2_quantidade_dados(grau2_min, k) == 2
        assert NBRValidator._classify_item2_quantidade_dados(grau3_min - 1, k) == 2
        assert NBRValidator._classify_item2_quantidade_dados(grau3_min, k) == 3


class TestItem5SignificanciaRegressores:
    """Item 5: o PIOR (maior) p-valor entre os regressores determina o grau."""

    def test_worst_pvalue_determines_grade_not_average_or_best(self):
        # Average ~0.1 (would be Grau III if averaged), best is 0.01, but the
        # worst (0.29) must dominate -> Grau I.
        pvalues = {'const': 0.001, 'x1': 0.01, 'x2': 0.29}
        grau, worst = NBRValidator._classify_item5_significancia_regressores(pvalues)
        assert worst == 0.29
        assert grau == 1

    def test_worst_pvalue_fails_even_if_average_would_pass(self):
        # Average ~0.18 (would look like Grau II if averaged), but worst
        # (0.35) exceeds every threshold -> Grau 0.
        pvalues = {'x1': 0.01, 'x2': 0.35}
        grau, worst = NBRValidator._classify_item5_significancia_regressores(pvalues)
        assert worst == 0.35
        assert grau == 0

    def test_const_excluded_from_worst_pvalue(self):
        pvalues = {'const': 0.9, 'x1': 0.05}
        grau, worst = NBRValidator._classify_item5_significancia_regressores(pvalues)
        assert worst == 0.05
        assert grau == 3


class TestFinalizePrecisionAndExtrapolation:
    def _base_validation_result(self):
        metrics = make_metrics(f_pvalue=0.001)
        model_result = make_model_result(metrics, {'x': 0.01, 'const': 0.01})
        X = pd.DataFrame({'const': 1, 'x': range(20)})
        y = pd.Series(range(20))
        return NBRValidator.validate_model(model_result, X, y, degree=1)

    @pytest.mark.parametrize("amplitude_pct,expected_grau", [
        (10.0, 3),
        (30.0, 3),
        (30.01, 2),
        (40.0, 2),
        (40.01, 1),
        (50.0, 1),
        (50.01, None),
        (75.0, None),
    ])
    def test_grau_precisao_ranges(self, amplitude_pct, expected_grau):
        res = self._base_validation_result()
        res = NBRValidator.finalize_precision_and_extrapolation(
            res, amplitude_pct=amplitude_pct,
            extrapolation_details=[
                {"variable": "x", "avaliando_value": 10, "sample_min": 0, "sample_max": 19}
            ],
            degree=1,
        )
        assert res.grau_precisao == expected_grau
        assert res.precisao_amplitude_pct == amplitude_pct
        if expected_grau is None:
            assert any("não classificável" in w for w in res.warnings)

    def test_extrapolation_within_limits(self):
        res = self._base_validation_result()
        res = NBRValidator.finalize_precision_and_extrapolation(
            res, amplitude_pct=20.0,
            extrapolation_details=[
                {"variable": "x", "avaliando_value": 10, "sample_min": 0, "sample_max": 19}
            ],
            degree=1,
        )
        item4 = next(i for i in res.item_scores if i.item == 4)
        assert item4.grau_achieved == 3

    def test_extrapolation_admitida_uma_variavel(self):
        # value=25, sample [0,19] -> outside [min,max] but inside extended
        # [0.5*min, 2*max] = [0, 38] -> Grau II (admitted for 1 variable).
        res = self._base_validation_result()
        res = NBRValidator.finalize_precision_and_extrapolation(
            res, amplitude_pct=20.0,
            extrapolation_details=[
                {"variable": "x", "avaliando_value": 25, "sample_min": 0, "sample_max": 19}
            ],
            degree=1,
        )
        item4 = next(i for i in res.item_scores if i.item == 4)
        assert item4.grau_achieved == 2

    def test_extrapolation_admitida_duas_variaveis_grau_i(self):
        # Two variables extrapolated (each within its own extended interval)
        # -> Grau II's "no máximo 1 variável" rule is violated, so it drops
        # to Grau I (still admitted, no upper limit on variable count there).
        res = self._base_validation_result()
        res = NBRValidator.finalize_precision_and_extrapolation(
            res, amplitude_pct=20.0,
            extrapolation_details=[
                {"variable": "x", "avaliando_value": 25, "sample_min": 0, "sample_max": 19},
                {"variable": "z", "avaliando_value": 3, "sample_min": 5, "sample_max": 10},
            ],
            degree=1,
        )
        item4 = next(i for i in res.item_scores if i.item == 4)
        assert item4.grau_achieved == 1

    def test_extrapolation_out_of_extended_interval(self):
        # value=50 way beyond ext_max=38 -> Grau 0, even for Grau I.
        res = self._base_validation_result()
        res = NBRValidator.finalize_precision_and_extrapolation(
            res, amplitude_pct=20.0,
            extrapolation_details=[
                {"variable": "x", "avaliando_value": 50, "sample_min": 0, "sample_max": 19}
            ],
            degree=1,
        )
        item4 = next(i for i in res.item_scores if i.item == 4)
        assert item4.grau_achieved == 0
        assert res.grau_fundamentacao is None


class TestModelBuilderPrecisionAndExtrapolation:
    def test_add_precision_and_extrapolation_simple_model(self):
        from modules.model_builder import ModelBuilder

        np.random.seed(0)
        n = 30
        area = np.linspace(50, 200, n)
        quartos = np.random.randint(1, 5, n)
        noise = np.random.normal(0, 500, n)
        preco = 1000 * area + 5000 * quartos + 20000 + noise

        X = pd.DataFrame({'area': area, 'quartos': quartos})
        y = pd.Series(preco)

        builder = ModelBuilder()
        result = builder.build_model(X, y, degree=1)
        assert result.success is True

        avaliando_raw = {'area': 120.0, 'quartos': 3}
        result2 = builder.add_precision_and_extrapolation(
            result, avaliando_raw, original_df=X, degree=1
        )

        vr = result2.validation_result
        assert vr is not None
        assert vr.precisao_amplitude_pct is not None
        assert vr.precisao_amplitude_pct >= 0
        assert np.isfinite(vr.precisao_amplitude_pct)

        details = vr.details.get("extrapolation_details")
        assert details is not None
        variables = {d["variable"] for d in details}
        assert variables == {"area", "quartos"}
        for d in details:
            assert d["sample_min"] <= d["sample_max"]

    def test_extrapolation_range_uses_data_effectively_used_after_outlier_removal(self):
        """
        Item 4 (extrapolação, 9.2.1/Anexo A.2) must derive sample_min/sample_max
        from the SAME "dados de mercado efetivamente utilizados" as item 2 (n) —
        i.e. from the data AFTER build_model()'s outlier removal, not from the
        raw original_df. Otherwise an outlier removed from the fitted model
        could still inflate [sample_min, sample_max] (and the extended
        [0.5*min, 2*max] interval), making item 4 more permissive than the
        actually-fitted model supports.
        """
        from modules.model_builder import ModelBuilder

        np.random.seed(0)
        n = 30
        area = np.linspace(50, 200, n)
        quartos = np.random.randint(1, 5, n)
        noise = np.random.normal(0, 500, n)
        preco = 1000 * area + 5000 * quartos + 20000 + noise

        # Plant one extreme, high-leverage outlier far outside the regular
        # sample range with a price well off the fitted line, so outlier
        # detection (Cook's distance / studentized residuals) flags it.
        area = np.append(area, 900.0)
        quartos = np.append(quartos, 2)
        preco = np.append(preco, 15000.0)

        X = pd.DataFrame({'area': area, 'quartos': quartos})
        y = pd.Series(preco)

        builder = ModelBuilder()
        result = builder.build_model(X, y, degree=1)
        assert result.success is True

        # Sanity check the fixture: the outlier must actually have been
        # detected and excluded from the refit, and n (item 2) must reflect
        # that post-removal sample.
        assert result.outliers_removed, "fixture outlier was not detected; test is not exercising the fix"
        assert len(result.residuals) == len(X) - len(result.outliers_removed)

        avaliando_raw = {'area': 120.0, 'quartos': 3}
        result2 = builder.add_precision_and_extrapolation(
            result, avaliando_raw, original_df=X, degree=1
        )

        details = result2.validation_result.details.get("extrapolation_details")
        area_detail = next(d for d in details if d["variable"] == "area")

        # The raw original_df contains the planted outlier (area=900), but
        # item 4's sample_max must come from the data effectively used by
        # the fitted model (max area ~200), not the raw 900.
        assert area_detail["sample_max"] < X['area'].max()
        assert area_detail["sample_max"] == pytest.approx(200.0, abs=1.0)


class TestVIFDoesNotBlock:
    """VIF is Anexo A.2.1.5.2 informative-only (no normative cutoff): a high
    VIF must produce a warning but must NEVER by itself reprove is_valid or
    prevent grau_fundamentacao from being classified."""

    def test_high_vif_is_flagged_as_warning_not_rejection(self):
        metrics = make_metrics(f_pvalue=0.001)
        pvalues = {'x1': 0.01, 'x2': 0.01, 'const': 0.01}
        # Two strongly collinear regressors -> VIF far above config.MAX_VIF (10).
        vif = {'x1': 150.0, 'x2': 150.0, 'const': 1.0}
        model_result = make_model_result(metrics, pvalues, vif=vif)
        X = pd.DataFrame({'const': 1, 'x1': range(20), 'x2': range(20)})
        y = pd.Series(range(20))

        res = NBRValidator.validate_model(model_result, X, y, degree=1)

        assert res.details["vif_violation"] is True
        assert any("VIF" in w for w in res.warnings)
        # Never a rejection/blocking message anywhere.
        assert not any("VIF" in m for m in res.messages)

    def test_high_vif_does_not_prevent_grau_fundamentacao_or_is_valid(self):
        metrics = make_metrics(f_pvalue=0.001)
        pvalues = {'x1': 0.01, 'x2': 0.01, 'const': 0.01}
        vif = {'x1': 150.0, 'x2': 150.0, 'const': 1.0}
        model_result = make_model_result(metrics, pvalues, vif=vif)
        X = pd.DataFrame({'const': 1, 'x1': range(20), 'x2': range(20)})
        y = pd.Series(range(20))

        res = NBRValidator.validate_model(model_result, X, y, degree=1)
        res = NBRValidator.finalize_precision_and_extrapolation(
            res, amplitude_pct=25.0,
            extrapolation_details=[
                {"variable": "x1", "avaliando_value": 10, "sample_min": 0, "sample_max": 19},
                {"variable": "x2", "avaliando_value": 10, "sample_min": 0, "sample_max": 19},
            ],
            degree=1,
        )

        # Despite VIF >> MAX_VIF throughout, the model still classifies and
        # is valid - VIF alone must never be the reason for a None grau or
        # is_valid=False.
        assert res.grau_fundamentacao is not None
        assert res.grau_fundamentacao >= 1
        assert res.is_valid is True
        assert any("VIF" in w for w in res.warnings)


class TestValoresAdmissiveisCampoDeArbitrio:
    """Anexo A.10.1.1: valores admissíveis = interseção entre o IC de 80% e
    o campo de arbítrio (±CAMPO_ARBITRIO) em torno da estimativa central.
    Whichever interval is narrower on a given side must prevail."""

    def _base_validation_result(self):
        metrics = make_metrics(f_pvalue=0.001)
        model_result = make_model_result(metrics, {'x': 0.01, 'const': 0.01})
        X = pd.DataFrame({'const': 1, 'x': range(20)})
        y = pd.Series(range(20))
        return NBRValidator.validate_model(model_result, X, y, degree=1)

    def test_campo_de_arbitrio_narrower_than_ic80_prevails(self):
        # central = 1000 -> campo de arbítrio (±15%) = [850, 1150].
        # IC de 80% is wider: [700, 1300]. The narrower interval (campo de
        # arbítrio) must win on both sides.
        res = self._base_validation_result()
        central = 1000.0
        ci_lower, ci_upper = 700.0, 1300.0
        amplitude_pct = abs(ci_upper - ci_lower) / central * 100

        res = NBRValidator.finalize_precision_and_extrapolation(
            res, amplitude_pct=amplitude_pct,
            extrapolation_details=[
                {"variable": "x", "avaliando_value": 10, "sample_min": 0, "sample_max": 19}
            ],
            degree=1,
            ci_lower=ci_lower, ci_upper=ci_upper, central_estimate=central,
        )

        campo_inf = central * (1 - config.CAMPO_ARBITRIO)
        campo_sup = central * (1 + config.CAMPO_ARBITRIO)
        assert campo_inf == pytest.approx(850.0)
        assert campo_sup == pytest.approx(1150.0)

        assert res.valores_admissiveis_inferior == pytest.approx(campo_inf)
        assert res.valores_admissiveis_superior == pytest.approx(campo_sup)
        # Sanity: the campo de arbítrio bounds are indeed strictly inside
        # the (wider) IC bounds in this scenario.
        assert ci_lower < campo_inf < campo_sup < ci_upper

    def test_ic80_narrower_than_campo_de_arbitrio_prevails(self):
        # central = 1000 -> campo de arbítrio (±15%) = [850, 1150].
        # IC de 80% is narrower: [900, 1050]. The narrower interval (IC 80%)
        # must win on both sides.
        res = self._base_validation_result()
        central = 1000.0
        ci_lower, ci_upper = 900.0, 1050.0
        amplitude_pct = abs(ci_upper - ci_lower) / central * 100

        res = NBRValidator.finalize_precision_and_extrapolation(
            res, amplitude_pct=amplitude_pct,
            extrapolation_details=[
                {"variable": "x", "avaliando_value": 10, "sample_min": 0, "sample_max": 19}
            ],
            degree=1,
            ci_lower=ci_lower, ci_upper=ci_upper, central_estimate=central,
        )

        campo_inf = central * (1 - config.CAMPO_ARBITRIO)
        campo_sup = central * (1 + config.CAMPO_ARBITRIO)
        assert campo_inf == pytest.approx(850.0)
        assert campo_sup == pytest.approx(1150.0)

        assert res.valores_admissiveis_inferior == pytest.approx(ci_lower)
        assert res.valores_admissiveis_superior == pytest.approx(ci_upper)
        # Sanity: the IC bounds are indeed strictly inside the (wider)
        # campo de arbítrio bounds in this scenario.
        assert campo_inf < ci_lower < ci_upper < campo_sup

    def test_asymmetric_intersection_ic80_wins_below_campo_wins_above(self):
        # Neither interval is wholly inside the other here: IC de 80% is
        # narrower on the lower side, campo de arbítrio is narrower on the
        # upper side. A correct interseção (per-side max/min, not "pick the
        # narrower interval wholesale") must take IC's lower bound and
        # campo's upper bound. central=1000 -> campo = [850, 1150];
        # ci = [900, 1300] -> expected valores_admissiveis = [900, 1150].
        res = self._base_validation_result()
        central = 1000.0
        ci_lower, ci_upper = 900.0, 1300.0
        amplitude_pct = abs(ci_upper - ci_lower) / central * 100

        res = NBRValidator.finalize_precision_and_extrapolation(
            res, amplitude_pct=amplitude_pct,
            extrapolation_details=[
                {"variable": "x", "avaliando_value": 10, "sample_min": 0, "sample_max": 19}
            ],
            degree=1,
            ci_lower=ci_lower, ci_upper=ci_upper, central_estimate=central,
        )

        campo_inf = central * (1 - config.CAMPO_ARBITRIO)
        campo_sup = central * (1 + config.CAMPO_ARBITRIO)
        assert campo_inf == pytest.approx(850.0)
        assert campo_sup == pytest.approx(1150.0)

        assert res.valores_admissiveis_inferior == pytest.approx(ci_lower)
        assert res.valores_admissiveis_superior == pytest.approx(campo_sup)


class TestOptimalCombinationTargetAchieved:
    def _make_strong_dataset(self, n=30, seed=1):
        rng = np.random.RandomState(seed)
        area = np.linspace(50, 200, n)
        noise = rng.normal(0, 50, n)
        preco = 1000 * area + 20000 + noise
        df = pd.DataFrame({'area': area, 'preco': preco})
        return df

    def test_target_achieved_true_when_reachable(self):
        from modules.optimal_combination import OptimalCombinationFinder

        df = self._make_strong_dataset()
        finder = OptimalCombinationFinder()
        result = finder.find_best_model(
            df, target_col='preco', degree=1,
            avaliando_raw={'area': 120.0},
        )

        assert result.success is True
        assert result.best_model is not None
        final_grau = result.best_model.validation_result.grau_fundamentacao
        assert result.best_grau_reached == final_grau
        assert final_grau is not None
        assert final_grau >= 1
        assert result.target_achieved is True

    def test_target_achieved_false_when_unreachable(self):
        from modules.optimal_combination import OptimalCombinationFinder

        df = self._make_strong_dataset()
        finder = OptimalCombinationFinder()
        # Grau III requires items 1 and 3 (externally informed) to be >= 2,
        # but find_best_model defaults grau_item1=grau_item3=1, so Grau III
        # is structurally unreachable regardless of data quality.
        result = finder.find_best_model(
            df, target_col='preco', degree=3,
            avaliando_raw={'area': 120.0},
        )

        assert result.success is True
        assert result.best_model is not None
        final_grau = result.best_model.validation_result.grau_fundamentacao
        assert result.best_grau_reached == final_grau
        assert final_grau is None or final_grau < 3
        assert result.target_achieved is False

    def test_target_achieved_false_and_best_grau_none_without_avaliando(self):
        """Without avaliando_raw, item 4 stays provisionally 0 and no grau
        can ever be classified (documented conservative behavior) - so
        best_grau_reached must reflect that (None), not a stale/optimistic
        value."""
        from modules.optimal_combination import OptimalCombinationFinder

        df = self._make_strong_dataset()
        finder = OptimalCombinationFinder()
        result = finder.find_best_model(df, target_col='preco', degree=1)

        assert result.success is True
        assert result.target_achieved is False
        assert result.best_grau_reached is None
