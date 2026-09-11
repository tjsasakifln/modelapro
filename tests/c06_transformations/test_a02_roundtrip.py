"""C06-A02: identity/log round-trip on the real target-transform API."""
import numpy as np
import pandas as pd
import pytest

from modules.target_transform import (
    fit_target_transform,
    inverse_target_prediction,
    transform_target,
)


class TestIdentityRoundTrip:
    def test_identity_round_trip_matches_input(self):
        y = np.array([10.0, 0.0, -3.5, 250000.0])
        state = fit_target_transform(y, "identity")
        z = transform_target(y, state)
        inv = inverse_target_prediction(z, state)
        np.testing.assert_allclose(np.asarray(inv["point"], dtype=float), y, rtol=0.0, atol=0.0)
        np.testing.assert_allclose(np.asarray(z, dtype=float), y, rtol=0.0, atol=0.0)

    def test_identity_inverse_equals_prediction(self):
        y = np.array([1.0, 2.0, 3.0])
        state = fit_target_transform(y, "identity")
        pred = np.array([9.5, -1.0, 0.0])
        inv = inverse_target_prediction(pred, state)
        np.testing.assert_allclose(np.asarray(inv["point"], dtype=float), pred)


class TestLogRoundTrip:
    def test_log_round_trip_on_positive_values(self):
        y = np.array([0.5, 1.0, np.e, 100.0])
        state = fit_target_transform(y, "log")
        z = transform_target(y, state)
        inv = inverse_target_prediction(z, state)
        np.testing.assert_allclose(np.asarray(inv["point"], dtype=float), y, rtol=1e-12, atol=0.0)

    def test_log_rejects_non_positive_train(self):
        with pytest.raises(ValueError):
            fit_target_transform(np.array([1.0, 0.0]), "log")
        with pytest.raises(ValueError):
            fit_target_transform(np.array([1.0, -2.0]), "log")


class TestInvalidNamesAndTypes:
    def test_unknown_name_raises(self):
        y = np.array([1.0, 2.0, 3.0])
        with pytest.raises(ValueError):
            fit_target_transform(y, "boxcox")
        with pytest.raises(ValueError):
            fit_target_transform(y, "ln")
        with pytest.raises(ValueError):
            fit_target_transform(y, "sqrt")

    def test_invalid_name_type_raises(self):
        y = np.array([1.0, 2.0, 3.0])
        with pytest.raises(TypeError):
            fit_target_transform(y, 1)
        with pytest.raises(TypeError):
            fit_target_transform(y, None)

    def test_invalid_y_type_raises(self):
        with pytest.raises(TypeError):
            fit_target_transform("not-an-array", "identity")

    def test_unknown_state_name_does_not_silently_become_identity(self):
        y = np.array([1.0, 2.0, 3.0])
        state = fit_target_transform(y, "identity")
        bad = dict(state)
        bad["name"] = "not-a-real-transform"
        with pytest.raises(ValueError):
            transform_target(y, bad)
        with pytest.raises(ValueError):
            inverse_target_prediction(y, bad)

    def test_series_input_round_trip(self):
        y = pd.Series([10.0, 20.0, 40.0], index=["a", "b", "c"])
        state = fit_target_transform(y, "log")
        z = transform_target(y, state)
        inv = inverse_target_prediction(z, state)
        np.testing.assert_allclose(np.asarray(inv["point"], dtype=float), y.to_numpy(dtype=float), rtol=1e-12)
