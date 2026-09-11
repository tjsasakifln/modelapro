import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from scipy import stats
from .results import TransformationResult
from .logging_manager import logger

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
    
    @staticmethod
    def apply_transformation(series: pd.Series, trans_type: str) -> Tuple[pd.Series, bool]:
        """
        Applies a specific transformation to a series.
        Returns the transformed series and a success flag.
        """
        try:
            func = Transformer.TRANSFORMATIONS.get(trans_type)
            if not func:
                return series, False
            
            # Check domain constraints
            if trans_type in ['ln', 'sqrt', 'inv_sqrt'] and (series <= 0).any():
                return series, False
            if trans_type in ['inverse', 'inv_sqr'] and (series == 0).any():
                return series, False
                
            transformed = func(series)
            
            # Check for infs or nans
            if np.isinf(transformed).any() or np.isnan(transformed).any():
                return series, False
                
            return transformed, True
        except Exception:
            return series, False

    @staticmethod
    def test_transformations(series: pd.Series, variable_name: str) -> List[TransformationResult]:
        """
        Tests all available transformations and returns results sorted by normality score.
        """
        results = []
        
        # Calculate initial normality (Shapiro-Wilk)
        # Note: Shapiro-Wilk is sensitive to sample size, for N > 5000 use Anderson-Darling or Kolmogorov-Smirnov
        # But NBR 14653 usually deals with smaller samples.
        try:
            stat, p_value_before = stats.shapiro(series)
        except:
            p_value_before = 0.0
            
        for name, _ in Transformer.TRANSFORMATIONS.items():
            transformed, success = Transformer.apply_transformation(series, name)
            
            if success:
                try:
                    stat, p_value_after = stats.shapiro(transformed)
                except:
                    p_value_after = 0.0
                
                results.append(TransformationResult(
                    success=True,
                    variable=variable_name,
                    transformation_type=name,
                    normality_score_before=p_value_before,
                    normality_score_after=p_value_after,
                    transformed_values=transformed.tolist()
                ))
        
        # Sort by normality score (p-value) descending
        results.sort(key=lambda x: x.normality_score_after, reverse=True)
        return results
