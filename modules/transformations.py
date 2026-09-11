import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from scipy import stats
from .results import TransformationResult


class TransformationApplyResult(tuple):
    """Legacy two-tuple ``(series, success)`` plus an explicit failure meaning.

    Existing callers that unpack two values keep working. ``failure_code`` is
    set only when ``success`` is False so domain/overflow failures are not
    silent.
    """

    def __new__(cls, series, success, failure_code=None):
        success = bool(success)
        obj = super().__new__(cls, (series, success))
        obj.series = series
        obj.success = success
        obj.failure_code = None if success else failure_code
        return obj


class Transformer:
    TRANSFORMATIONS = {
        'linear': lambda x: x,
        'inverse': lambda x: 1/x,
        'ln': lambda x: np.log(x),
        'sqr': lambda x: x**2,
        'sqrt': lambda x: np.sqrt(x),
        'inv_sqr': lambda x: 1/(x**2),
        'inv_sqrt': lambda x: 1/np.sqrt(x)
    }

    # Domain: sqrt accepts 0 and rejects negatives; ln/inv_sqrt require
    # strictly positive values; inverse/inv_sqr require nonzero.
    STRICTLY_POSITIVE = frozenset({"ln", "inv_sqrt"})
    NON_NEGATIVE = frozenset({"sqrt"})
    NONZERO = frozenset({"inverse", "inv_sqr"})

    TRANSFORM_DOMAINS = {
        "linear": {
            "requires_finite": True,
            "requires_positive": False,
            "includes_zero": True,
            "includes_negative": True,
        },
        "sqr": {
            "requires_finite": True,
            "requires_positive": False,
            "includes_zero": True,
            "includes_negative": True,
        },
        "sqrt": {
            "requires_finite": True,
            "requires_positive": False,
            "includes_zero": True,
            "includes_negative": False,
        },
        "ln": {
            "requires_finite": True,
            "requires_positive": True,
            "includes_zero": False,
            "includes_negative": False,
        },
        "inv_sqrt": {
            "requires_finite": True,
            "requires_positive": True,
            "includes_zero": False,
            "includes_negative": False,
        },
        "inverse": {
            "requires_finite": True,
            "requires_positive": False,
            "includes_zero": False,
            "includes_negative": True,
        },
        "inv_sqr": {
            "requires_finite": True,
            "requires_positive": False,
            "includes_zero": False,
            "includes_negative": True,
        },
    }

    @classmethod
    def domain_for(cls, trans_type: str) -> Optional[Dict]:
        spec = cls.TRANSFORM_DOMAINS.get(trans_type)
        return None if spec is None else dict(spec)

    @staticmethod
    def apply_transformation(series: pd.Series, trans_type: str) -> Tuple[pd.Series, bool]:
        """
        Applies a specific transformation to a series.
        Returns the transformed series and a success flag.

        The return value unpacks as ``(series, bool)`` for C04/C05. On
        failure it also carries ``failure_code`` (zero vs negative vs
        unknown vs non-finite/overflow). Non-finite results are never a
        successful transform.
        """
        if trans_type not in Transformer.TRANSFORMATIONS:
            return TransformationApplyResult(series, False, "unknown_name")

        try:
            arr = np.asarray(series, dtype=float)
        except (TypeError, ValueError):
            return TransformationApplyResult(series, False, "nonfinite_input")

        if arr.size > 0 and not np.isfinite(arr).all():
            return TransformationApplyResult(series, False, "nonfinite_input")

        domain_code = Transformer._domain_failure(trans_type, arr)
        if domain_code is not None:
            return TransformationApplyResult(series, False, domain_code)

        func = Transformer.TRANSFORMATIONS[trans_type]
        try:
            with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
                transformed = func(series)
            transformed_arr = np.asarray(transformed, dtype=float)
        except (OverflowError, FloatingPointError, ValueError, ZeroDivisionError):
            return TransformationApplyResult(series, False, "overflow")

        if transformed_arr.size > 0 and not np.isfinite(transformed_arr).all():
            if np.isinf(transformed_arr).any():
                return TransformationApplyResult(series, False, "overflow")
            return TransformationApplyResult(series, False, "nonfinite_output")

        return TransformationApplyResult(transformed, True, None)

    @staticmethod
    def _domain_failure(trans_type: str, arr: np.ndarray) -> Optional[str]:
        if arr.size == 0:
            return None
        if trans_type in Transformer.STRICTLY_POSITIVE:
            if np.any(arr < 0):
                return "domain_negative"
            if np.any(arr == 0):
                return "domain_zero"
        elif trans_type in Transformer.NON_NEGATIVE:
            if np.any(arr < 0):
                return "domain_negative"
        elif trans_type in Transformer.NONZERO:
            if np.any(arr == 0):
                return "domain_zero"
        return None

    @staticmethod
    def test_transformations(series: pd.Series, variable_name: str) -> List[TransformationResult]:
        """
        Tests all available transformations and returns diagnostic results.

        Shapiro-Wilk p-values on the marginal X (or transformed X) are
        diagnostics only. They are not a regression-quality score and are
        not used to rank or select candidates.
        """
        results = []

        try:
            stat, p_value_before = stats.shapiro(series)
        except Exception:
            p_value_before = 0.0

        for name in Transformer.TRANSFORMATIONS:
            transformed, success = Transformer.apply_transformation(series, name)

            if success:
                try:
                    stat, p_value_after = stats.shapiro(transformed)
                except Exception:
                    p_value_after = 0.0

                results.append(TransformationResult(
                    success=True,
                    variable=variable_name,
                    transformation_type=name,
                    normality_score_before=p_value_before,
                    normality_score_after=p_value_after,
                    transformed_values=transformed.tolist()
                ))

        return results
