from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from modules.data_loader import DataLoader
from modules.optimal_combination import OptimalCombinationFinder

INDEPENDENT = Path(__file__).resolve().parent / "fixtures" / "independent"


class TestFullFlow:
    def test_end_to_end_logic(self):
        np.random.seed(42)
        n = 30
        x1 = np.linspace(1, 10, n)
        x2 = np.random.rand(n)
        y = 3 * x1 + np.random.normal(0, 0.5, n)

        df = pd.DataFrame({'x1': x1, 'x2': x2, 'y': y})

        finder = OptimalCombinationFinder()
        avaliando_raw = {'x1': float(np.median(x1)), 'x2': float(np.median(x2))}
        result = finder.find_best_model(df, 'y', degree=1, avaliando_raw=avaliando_raw)

        assert result.success is True
        assert result.best_model is not None

        params = result.best_model.coefficients
        assert 'x1' in params
        assert np.isclose(params['x1'], 3.0, atol=0.5)

        val = result.best_model.validation_result
        assert val.is_valid is True
        assert result.target_achieved is True
        assert result.best_grau_reached == val.grau_fundamentacao


class TestDataLoaderToOptimalCombinationWithCandidateCols:
    def test_pipeline_with_candidate_cols_restriction(self):
        np.random.seed(7)
        n = 30
        area = np.linspace(50, 200, n)
        quartos = np.random.randint(1, 5, n)
        bairro = np.random.choice(['Centro', 'Norte', 'Sul'], n)
        preco = 1000 * area + 5000 * quartos + 20000 + np.random.normal(0, 200, n)

        df = pd.DataFrame({
            'area': area, 'quartos': quartos, 'bairro': bairro, 'preco': preco,
        })
        csv_content = df.to_csv(index=False).encode('utf-8')

        loader = DataLoader()
        load_result = loader.load_data(csv_content, 'test.csv')

        assert load_result.success is True
        assert load_result.error is None
        assert not load_result.excluded_columns

        finder = OptimalCombinationFinder()
        result = finder.find_best_model(
            load_result.dataframe, 'preco', degree=1, candidate_cols=['area', 'quartos'],
        )

        assert result.success is True
        assert result.best_model is not None
        assert result.best_model.success is True

        for entry in result.history:
            base_names = {
                OptimalCombinationFinder._base_name(col) for col in entry['variables']
            }
            assert base_names <= {'area', 'quartos'}

        winning_bases = {
            OptimalCombinationFinder._base_name(c)
            for c in result.best_model.coefficients
            if c != 'const'
        }
        assert winning_bases <= {'area', 'quartos'}
        assert not any(b.startswith('bairro') for b in winning_bases)

    def test_empty_candidate_cols_is_explicit_error_not_all_columns(self):
        """F16 / C16-A02: candidate_cols=[] authorizes no predictors."""
        csv_content = (INDEPENDENT / "f16_empty_selection.csv").read_bytes()
        loader = DataLoader()
        load_result = loader.load_data(csv_content, "f16_empty_selection.csv")
        assert load_result.success is True

        finder = OptimalCombinationFinder()
        result = finder.find_best_model(
            load_result.dataframe, "preco", degree=1, candidate_cols=[],
        )
        assert result.success is False
        blob = (result.message or "") + " " + (result.error or "")
        assert result.best_model is None
        assert "nenhuma" in blob.lower() or "no_independent" in blob.lower() or "vazia" in blob.lower()

    def test_missing_target_observed_n_is_exactly_the_raw_non_null_count(self):
        """F01 / C16-A02: observed-target n is counted from the file, not after mean fill."""
        path = INDEPENDENT / "f01_missing_target.csv"
        raw = pd.read_csv(path)
        n_observed = int(raw["preco"].notna().sum())
        assert n_observed == 25

        loader = DataLoader()
        load_result = loader.load_data(path.read_bytes(), "f01_missing_target.csv")
        assert load_result.success is True
        loaded = load_result.dataframe
        assert loaded is not None
        observed_in_model = int(loaded["preco"].notna().sum())
        assert observed_in_model == n_observed
        assert len(loaded) == n_observed
