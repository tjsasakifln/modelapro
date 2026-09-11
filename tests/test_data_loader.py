import pytest
import pandas as pd
import io
from modules.data_loader import DataLoader
from modules.config_manager import config

class TestDataLoader:
    def test_load_csv_valid(self):
        loader = DataLoader()
        csv_content = b"col1,col2\n1,2\n3,4\n5,6\n7,8\n9,10\n11,12\n13,14\n15,16\n17,18\n19,20\n21,22\n23,24\n25,26\n27,28\n29,30"
        result = loader.load_data(csv_content, "test.csv")
        
        assert result.success is True
        assert result.dataframe is not None
        assert len(result.dataframe) == 15
        assert "col1" in result.dataframe.columns
        
    def test_load_invalid_format(self):
        loader = DataLoader()
        result = loader.load_data(b"junk", "test.txt")
        assert result.success is False
        assert "Unsupported file format" in result.message
        
    def test_insufficient_samples(self):
        loader = DataLoader()
        # Create small CSV
        csv_content = b"col1\n1\n2"
        result = loader.load_data(csv_content, "test.csv")

        assert result.success is True # Loading succeeds
        # Sample-size minimums have no normative basis independent of k, so
        # they must not block the data load anymore - only warn.
        assert result.validation.is_valid is True
        assert any("Insufficient samples" in w for w in result.validation.warnings)

    def test_high_cardinality_categorical_is_excluded_not_dropped_silently(self):
        """
        A categorical column with more unique values than
        config.MAX_ONE_HOT_CATEGORIES (e.g. a free-text "Endereço" or
        "Informante" column) is technically not one-hot-encodable. It must:
          - NOT raise, and NOT affect the rest of the load (numeric columns
            still load normally, sample survives);
          - appear in excluded_columns with a documented reason;
          - be surfaced as a warning in validation.warnings;
          - have its ORIGINAL (untransformed) values preserved in
            identification_df, aligned to the final dataframe's rows.
        """
        n = 30
        # nunique = n > MAX_ONE_HOT_CATEGORIES (default 50 is >= n in some
        # envs, so force nunique explicitly above the configured limit by
        # using a value per row - each row is unique, guaranteeing
        # nunique == n regardless of the configured threshold, as long as
        # the threshold is below n... to be robust, build enough rows).
        limit = config.MAX_ONE_HOT_CATEGORIES
        n = limit + 20
        col1 = list(range(1, n + 1))
        col2 = [float(i) * 2.0 for i in range(1, n + 1)]
        # One free-text value per row => nunique == n > limit, guaranteed
        # to exceed MAX_ONE_HOT_CATEGORIES.
        endereco = [f"Rua Exemplo, {i}, Bairro {i}" for i in range(n)]

        df = pd.DataFrame({"col1": col1, "col2": col2, "endereco": endereco})
        csv_content = df.to_csv(index=False).encode("utf-8")

        loader = DataLoader()
        result = loader.load_data(csv_content, "test.csv")

        assert result.success is True
        assert result.error is None

        # Excluded with a documented reason, never silently dropped.
        assert "endereco" in result.excluded_columns
        reason = result.excluded_columns["endereco"]
        assert "MAX_ONE_HOT_CATEGORIES" in reason or str(limit) in reason

        # Surfaced as a warning.
        assert any(
            "endereco" in w and "excluída" in w.lower()
            for w in result.validation.warnings
        )

        # Rest of the load is unaffected: numeric columns still present,
        # sample size preserved.
        assert "col1" in result.dataframe.columns
        assert "col2" in result.dataframe.columns
        assert "endereco" not in result.dataframe.columns
        assert len(result.dataframe) == n

        # Original values preserved in identification_df, aligned to the
        # surviving rows.
        assert result.identification_df is not None
        assert "endereco" in result.identification_df.columns
        preserved = result.identification_df.loc[result.dataframe.index, "endereco"]
        original_aligned = pd.Series(endereco, name="endereco").loc[result.dataframe.index]
        assert list(preserved) == list(original_aligned)

    def test_numeric_text_column_is_converted_regardless_of_string_dtype(self):
        """
        Regression test: step 2 of load_data ("Convert Numeric Columns")
        must detect and convert Brazilian-formatted numeric strings (e.g.
        "1.234,56") even when pandas reads the column as its dedicated
        StringDtype ("string"/"str") instead of legacy `object` - which is
        what pd.read_csv actually returns by default in the pandas version
        installed here (confirmed: pandas 3.0). A raw `dtype == 'object'`
        check silently never matches StringDtype columns and skips
        safe_float_conversion entirely, misclassifying an otherwise-numeric
        market variable as an unmodelable/categorical text column.
        """
        loader = DataLoader()
        n = 20
        # Brazilian-format prices, e.g. "1.100,10" -> 1100.10
        precos = [f"1.{100 + i:03d},{10 + i:02d}" for i in range(n)]
        col2 = list(range(n))
        # Quote the price field: it contains a comma (Brazilian decimal
        # separator) which would otherwise be misread as the CSV delimiter.
        lines = ["preco,col2"] + [f'"{precos[i]}",{col2[i]}' for i in range(n)]
        csv_content = ("\n".join(lines)).encode("utf-8")

        result = loader.load_data(csv_content, "test.csv")

        assert result.success is True
        assert "preco" not in result.excluded_columns
        assert "preco" in result.dataframe.columns
        assert pd.api.types.is_numeric_dtype(result.dataframe["preco"])
        # "1.100,10" -> 1100.10
        assert abs(float(result.dataframe["preco"].iloc[0]) - 1100.10) < 1e-6
