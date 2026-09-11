import pandas as pd
import numpy as np
from typing import List, Optional, Dict
import io
from .results import DataLoadResult, ValidationResult
from .utils import clean_column_name, safe_float_conversion
from .config_manager import config
from .logging_manager import logger

class DataLoader:
    def __init__(self):
        self.df = None
        self.original_df = None
        self.identification_df = None

    def load_data(self, file_content: bytes, filename: str) -> DataLoadResult:
        """
        Loads data from CSV or Excel file with robust handling.

        No column is ever dropped silently. The user must have total
        freedom to bring in whatever candidate variables they want/can from
        the market; this method only decides what is TECHNICALLY possible
        to turn into a usable numeric model variable (directly numeric, or
        categorical with up to config.MAX_ONE_HOT_CATEGORIES unique values
        and thus one-hot-encodable). Every column that fails that technical
        test (free text with too many unique values, or a column with zero
        usable values) is preserved - untransformed - in
        DataLoadResult.identification_df, recorded with its reason in
        DataLoadResult.excluded_columns, and surfaced as a warning in
        ValidationResult.warnings. Deciding which of the remaining,
        technically-modelable columns the user actually wants to use as
        candidates is a separate, later decision (not made here).
        """
        try:
            # 1. Read File with Encoding Detection
            if filename.endswith('.csv'):
                try:
                    self.original_df = pd.read_csv(io.BytesIO(file_content), encoding='utf-8')
                except UnicodeDecodeError:
                    try:
                        self.original_df = pd.read_csv(io.BytesIO(file_content), encoding='latin1')
                    except:
                        self.original_df = pd.read_csv(io.BytesIO(file_content), encoding='cp1252')
            elif filename.endswith(('.xls', '.xlsx')):
                self.original_df = pd.read_excel(io.BytesIO(file_content))
            else:
                return DataLoadResult(success=False, message="Unsupported file format")

            # Clean column names
            self.original_df.columns = [clean_column_name(col) for col in self.original_df.columns]

            # Basic cleaning
            self.df = self.original_df.copy()

            excluded_columns: Dict[str, str] = {}

            # 2. Convert Numeric Columns
            # Try to convert object columns to float, coercing errors to NaN.
            # A column is treated as numeric only if a clear majority
            # (>50%) of its values parse as numbers; otherwise it is left
            # as-is and handled as a categorical/text column below.
            for col in self.df.columns:
                # pandas 2.x/3.x may read text columns as the dedicated
                # StringDtype ("string"/"str") instead of legacy `object`
                # (confirmed with pandas 3.0 + pd.read_excel/read_csv here).
                # `dtype == 'object'` silently never matches those columns,
                # skipping numeric-string conversion (e.g. "R$ 1.234,56")
                # entirely - use is_string_dtype so this step is not
                # version-dependent.
                if pd.api.types.is_string_dtype(self.df[col]):
                    converted = self.df[col].apply(safe_float_conversion)
                    if converted.notna().sum() > 0.5 * len(self.df):
                        self.df[col] = converted

            # 3. Handle Categorical Variables (One-Hot Encoding)
            # Identify remaining object columns. Every one of them is
            # either one-hot encoded (up to MAX_ONE_HOT_CATEGORIES unique
            # values - technically modelable) or explicitly excluded with a
            # documented reason (never silently dropped).
            # is_string_dtype (not select_dtypes(include=['object'])):
            # pandas currently still includes StringDtype columns via a
            # backward-compat shim when 'object' is requested, but warns
            # this will be removed in a future version - checking directly
            # avoids depending on that shim.
            cat_cols = [c for c in self.df.columns if pd.api.types.is_string_dtype(self.df[c])]
            one_hot_cols: List[str] = []
            for col in cat_cols:
                nunique = self.df[col].nunique()
                if nunique <= 1:
                    # pd.get_dummies(..., drop_first=True) produces ZERO
                    # dummy columns for a column with 0 or 1 non-null
                    # unique values (no variance to encode). One-hot
                    # encoding it would therefore silently vanish the
                    # column with no replacement column and no trace -
                    # must be excluded explicitly instead, same as any
                    # other technically-non-modelable column.
                    if nunique == 0:
                        excluded_columns[col] = (
                            "coluna de texto sem nenhum valor preenchido (100% de valores "
                            "ausentes); não é possível utilizá-la como variável numérica. "
                            "Mantida como dado de identificação (identification_df), não "
                            "como candidata a variável."
                        )
                    else:
                        only_value = self.df[col].dropna().unique()[0]
                        excluded_columns[col] = (
                            f"coluna categórica com um único valor não-nulo ({only_value!r}) "
                            f"em todas as linhas; sem variância, não é tecnicamente viável "
                            f"codificar como variável numérica (one-hot encoding produziria "
                            f"zero colunas dummy com drop_first=True). Mantida como dado de "
                            f"identificação (identification_df), não como candidata a "
                            f"variável."
                        )
                elif nunique <= config.MAX_ONE_HOT_CATEGORIES:
                    one_hot_cols.append(col)
                else:
                    excluded_columns[col] = (
                        f"texto livre com {nunique} valores únicos, acima do limite de "
                        f"MAX_ONE_HOT_CATEGORIES ({config.MAX_ONE_HOT_CATEGORIES}); não é "
                        f"tecnicamente viável codificar como variável numérica (one-hot "
                        f"geraria {nunique} colunas dummy). Mantida como dado de "
                        f"identificação (identification_df), não como candidata a variável."
                    )

            for col in one_hot_cols:
                dummies = pd.get_dummies(self.df[col], prefix=col, drop_first=True)
                dummies = dummies.astype(int)
                self.df = pd.concat([self.df, dummies], axis=1)

            cols_to_drop = one_hot_cols + [c for c in excluded_columns.keys() if c in self.df.columns]
            if cols_to_drop:
                self.df = self.df.drop(columns=cols_to_drop)

            # 4. Handle columns with zero usable values (never silently
            # drop - previously `dropna(axis=1, how='all')` did this
            # without a trace). Only numeric columns can reach this point
            # entirely empty, since categorical columns were already
            # resolved above.
            numeric_cols = list(self.df.select_dtypes(include=[np.number]).columns)
            all_nan_cols = [c for c in numeric_cols if self.df[c].isna().all()]
            for col in all_nan_cols:
                excluded_columns[col] = (
                    "coluna sem nenhum valor preenchido (100% de valores ausentes); não é "
                    "possível utilizá-la como variável numérica. Mantida como dado de "
                    "identificação (identification_df), não como candidata a variável."
                )
            if all_nan_cols:
                self.df = self.df.drop(columns=all_nan_cols)

            # 5. Handle Missing Values
            # Simple strategy: Fill numeric with mean
            numeric_cols = list(self.df.select_dtypes(include=[np.number]).columns)
            if numeric_cols:
                self.df[numeric_cols] = self.df[numeric_cols].fillna(self.df[numeric_cols].mean())

            # Drop rows with remaining NaNs (e.g. residual gaps after mean
            # imputation); this is a row-level cleaning step, unrelated to
            # column exclusion above.
            self.df = self.df.dropna()

            # Build identification_df: the ORIGINAL, untransformed values of
            # every technically-excluded column (e.g. Endereço, Informante,
            # Telefone), aligned to the same rows that survived into the
            # final modeling dataframe.
            identification_df: Optional[pd.DataFrame] = None
            if excluded_columns:
                identification_df = self.original_df.loc[self.df.index, list(excluded_columns.keys())].copy()
            self.identification_df = identification_df

            # Initial validation
            validation = self._validate_initial_requirements(excluded_columns)

            return DataLoadResult(
                success=True,
                dataframe=self.df,
                validation=validation,
                variables=list(self.df.columns),
                sample_size=len(self.df),
                missing_values=self.df.isnull().sum().to_dict(),
                identification_df=identification_df,
                excluded_columns=excluded_columns,
            )

        except Exception as e:
            logger.error(f"Error loading data: {str(e)}")
            return DataLoadResult(success=False, message=f"Error loading data: {str(e)}", error=str(e))

    def _validate_initial_requirements(self, excluded_columns: Optional[Dict[str, str]] = None) -> ValidationResult:
        """
        Checks basic requirements like minimum sample size, and surfaces a
        warning for every column excluded from modeling (never silent -
        see load_data).
        """
        messages = []
        warnings = []
        is_valid = True

        n_samples = len(self.df)

        if excluded_columns:
            for col, reason in excluded_columns.items():
                warnings.append(f"Coluna '{col}' excluída da modelagem: {reason}")

        # NOTE: MIN_SAMPLES_GRAU_1/2/3 have no normative basis as absolute
        # minimums independent of k (number of model variables), so they must
        # never block/fail the data load. They are informational only here;
        # the actual normative criterion (n >= 3(k+1)/4(k+1)/6(k+1)) is
        # evaluated later, during model validation, once k is known.
        if n_samples < config.MIN_SAMPLES_GRAU_1:
            warnings.append(f"Insufficient samples: {n_samples}. Reference minimum for Degree 1 is {config.MIN_SAMPLES_GRAU_1} (informational; the binding normative minimum depends on the number of model variables k).")
        elif n_samples < config.MIN_SAMPLES_GRAU_2:
            warnings.append(f"Sample size {n_samples} only sufficient for Degree 1 (Minimum for Degree 2 is {config.MIN_SAMPLES_GRAU_2}).")
        elif n_samples < config.MIN_SAMPLES_GRAU_3:
            warnings.append(f"Sample size {n_samples} sufficient for Degree 1 and 2 (Minimum for Degree 3 is {config.MIN_SAMPLES_GRAU_3}).")

        return ValidationResult(
            success=True,
            is_valid=is_valid,
            messages=messages,
            warnings=warnings,
            details={"n_samples": n_samples}
        )

    def get_numeric_columns(self) -> List[str]:
        if self.df is None:
            return []
        return self.df.select_dtypes(include=[np.number]).columns.tolist()
