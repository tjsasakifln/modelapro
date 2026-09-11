import pytest
import pandas as pd
import numpy as np
from modules.transformations import Transformer

class TestTransformations:
    def test_linear(self):
        s = pd.Series([1, 2, 3])
        res, success = Transformer.apply_transformation(s, 'linear')
        assert success is True
        assert res.equals(s)
        
    def test_ln_valid(self):
        s = pd.Series([1, np.e, np.e**2])
        res, success = Transformer.apply_transformation(s, 'ln')
        assert success is True
        assert np.allclose(res, [0, 1, 2])
        
    def test_ln_invalid(self):
        s = pd.Series([1, -1, 0])
        res, success = Transformer.apply_transformation(s, 'ln')
        assert success is False
        
    def test_inverse_zero(self):
        s = pd.Series([1, 0, 2])
        res, success = Transformer.apply_transformation(s, 'inverse')
        assert success is False

    def test_sqrt_accepts_zero_and_returns_literal_oracles(self):
        s = pd.Series([0, 1, 4], dtype=float)
        res, success = Transformer.apply_transformation(s, "sqrt")
        assert success is True
        np.testing.assert_allclose(res.to_numpy(dtype=float), [0.0, 1.0, 2.0])

    def test_sqrt_rejects_negative(self):
        s = pd.Series([-1.0])
        result = Transformer.apply_transformation(s, "sqrt")
        _, success = result
        assert success is False
        assert getattr(result, "failure_code", None) == "domain_negative"

    def test_unknown_transform_name_fails(self):
        s = pd.Series([1.0, 2.0])
        result = Transformer.apply_transformation(s, "not_a_transform")
        _, success = result
        assert success is False
        assert getattr(result, "failure_code", None) == "unknown_name"
