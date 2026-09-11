"""C06-A01: X-transform domains on the real Transformer.apply_transformation."""
import math

import numpy as np
import pandas as pd
import pytest

from modules.transformations import Transformer


def _apply(values, name):
    series = pd.Series(values, dtype=float)
    return Transformer.apply_transformation(series, name)


class TestSqrtDomain:
    def test_sqrt_of_zero_one_four_succeeds_with_literal_oracles(self):
        result = _apply([0.0, 1.0, 4.0], "sqrt")
        transformed, success = result
        assert success is True
        assert result.failure_code is None
        np.testing.assert_allclose(transformed.to_numpy(dtype=float), [0.0, 1.0, 2.0])

    def test_sqrt_rejects_negative_with_negative_meaning(self):
        result = _apply([-1.0], "sqrt")
        transformed, success = result
        assert success is False
        assert result.failure_code == "domain_negative"
        # Failure payload is not a successful transform (original series, not NaN-as-success).
        np.testing.assert_allclose(transformed.to_numpy(dtype=float), [-1.0])


class TestLnAndInvSqrtRequirePositive:
    def test_ln_of_zero_fails_with_zero_meaning(self):
        result = _apply([0.0], "ln")
        _, success = result
        assert success is False
        assert result.failure_code == "domain_zero"

    def test_ln_of_negative_fails_with_negative_meaning(self):
        result = _apply([-1.0], "ln")
        _, success = result
        assert success is False
        assert result.failure_code == "domain_negative"

    def test_ln_of_strictly_positive_succeeds(self):
        result = _apply([1.0, math.e, math.e ** 2], "ln")
        transformed, success = result
        assert success is True
        np.testing.assert_allclose(transformed.to_numpy(dtype=float), [0.0, 1.0, 2.0])

    def test_inv_sqrt_of_zero_fails_with_zero_meaning(self):
        result = _apply([0.0], "inv_sqrt")
        _, success = result
        assert success is False
        assert result.failure_code == "domain_zero"

    def test_inv_sqrt_of_positive_succeeds(self):
        result = _apply([1.0, 4.0], "inv_sqrt")
        transformed, success = result
        assert success is True
        np.testing.assert_allclose(transformed.to_numpy(dtype=float), [1.0, 0.5])


class TestInverseAndInvSqrRequireNonzero:
    def test_inverse_of_zero_fails_with_zero_meaning(self):
        result = _apply([0.0], "inverse")
        _, success = result
        assert success is False
        assert result.failure_code == "domain_zero"

    def test_inverse_of_nonzero_including_negative_succeeds(self):
        result = _apply([1.0, -2.0, 4.0], "inverse")
        transformed, success = result
        assert success is True
        np.testing.assert_allclose(transformed.to_numpy(dtype=float), [1.0, -0.5, 0.25])

    def test_inv_sqr_of_zero_fails_with_zero_meaning(self):
        result = _apply([0.0], "inv_sqr")
        _, success = result
        assert success is False
        assert result.failure_code == "domain_zero"

    def test_inv_sqr_of_nonzero_including_negative_succeeds(self):
        result = _apply([-2.0, 2.0], "inv_sqr")
        transformed, success = result
        assert success is True
        np.testing.assert_allclose(transformed.to_numpy(dtype=float), [0.25, 0.25])


class TestNonfiniteAndUnknown:
    def test_nan_input_fails_explicitly(self):
        result = _apply([1.0, float("nan")], "linear")
        _, success = result
        assert success is False
        assert result.failure_code == "nonfinite_input"

    def test_inf_input_fails_explicitly(self):
        result = _apply([1.0, float("inf")], "linear")
        _, success = result
        assert success is False
        assert result.failure_code == "nonfinite_input"

    def test_overflow_output_is_not_a_successful_transform(self):
        tiny = np.finfo(float).tiny
        result = _apply([tiny], "inv_sqr")
        transformed, success = result
        assert success is False
        assert result.failure_code in {"overflow", "nonfinite_output"}
        out = np.asarray(transformed, dtype=float)
        # Either original series or a failed payload — never success with inf.
        assert not np.isfinite(out).all() or np.allclose(out, [tiny])

    def test_unknown_name_fails_and_does_not_pass_silently(self):
        series = pd.Series([1.0, 2.0])
        result = Transformer.apply_transformation(series, "boxcox")
        transformed, success = result
        assert success is False
        assert result.failure_code == "unknown_name"
        np.testing.assert_allclose(transformed.to_numpy(dtype=float), [1.0, 2.0])

    def test_two_tuple_unpack_compatibility(self):
        transformed, success = Transformer.apply_transformation(
            pd.Series([0.0, 1.0, 4.0]), "sqrt"
        )
        assert success is True
        assert isinstance(transformed, pd.Series)


class TestLegacyNonRegression:
    def test_linear_unchanged(self):
        s = pd.Series([1.0, -3.0, 0.0, 8.0])
        transformed, success = Transformer.apply_transformation(s, "linear")
        assert success is True
        np.testing.assert_allclose(transformed.to_numpy(dtype=float), s.to_numpy(dtype=float))

    def test_sqr_of_reals_succeeds(self):
        result = _apply([-2.0, 0.0, 3.0], "sqr")
        transformed, success = result
        assert success is True
        np.testing.assert_allclose(transformed.to_numpy(dtype=float), [4.0, 0.0, 9.0])
