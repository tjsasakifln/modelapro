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

    def test_high_cardinality_text_is_kept_capacity_reported_not_excluded(self):
        """
        C01 does not treat high cardinality as a mathematical impossibility
        and does not one-hot-encode here (C02 owns encoding). A free-text
        column must remain in the dataframe, not be dummy-coded, and the
        capacity limit is reported with a reason.
        """
        limit = config.MAX_ONE_HOT_CATEGORIES
        n = limit + 20
        col1 = list(range(1, n + 1))
        col2 = [float(i) * 2.0 for i in range(1, n + 1)]
        endereco = [f"Rua Exemplo, {i}, Bairro {i}" for i in range(n)]

        df = pd.DataFrame({"col1": col1, "col2": col2, "endereco": endereco})
        csv_content = df.to_csv(index=False).encode("utf-8")

        loader = DataLoader()
        result = loader.load_data(csv_content, "test.csv")

        assert result.success is True
        assert result.error is None
        assert "endereco" not in result.excluded_columns
        assert "endereco" in result.dataframe.columns
        assert not any(c.startswith("endereco_") for c in result.dataframe.columns)
        assert any(
            "endereco" in w and ("MAX_ONE_HOT_CATEGORIES" in w or str(limit) in w)
            for w in result.validation.warnings
        )
        assert "col1" in result.dataframe.columns
        assert "col2" in result.dataframe.columns
        assert len(result.dataframe) == n
        assert list(result.dataframe["endereco"]) == endereco

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

    def test_load_data_does_not_impute_missing_target_with_mean(self):
        loader = DataLoader()
        csv_content = b"preco,area\n600000,50\n800000,80\n,70\n"
        result = loader.load_data(csv_content, "test.csv")
        assert result.success is True
        prices = list(result.dataframe["preco"])
        assert 700000 not in prices
        assert 700000.0 not in prices
        assert any(pd.isna(v) for v in prices)

    def test_uppercase_csv_extension_is_supported(self):
        loader = DataLoader()
        result = loader.load_data(b"col1,col2\n1,2\n3,4\n", "market.CSV")
        assert result.success is True
        assert len(result.dataframe) == 2
