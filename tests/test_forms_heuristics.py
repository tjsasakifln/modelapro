import pandas as pd
from frontend.components.forms import (
    _looks_like_identification,
    build_request_spec,
    build_subject_payload,
    candidate_cols_from_selection,
    suggest_roles,
    validate_dispatch,
)
from tests.c09_frontend.fixtures import PREVIEW_BAIRRO_FORMATTED


class TestLooksLikeIdentification:
    """
    Regression coverage for a real bug found via live browser testing:
    `_looks_like_identification` used `series.dtype != object` to bail out
    early for non-text columns. pandas 3.0 (installed here) reads text
    columns from pd.read_csv/read_excel as the dedicated StringDtype
    ("string"/"str"), not legacy `object` - the raw `!= object` check
    silently never matched those columns, disabling the whole heuristic for
    every text column (Informante/Telefone/Endereço stayed checked by
    default in the actual running app instead of being excluded).
    """

    def _string_series(self, values):
        # This is exactly the dtype pd.read_csv/read_excel produce by
        # default in the installed pandas version - using it here (instead
        # of forcing legacy object dtype) is the point of the regression
        # test.
        return pd.Series(values, dtype="string")

    def test_identification_keyword_excluded_with_string_dtype(self):
        s = self._string_series(["Fulano", "Ciclano", "Beltrano"])
        assert _looks_like_identification("Informante", s) == True

    def test_telefone_multiword_excluded_with_string_dtype(self):
        s = self._string_series(["(48) 99999-0000", "(48) 98888-1111"])
        assert _looks_like_identification("Telefone Informante", s) == True

    def test_endereco_excluded_with_string_dtype(self):
        s = self._string_series(["Rua A, 100", "Rua B, 200"])
        assert _looks_like_identification("Endereço", s) == True

    def test_legitimate_categorical_not_excluded(self):
        # "bairro" is intentionally not a keyword - it's a legitimate
        # categorical market variable, not identification data.
        s = self._string_series(["Centro", "Norte", "Centro"])
        assert _looks_like_identification("Bairro", s) == False

    def test_numeric_column_never_excluded_regardless_of_name(self):
        s = pd.Series([1, 2, 3])
        assert _looks_like_identification("id", s) == False


class TestRequestSpecFromBairroAndFormattedNumber:
    """C09-A01: o mapeamento enviado (não uma reimplementação no teste)."""

    def test_form_pass_yields_coherent_spec_and_subject(self):
        roles = suggest_roles(PREVIEW_BAIRRO_FORMATTED["column_map"], target_col="preco")
        spec = build_request_spec(
            target_col="preco",
            candidate_cols=["bairro", "area"],
            roles=roles,
            units={"area": "m2"},
            target_unit="",
        )
        subject = build_subject_payload(
            PREVIEW_BAIRRO_FORMATTED["feature_schema"],
            {"bairro": "Centro", "area": "1.234,56"},
        )
        assert spec["roles"]["bairro"] == "predictor"
        assert spec["candidate_cols"] == ["bairro", "area"]
        assert spec["target_unit"] == ""
        assert spec["reference_date"] is None
        assert subject["raw_values"]["bairro"] == "Centro"
        assert subject["raw_values"]["área"] == "1.234,56"
        decision = validate_dispatch(spec, subject, preview=PREVIEW_BAIRRO_FORMATTED)
        assert decision["ok"] is True

    def test_empty_candidate_cols_is_none_authorized(self):
        spec = build_request_spec(
            target_col="preco",
            candidate_cols=candidate_cols_from_selection([], auto=False),
            roles={"preco": "target", "bairro": "predictor"},
        )
        assert spec["candidate_cols"] == []
        decision = validate_dispatch(spec, {"supported": True, "issues": []}, preview=PREVIEW_BAIRRO_FORMATTED)
        assert decision["can_dispatch"] is False
        assert any(item["code"] == "no_authorized_variables" for item in decision["blocking"])
