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
