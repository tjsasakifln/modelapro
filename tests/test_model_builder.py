import pytest
import pandas as pd
import numpy as np
from modules.model_builder import ModelBuilder, fit_candidate, evaluate_fitted

class TestModelBuilder:
    def test_simple_linear_regression(self):
        # y = 2x + 1
        X = pd.DataFrame({'x': range(20)})
        y = 2 * X['x'] + 1
        
        builder = ModelBuilder()
        result = builder.build_model(X, y, degree=1)
        
        assert result.success is True
        assert result.model_metrics.r2 == 1.0
        assert np.isclose(result.coefficients['x'], 2.0)
        assert np.isclose(result.coefficients['const'], 1.0)
        
    def test_validation_integration(self):
        # Low-R2 model that is nonetheless F-significant, with all p-values,
        # VIF and normality within NBR 14653-2 limits for Degree 2.
        np.random.seed(42)
        X = pd.DataFrame({'x': np.random.rand(20)})
        y = pd.Series(np.random.rand(20))

        builder = ModelBuilder()
        result = builder.build_model(X, y, degree=2)

        assert result.success is True
        # R2 has no normative basis as a blocking criterion (Anexo A.4): a low
        # R2 must not appear as a rejection message, only as a warning. Not
        # asserting is_valid here - its verdict now depends on
        # grau_fundamentacao/target_degree, computed by a later step.
        assert not any("R²" in m for m in result.validation_result.messages)
        assert any("R²" in w for w in result.validation_result.warnings)

    def test_legacy_remove_outliers_flag_keeps_sample(self):
        np.random.seed(0)
        X = pd.DataFrame({'x': np.linspace(1, 10, 25)})
        y = 2 * X['x'] + 1 + np.random.normal(0, 0.1, 25)
        y.iloc[-1] = 80.0
        builder = ModelBuilder()
        result = builder.build_model(X, y, remove_outliers=True)
        assert result.success is True
        assert result.outliers_removed == []
        assert len(result.residuals) == len(X)

    def test_public_mp1_exports_exist(self):
        assert callable(fit_candidate)
        assert callable(evaluate_fitted)

