import pandas as pd
import numpy as np
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.stattools import durbin_watson
from statsmodels.stats.diagnostic import het_breuschpagan
from scipy import stats
from typing import List, Dict, Optional, Tuple
from .results import ModelResult, ModelMetrics, ValidationResult
from .logging_manager import logger
from .nbr14653_validation import NBRValidator
from .config_manager import config
from .transformations import Transformer

class ModelBuilder:
    def __init__(self):
        pass


    def _calculate_metrics(self, model, X, y) -> ModelMetrics:
        # Normality test (Shapiro-Wilk)
        try:
            _, normality_p = stats.shapiro(model.resid)
        except:
            normality_p = 0.0
            
        # Homoscedasticity (Breusch-Pagan)
        try:
            _, homoscedasticity_p, _, _ = het_breuschpagan(model.resid, X)
        except:
            homoscedasticity_p = 0.0
            
        # Durbin-Watson
        dw = durbin_watson(model.resid)
        
        return ModelMetrics(
            r2=model.rsquared,
            r2_adjusted=model.rsquared_adj,
            f_statistic=model.fvalue,
            f_pvalue=model.f_pvalue,
            std_error=np.sqrt(model.mse_resid),
            aic=model.aic,
            bic=model.bic,
            condition_number=model.condition_number,
            normality_pvalue=normality_p,
            homoscedasticity_pvalue=homoscedasticity_p,
            autocorrelation_durbin_watson=dw
        )
        
    def _get_formula(self, model) -> str:
        # Construct a string representation of the formula
        try:
            params = model.params
            formula = f"y = {params['const']:.4f}"
            for col in params.index:
                if col != 'const':
                    sign = "+" if params[col] >= 0 else "-"
                    formula += f" {sign} {abs(params[col]):.4f}*{col}"
            return formula
        except:
            return "Formula generation failed"

    def detect_outliers(self, model) -> List[int]:
        """
        Identifies outliers using Cook's Distance and Standardized Residuals.
        Returns a list of indices (from the original data) to be removed.
        """
        outliers = set()
        
        try:
            # Cook's Distance
            influence = model.get_influence()
            cooks_d, _ = influence.cooks_distance
            
            # Threshold for Cook's D: usually > 1 or > 4/n
            # We use config or default 1.0 for robustness, but 4/n is more sensitive
            n = len(model.resid)
            cooks_threshold = config.MAX_COOK_DISTANCE if hasattr(config, 'MAX_COOK_DISTANCE') else 1.0
            
            # Standardized Residuals
            # Threshold > 2 or 3
            std_resid = influence.resid_studentized_internal
            resid_threshold = 2.5 # Strictness
            
            for i in range(n):
                if cooks_d[i] > cooks_threshold:
                    outliers.add(model.resid.index[i])
                elif abs(std_resid[i]) > resid_threshold:
                    outliers.add(model.resid.index[i])
                    
            return list(outliers)
            
        except Exception as e:
            logger.error(f"Error detecting outliers: {str(e)}")
            return []

    def build_model(self, X: pd.DataFrame, y: pd.Series, degree: int = 1, remove_outliers: bool = True,
                     grau_item1: int = 1, grau_item3: int = 1) -> ModelResult:
        """
        Fits a OLS regression model and returns detailed results.
        Optionally removes outliers and refits.
        """
        try:
            # Add constant
            X_with_const = sm.add_constant(X)
            
            # Fit initial model
            model = sm.OLS(y, X_with_const).fit()

            outliers_removed: List = []
            if remove_outliers:
                outlier_indices = self.detect_outliers(model)
                if outlier_indices:
                    # Filter data
                    clean_indices = [idx for idx in X.index if idx not in outlier_indices]
                    if len(clean_indices) > len(X) * 0.5: # Safety check: don't remove more than 50%
                        X_clean = X_with_const.loc[clean_indices]
                        y_clean = y.loc[clean_indices]
                        # Refit
                        model = sm.OLS(y_clean, X_clean).fit()
                        X_with_const = X_clean # Update for metrics calculation
                        y = y_clean
                        # Track which rows (by original index) were actually
                        # excluded from the refit, so downstream steps (e.g.
                        # item 4 / extrapolação) can restrict "dados de
                        # mercado efetivamente utilizados" to the same
                        # post-outlier-removal sample used for n (item 2).
                        outliers_removed = [idx for idx in X.index if idx not in clean_indices]
            
            # Calculate metrics
            metrics = self._calculate_metrics(model, X_with_const, y)
            
            # Calculate VIF
            vif = {}
            for i, col in enumerate(X_with_const.columns):
                try:
                    vif[col] = variance_inflation_factor(X_with_const.values, i)
                except:
                    vif[col] = float('inf')
            
            # Create ModelResult
            result = ModelResult(
                success=True,
                model_metrics=metrics,
                coefficients=model.params.to_dict(),
                pvalues=model.pvalues.to_dict(),
                vif=vif,
                residuals=model.resid.tolist(),
                fitted_values=model.fittedvalues.tolist(),
                formula=self._get_formula(model),
                outliers_removed=outliers_removed,
                model_object=model
            )
            
            # Validate
            result.validation_result = NBRValidator.validate_model(
                result, X_with_const, y, degree, grau_item1=grau_item1, grau_item3=grau_item3
            )

            return result

        except Exception as e:
            logger.error(f"Error building model: {str(e)}")
            return ModelResult(success=False, message=f"Error building model: {str(e)}", error=str(e))

    def add_precision_and_extrapolation(self, model_result: ModelResult, avaliando_raw: Dict[str, float],
                                         original_df: pd.DataFrame, degree: Optional[int] = None) -> ModelResult:
        """
        Completes the model's NBR 14653-2 validation with the avaliando's
        characteristics: computes the 80% confidence interval amplitude
        (grau de precisão, Tabela 5) and checks extrapolation (item 4,
        Tabela 1) for each base variable used in the model.

        avaliando_raw: {base_variable_name: value}, e.g. {"area": 120, "quartos": 3}
        (keys are variable names BEFORE any mathematical transformation).
        """
        try:
            if not model_result.validation_result:
                logger.error("add_precision_and_extrapolation: model_result has no validation_result.")
                return model_result

            if degree is None:
                degree = model_result.validation_result.target_degree
                if degree is None:
                    degree = 1

            columns = [col for col in model_result.coefficients.keys() if col != 'const']

            # Item 4 (extrapolação, 9.2.1) must use the same "dados de
            # mercado efetivamente utilizados" as item 2 (n): the sample
            # AFTER outlier removal performed in build_model(), not the raw
            # original_df. Otherwise outliers (typically extreme values)
            # would artificially widen [sample_min, sample_max] and the
            # extended interval [0.5*min, 2*max], making item 4 more
            # permissive than the model actually fitted supports.
            effective_df = original_df
            if model_result.outliers_removed:
                matched_outliers = [idx for idx in model_result.outliers_removed if idx in original_df.index]
                if not matched_outliers:
                    logger.warning(
                        "add_precision_and_extrapolation: model_result.outliers_removed is "
                        "non-empty but none of its indices are present in original_df. "
                        "sample_min/sample_max will silently fall back to the full "
                        "original_df, which may re-introduce outliers into item 4's "
                        "extrapolation range. This usually means original_df's index does "
                        "not align with the index used in build_model()."
                    )
                effective_df = original_df.drop(index=matched_outliers)

            row_values = {'const': 1.0}
            extrapolation_details = []
            seen_bases = set()

            for col in columns:
                # Determine base variable name and transformation function
                if '(' in col and col.endswith(')'):
                    func_name = col[:col.index('(')]
                    base = col[col.index('(') + 1: -1]
                else:
                    func_name = 'linear'
                    base = col

                if base not in avaliando_raw:
                    raise KeyError(f"Valor do avaliando não informado para a variável base '{base}' (coluna '{col}').")

                raw_value = avaliando_raw[base]

                transformed_series, ok = Transformer.apply_transformation(
                    pd.Series([raw_value]), func_name
                )
                if not ok:
                    raise ValueError(f"Falha ao aplicar transformação '{func_name}' ao valor do avaliando para '{base}'.")

                row_values[col] = transformed_series.iloc[0]

                if base not in seen_bases:
                    seen_bases.add(base)
                    if base not in original_df.columns:
                        raise KeyError(f"Variável base '{base}' não encontrada no DataFrame original.")
                    extrapolation_details.append({
                        "variable": base,
                        "avaliando_value": raw_value,
                        "sample_min": float(effective_df[base].min()),
                        "sample_max": float(effective_df[base].max()),
                    })

            # Assemble the 1-row DataFrame in the same column order as X_with_const
            ordered_columns = list(model_result.coefficients.keys())
            avaliando_df = pd.DataFrame([row_values], columns=ordered_columns)

            prediction = model_result.model_object.get_prediction(avaliando_df)
            summary = prediction.summary_frame(alpha=1 - config.CONFIDENCE_LEVEL_PRECISION)

            mean = summary['mean'].iloc[0]
            ci_lower = summary['mean_ci_lower'].iloc[0]
            ci_upper = summary['mean_ci_upper'].iloc[0]

            amplitude_pct = abs(ci_upper - ci_lower) / abs(mean) * 100 if mean != 0 else float('inf')

            model_result.validation_result = NBRValidator.finalize_precision_and_extrapolation(
                model_result.validation_result, amplitude_pct, extrapolation_details, degree,
                ci_lower=ci_lower, ci_upper=ci_upper, central_estimate=mean
            )

            return model_result

        except Exception as e:
            # Kept broad deliberately: this runs once per candidate during
            # the search (see OptimalCombinationFinder.find_best_model) and
            # must not abort the whole search over one candidate's failure
            # here. The now-expected failure modes (a base variable missing
            # from avaliando_raw, or a transformation domain-invalid for
            # the avaliando's specific value) are pre-filtered before the
            # search reaches this point - see
            # OptimalCombinationFinder._build_variable_options - so
            # anything still landing here is unexpected (e.g. a
            # get_prediction() failure). logger.exception captures the
            # traceback, and the warning is also surfaced on the result
            # itself so the failure is visible in the websocket payload and
            # PDF report instead of being inferable only from item 4 == 0.
            logger.exception(f"Error in add_precision_and_extrapolation: {str(e)}")
            if model_result.validation_result:
                model_result.validation_result.warnings.append(
                    f"Não foi possível calcular grau de precisão / item 4 (extrapolação) "
                    f"para este candidato: {type(e).__name__}: {str(e)}"
                )
            return model_result
