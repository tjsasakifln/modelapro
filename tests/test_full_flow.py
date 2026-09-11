import pytest
import pandas as pd
import numpy as np
from modules.data_loader import DataLoader
from modules.optimal_combination import OptimalCombinationFinder

class TestFullFlow:
    def test_end_to_end_logic(self):
        # 1. Create synthetic data
        np.random.seed(42)
        n = 30
        x1 = np.linspace(1, 10, n)
        x2 = np.random.rand(n)
        # y = 3*x1 + noise
        y = 3 * x1 + np.random.normal(0, 0.5, n)
        
        df = pd.DataFrame({'x1': x1, 'x2': x2, 'y': y})
        
        # 2. Find Optimal Model
        # avaliando_raw must be supplied so item 4 (extrapolação) and the
        # grau de precisão get finalized for the winning model - without it,
        # item 4 stays provisionally 0 (conservative) and no grau de
        # fundamentação can ever be classified, by design.
        finder = OptimalCombinationFinder()
        avaliando_raw = {'x1': float(np.median(x1)), 'x2': float(np.median(x2))}
        result = finder.find_best_model(df, 'y', degree=1, avaliando_raw=avaliando_raw)

        assert result.success is True
        assert result.best_model is not None

        # Should pick x1
        params = result.best_model.coefficients
        assert 'x1' in params
        assert np.isclose(params['x1'], 3.0, atol=0.5)

        # Should likely exclude x2 or have it insignificant
        # (Stepwise logic in MVP is simple combination, so it might pick x1+x2 if R2 adj increases slightly)
        # But x1 should be the dominant factor.

        # 3. Validation
        val = result.best_model.validation_result
        assert val.is_valid is True # Should pass for Degree 1
        assert result.target_achieved is True
        assert result.best_grau_reached == val.grau_fundamentacao


class TestDataLoaderToOptimalCombinationWithCandidateCols:
    """
    Light integration test: DataLoader.load_data's output DataFrame feeds
    directly into OptimalCombinationFinder.find_best_model with an explicit
    candidate_cols restriction, confirming the two modules fit together
    without error and that the restriction is honored end-to-end (not just
    unit-tested against a hand-built DataFrame).
    """

    def test_pipeline_with_candidate_cols_restriction(self):
        np.random.seed(7)
        n = 30
        area = np.linspace(50, 200, n)
        quartos = np.random.randint(1, 5, n)
        # 'bairro' is a real market variable not selected as a candidate.
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
        # 'bairro' one-hot-encodes fine (3 uniques), so nothing should be
        # excluded here - this integration test focuses on candidate_cols,
        # not on the exclusion path (covered separately in
        # test_data_loader.py).
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
