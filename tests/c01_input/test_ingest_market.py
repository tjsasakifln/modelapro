"""C01 acceptance tests. Drive ingest_market / load_data; do not reimplement the parser."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from modules.data_loader import (
    DataLoader,
    ingest_market,
    observed_target_count,
    reconstruct_original_record,
)
from modules.import_formats import DEFAULT_MAX_FILE_BYTES
from tests.c01_input.conftest import make_request_spec

FIXTURES = Path(__file__).parent / "fixtures"
A01_CSV = FIXTURES / "a01_precos.csv"


def _issue_codes(bundle) -> set:
    return {item["code"] for item in bundle.issues}


def _issues_with(bundle, code: str):
    return [item for item in bundle.issues if item["code"] == code]


def _xlsx_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


class TestA01NoInventedPrices:
    def test_missing_target_is_pending_not_mean_filled(self):
        file_bytes = A01_CSV.read_bytes()
        bundle = ingest_market(file_bytes, "a01_precos.csv", make_request_spec("preco"))

        assert bundle["schema_version"] == "MP/1"
        assert set(bundle.keys()) >= {
            "schema_version",
            "raw_frame",
            "parsed_frame",
            "column_map",
            "row_ledger",
            "input_sha256",
            "issues",
        }
        assert len(bundle.raw_frame) == 3
        assert len(bundle.row_ledger) == 3
        assert observed_target_count(bundle) == 2

        parsed_prices = list(bundle.parsed_frame["preco"])
        assert 700000 not in parsed_prices
        assert 700000.0 not in parsed_prices
        assert parsed_prices[0] == pytest.approx(600000.0)
        assert parsed_prices[1] == pytest.approx(800000.0)
        assert pd.isna(parsed_prices[2])

        pending = [entry for entry in bundle.row_ledger if not entry["observed_target"]]
        assert len(pending) == 1
        assert pending[0]["disposition"] == "pending_target"
        assert "preco" in pending[0]["missing_before"]
        assert pending[0]["row_id"] == bundle.parsed_frame.iloc[2]["row_id"]

        observed_ids = [e["row_id"] for e in bundle.row_ledger if e["observed_target"]]
        assert len(observed_ids) == 2
        assert "row_id" in bundle.parsed_frame.columns

        raw_third = bundle.raw_frame.iloc[2]["preco"]
        assert raw_third == "" or pd.isna(raw_third)

    def test_missing_before_is_not_reconstructed_after_parse(self):
        csv = "preco,area\n600000,\n800000,80\n".encode("utf-8")
        bundle = ingest_market(csv, "gap.csv", make_request_spec("preco"))
        first = bundle.row_ledger[0]
        assert "area" in first["missing_before"]
        assert first["observed_target"] is True
        assert pd.isna(bundle.parsed_frame.iloc[0]["area"])

    def test_load_data_adapter_does_not_invent_700000(self):
        loader = DataLoader()
        result = loader.load_data(A01_CSV.read_bytes(), "a01_precos.csv")
        assert result.success is True
        prices = list(result.dataframe["preco"])
        assert 700000 not in prices
        assert 700000.0 not in prices
        assert any(pd.isna(v) for v in prices)
        assert len(result.dataframe) == 3


class TestA02NumericLocale:
    def _ingest_value(self, raw: str, locale: str, filename: str = "n.csv"):
        csv = f"valor\n{raw}\n".encode("utf-8")
        spec = make_request_spec("valor", locale=locale)
        return ingest_market(csv, filename, spec)

    def test_pt_br_currency(self):
        bundle = self._ingest_value('"R$ 1.234,56"', "pt-BR")
        assert bundle.parsed_frame.iloc[0]["valor"] == pytest.approx(1234.56)

    def test_en_us_thousands(self):
        bundle = self._ingest_value('"1,234.56"', "en-US")
        assert bundle.parsed_frame.iloc[0]["valor"] == pytest.approx(1234.56)

    def test_decimal_point_string(self):
        bundle = self._ingest_value("123.45", "auto")
        assert bundle.parsed_frame.iloc[0]["valor"] == pytest.approx(123.45)

    def test_ambiguous_dot_group_does_not_change_magnitude(self):
        bundle = self._ingest_value("1.234", "auto")
        value = bundle.parsed_frame.iloc[0]["valor"]
        assert value == "1.234" or value == 1.234
        assert value != 1234 and value != 1234.0
        assert any(item["code"] == "ambiguous_number" for item in bundle.issues)

    def test_ambiguous_resolved_by_pt_br(self):
        bundle = self._ingest_value("1.234", "pt-BR")
        assert bundle.parsed_frame.iloc[0]["valor"] == pytest.approx(1234.0)

    def test_ambiguous_resolved_by_en_us(self):
        bundle = self._ingest_value("1.234", "en-US")
        assert bundle.parsed_frame.iloc[0]["valor"] == pytest.approx(1.234)

    def test_already_numeric_column_keeps_magnitude(self):
        df = pd.DataFrame({"valor": [1234.56, 600000.0]})
        bundle = ingest_market(_xlsx_bytes(df), "already.xlsx", make_request_spec("valor"))
        assert bundle.parsed_frame.iloc[0]["valor"] == pytest.approx(1234.56)
        assert bundle.parsed_frame.iloc[1]["valor"] == pytest.approx(600000.0)

    def test_identifier_cep_keeps_leading_zeros(self):
        csv = "preco,cep\n100000,01310-100\n200000,04038-001\n".encode("utf-8")
        spec = make_request_spec("preco", roles={"cep": "identifier"})
        bundle = ingest_market(csv, "cep.csv", spec)
        ceps = list(bundle.parsed_frame["cep"])
        assert ceps[0] == "01310-100"
        assert ceps[1] == "04038-001"
        assert not any(isinstance(v, float) for v in ceps)

    def test_phone_and_date_not_converted_by_parse_rate(self):
        csv = (
            "preco,telefone,data\n"
            "100000,(11) 90000-0000,2024-01-15\n"
            "200000,(11) 90000-0001,2024-02-01\n"
        ).encode("utf-8")
        spec = make_request_spec(
            "preco",
            roles={"telefone": "identifier", "data": "date"},
        )
        bundle = ingest_market(csv, "ids.csv", spec)
        assert str(bundle.parsed_frame.iloc[0]["telefone"]).startswith("(11)")
        assert "2024-01-15" in str(bundle.parsed_frame.iloc[0]["data"])


class TestA03CsvExcelParity:
    def test_semicolon_bom_and_excel_same_interpreted_base(self):
        csv_text = "preco;area;bairro\nR$ 600.000,00;50,0;Centro\nR$ 800.000,00;80,5;Sul\n"
        csv_bytes = b"\xef\xbb\xbf" + csv_text.encode("utf-8")
        spec_csv = make_request_spec("preco", locale="pt-BR", delimiter=";")
        csv_bundle = ingest_market(csv_bytes, "mercado.CSV", spec_csv)

        excel_df = pd.DataFrame(
            {
                "preco": [600000.0, 800000.0],
                "area": [50.0, 80.5],
                "bairro": ["Centro", "Sul"],
            }
        )
        xlsx_bundle = ingest_market(
            _xlsx_bytes(excel_df),
            "mercado.xlsx",
            make_request_spec("preco", locale="pt-BR"),
        )

        for bundle in (csv_bundle, xlsx_bundle):
            assert observed_target_count(bundle) == 2
            assert list(bundle.parsed_frame["preco"]) == pytest.approx([600000.0, 800000.0])
            assert list(bundle.parsed_frame["area"]) == pytest.approx([50.0, 80.5])
            assert list(bundle.parsed_frame["bairro"]) == ["Centro", "Sul"]
            assert [e["disposition"] for e in bundle.row_ledger] == ["observed", "observed"]

        assert csv_bundle.input_sha256 != xlsx_bundle.input_sha256
        assert any(i["code"] == "read_metadata" for i in csv_bundle.issues)
        assert any(i["evidence"].get("bom") for i in csv_bundle.issues if i["code"] == "read_metadata")

    def test_latin1_encoding(self):
        text = "preco;bairro\n100000;Jardim União\n"
        csv_bytes = text.encode("latin1")
        spec = make_request_spec("preco", locale="pt-BR", delimiter=";", encoding="latin1")
        bundle = ingest_market(csv_bytes, "latin.csv", spec)
        assert bundle.parsed_frame.iloc[0]["bairro"] == "Jardim União"

    def test_uppercase_csv_extension(self):
        bundle = ingest_market(
            A01_CSV.read_bytes(),
            "A01.CSV",
            make_request_spec("preco"),
        )
        assert observed_target_count(bundle) == 2

    def test_xls_without_engine_is_structured_issue(self):
        bundle = ingest_market(b"not-an-xls", "mercado.xls", make_request_spec("preco"))
        codes = _issue_codes(bundle)
        assert "excel_engine_missing" in codes or "excel_parse_error" in codes
        assert any(i["severity"] == "error" for i in bundle.issues)
        assert len(bundle.raw_frame) == 0

    def test_invalid_format_has_field(self):
        bundle = ingest_market(b"junk", "notes.txt", make_request_spec("preco"))
        err = _issues_with(bundle, "unsupported_format")[0]
        assert err["severity"] == "error"
        assert err["evidence"].get("field") == "filename"

    def test_file_size_limit_reported_for_c10(self):
        spec = make_request_spec("preco")
        spec["import_options"]["max_file_bytes"] = 8
        bundle = ingest_market(b"preco,area\n1,2\n", "big.csv", spec)
        err = _issues_with(bundle, "file_size_limit")[0]
        assert err["evidence"]["report_to"] == "C10"
        assert err["evidence"]["limit_bytes"] == 8
        assert DEFAULT_MAX_FILE_BYTES > 8


class TestA04ExplicitErrors:
    def test_column_name_collision_is_not_silent(self):
        csv = "foo-bar,foobar,preco\n1,2,3\n".encode("utf-8")
        bundle = ingest_market(csv, "cols.csv", make_request_spec("preco"))
        internals = [e["internal"] for e in bundle.column_map["entries"]]
        assert len(internals) == len(set(internals))
        assert any(e["collision"] for e in bundle.column_map["entries"])
        assert "column_name_collision" in _issue_codes(bundle)
        orig_to_int = bundle.column_map["original_to_internal"]
        int_to_orig = bundle.column_map["internal_to_original"]
        for original, internal in orig_to_int.items():
            assert int_to_orig[internal] == original

    def test_non_string_and_accented_column_names_are_reversible(self):
        df = pd.DataFrame({0: [1, 2], "Área (m²)": [10, 20], "preco": [100.0, 200.0]})
        bundle = ingest_market(_xlsx_bytes(df), "names.xlsx", make_request_spec("preco"))
        for entry in bundle.column_map["entries"]:
            assert bundle.column_map["internal_to_original"][entry["internal"]] == entry["original"]
            assert bundle.column_map["original_to_internal"][entry["original"]] == entry["internal"]

    def test_duplicate_identifiers_keep_distinct_row_ids(self):
        csv = "codigo,preco\nA,10\nA,20\nB,30\n".encode("utf-8")
        spec = make_request_spec("preco", roles={"codigo": "identifier"})
        bundle = ingest_market(csv, "dup.csv", spec)
        row_ids = [e["row_id"] for e in bundle.row_ledger]
        assert len(row_ids) == len(set(row_ids)) == 3
        assert "duplicate_identifier" in _issue_codes(bundle)
        assert observed_target_count(bundle) == 3

    def test_non_finite_target_is_rejected(self):
        csv = "preco,area\n600000,50\ninf,80\n".encode("utf-8")
        bundle = ingest_market(csv, "inf.csv", make_request_spec("preco"))
        assert "non_finite_value" in _issue_codes(bundle)
        inf_row = bundle.row_ledger[1]
        assert inf_row["observed_target"] is False
        assert inf_row["disposition"] == "rejected"
        assert observed_target_count(bundle) == 1

    def test_empty_file(self):
        bundle = ingest_market(b"", "empty.csv", make_request_spec("preco"))
        assert "empty_file" in _issue_codes(bundle)
        assert bundle.row_ledger == []

    def test_header_only_is_empty(self):
        bundle = ingest_market(b"preco,area\n", "header.csv", make_request_spec("preco"))
        assert "empty_file" in _issue_codes(bundle)

    def test_missing_target_column(self):
        csv = "area,bairro\n50,Centro\n".encode("utf-8")
        bundle = ingest_market(csv, "notarget.csv", make_request_spec("preco"))
        err = _issues_with(bundle, "target_not_found")[0]
        assert err["severity"] == "error"
        assert err["evidence"]["field"] == "target_col"
        authorized = []
        for item in bundle.issues:
            if item["code"] == "candidate_selection_auto":
                authorized = item["evidence"]["authorized_predictors"]
        assert "preco" not in authorized

    def test_empty_candidate_cols_is_selection_error(self):
        csv = "preco,area\n1,2\n".encode("utf-8")
        spec = make_request_spec("preco", candidate_cols=[])
        bundle = ingest_market(csv, "none.csv", spec)
        err = _issues_with(bundle, "empty_candidate_selection")[0]
        assert err["severity"] == "error"
        auto = [i for i in bundle.issues if i["code"] == "candidate_selection_auto"]
        assert auto == []

    def test_absent_requested_column_does_not_expand_universe(self):
        csv = "preco,area,quartos\n1,2,3\n".encode("utf-8")
        spec = make_request_spec("preco", candidate_cols=["area", "garagem"])
        bundle = ingest_market(csv, "missing_col.csv", spec)
        err = _issues_with(bundle, "requested_column_absent")[0]
        assert "garagem" in err["evidence"]["missing"]
        assert err["evidence"]["authorized"] == ["area"]
        assert "quartos" not in err["evidence"]["authorized"]

    def test_malformed_number_is_explicit(self):
        csv = "preco,area\n12.34.56,10\n".encode("utf-8")
        bundle = ingest_market(csv, "bad.csv", make_request_spec("preco"))
        assert "malformed_number" in _issue_codes(bundle)
        bad = bundle.row_ledger[0]
        assert bad["observed_target"] is False
        assert any(c.get("action") == "malformed_unconverted" for c in bad["changes"])

    def test_source_row_id_column_does_not_overwrite_identity(self):
        csv = "row_id,preco\nmarket-a,10\nmarket-b,20\n".encode("utf-8")
        bundle = ingest_market(csv, "rowid.csv", make_request_spec("preco"))
        generated = list(bundle.parsed_frame["row_id"])
        assert generated == [e["row_id"] for e in bundle.row_ledger]
        assert generated[0].startswith("R")
        source_internal = bundle.column_map["original_to_internal"]["row_id"]
        assert source_internal != "row_id"
        assert list(bundle.parsed_frame[source_internal]) == ["market-a", "market-b"]

    def test_row_id_born_before_filters_and_not_pandas_index(self):
        csv = "preco,area\n1,2\n3,4\n".encode("utf-8")
        bundle = ingest_market(csv, "idx.csv", make_request_spec("preco"))
        assert [e["row_id"] for e in bundle.row_ledger] == list(bundle.parsed_frame["row_id"])
        assert list(bundle.raw_frame.index) == [0, 1]
        assert bundle.row_ledger[0]["row_id"] != bundle.raw_frame.index[0]


class TestA05ProvenanceRoundTrip:
    def test_round_trip_recovers_raw_and_changes(self):
        csv = (
            "Preço,Área,bairro\n"
            '"R$ 1.234,56",50,Centro\n'
            '"R$ 2.000,00",80,Sul\n'
        ).encode("utf-8")
        spec = make_request_spec("Preço", locale="pt-BR")
        bundle = ingest_market(csv, "prov.csv", spec)
        assert observed_target_count(bundle) == 2

        for entry in bundle.row_ledger:
            recovered = reconstruct_original_record(bundle, entry["row_id"])
            raw_values = recovered["values"]
            assert set(raw_values) == set(bundle.raw_frame.columns)
            for column, value in raw_values.items():
                original_cell = bundle.raw_frame.iloc[
                    [e["row_id"] for e in bundle.row_ledger].index(entry["row_id"])
                ][column]
                if pd.isna(value) and pd.isna(original_cell):
                    continue
                assert value == original_cell
            assert recovered["changes"] == entry["changes"]
            for change in entry["changes"]:
                orig_col = change["original_column"]
                assert raw_values[orig_col] == change["raw"]

        first_price = bundle.parsed_frame.iloc[0]["preço"]
        assert first_price == pytest.approx(1234.56)
        assert any("R$" in str(c["raw"]) for c in bundle.row_ledger[0]["changes"])

    def test_fixtures_are_synthetic(self):
        text = A01_CSV.read_text(encoding="utf-8")
        forbidden = ["cpf", "rg", "sasaki", "@gmail", "real-person"]
        lowered = text.lower()
        assert all(token not in lowered for token in forbidden)


class TestLegacyAdapter:
    def test_high_cardinality_text_kept_with_capacity_warning(self):
        from modules.config_manager import config

        limit = config.MAX_ONE_HOT_CATEGORIES
        n = limit + 20
        df = pd.DataFrame(
            {
                "col1": list(range(1, n + 1)),
                "col2": [float(i) * 2.0 for i in range(1, n + 1)],
                "endereco": [f"Rua Exemplo, {i}, Bairro {i}" for i in range(n)],
            }
        )
        result = DataLoader().load_data(df.to_csv(index=False).encode("utf-8"), "card.csv")
        assert result.success is True
        assert "endereco" in result.dataframe.columns
        assert "endereco" not in result.excluded_columns
        assert not any(c.startswith("endereco_") for c in result.dataframe.columns)
        assert any("capacidade" in w.lower() or "MAX_ONE_HOT" in w for w in result.validation.warnings)
        assert "impossibilidade matemática" in " ".join(result.validation.warnings).lower() or any(
            "C02" in w for w in result.validation.warnings
        )
