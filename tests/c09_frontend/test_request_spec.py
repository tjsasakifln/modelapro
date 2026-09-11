"""C09-A01: formulário → RequestSpec / avaliando coerentes."""

import json

from frontend.components.forms import (
    EMPTY_SELECTION_MESSAGE,
    build_request_spec,
    build_subject_payload,
    candidate_cols_from_selection,
    preview_to_form_model,
    request_spec_json,
    suggest_roles,
    validate_dispatch,
)
from tests.c09_frontend.fixtures import PREVIEW_BAIRRO_FORMATTED


def _spec_from_preview(*, candidate_cols, target_unit="", reference_date=None, inspection_date=None):
    model = preview_to_form_model(PREVIEW_BAIRRO_FORMATTED)
    roles = suggest_roles(model["column_map"], target_col="preco")
    return build_request_spec(
        target_col="preco",
        candidate_cols=candidate_cols,
        roles=roles,
        units={"area": "m2"},
        reference_date=reference_date,
        inspection_date=inspection_date,
        target_unit=target_unit,
        applicant="Banco Exemplo",
        purpose="garantia",
        minimum_fundamentacao_grade=2,
    )


def test_preview_to_form_model_accepts_c01_entries_column_map():
    preview = {
        "column_map": {
            "entries": [
                {"original": "id", "internal": "id", "kind": "text"},
                {"original": "area", "internal": "area", "kind": "numeric"},
                {"original": "preco", "internal": "preco", "kind": "numeric"},
            ]
        },
        "feature_schema": {
            "columns": {
                "area": {"original_name": "area", "kind": "numeric"},
                "preco": {"original_name": "preco", "kind": "numeric", "role": "target"},
            }
        },
        "issues": [],
    }
    model = preview_to_form_model(preview)
    assert "area" in model["column_map"]
    assert isinstance(model["column_map"]["area"], dict)
    assert model["column_map"]["area"].get("kind") == "numeric"
    assert "entries" not in model["columns"]


class TestBairroAndFormattedNumberMapping:
    def test_bairro_is_predictor_not_identifier(self):
        roles = suggest_roles(PREVIEW_BAIRRO_FORMATTED["column_map"], target_col="preco")
        assert roles["bairro"] == "predictor"
        assert roles["preco"] == "target"
        assert roles["informante"] == "identifier"
        assert roles["area"] == "predictor"

    def test_request_spec_keeps_bairro_and_does_not_assume_brl_or_today(self):
        spec = _spec_from_preview(candidate_cols=["bairro", "area"])
        assert spec["schema_version"] == "MP/1"
        assert spec["target_col"] == "preco"
        assert spec["candidate_cols"] == ["bairro", "area"]
        assert spec["roles"]["bairro"] == "predictor"
        assert spec["target_unit"] == ""
        assert spec["reference_date"] is None
        assert spec["inspection_date"] is None
        assert spec["missing_policy"]["target"] == "never_impute"
        dumped = request_spec_json(spec)
        parsed = json.loads(dumped)
        assert parsed["candidate_cols"] == ["bairro", "area"]
        assert parsed["reference_date"] is None
        assert "BRL" not in parsed["target_unit"]

    def test_subject_keeps_formatted_number_and_category_not_dummies(self):
        schema = PREVIEW_BAIRRO_FORMATTED["feature_schema"]
        subject = build_subject_payload(
            schema,
            {"bairro": "Centro", "area": "1.234,56"},
        )
        assert subject["supported"] is True
        assert subject["raw_values"]["bairro"] == "Centro"
        assert subject["raw_values"]["área"] == "1.234,56"
        assert "bairro_Centro" not in subject["raw_values"]
        assert "bairro_Norte" not in subject["raw_values"]
        assert 0 not in subject["raw_values"].values()

    def test_empty_candidate_cols_means_none_and_blocks_dispatch(self):
        spec = _spec_from_preview(candidate_cols=[])
        assert spec["candidate_cols"] == []
        assert spec["candidate_cols"] is not None
        subject = build_subject_payload(
            PREVIEW_BAIRRO_FORMATTED["feature_schema"],
            {"bairro": "Centro", "area": "1.234,56"},
        )
        decision = validate_dispatch(spec, subject, preview=PREVIEW_BAIRRO_FORMATTED)
        assert decision["ok"] is False
        assert decision["can_dispatch"] is False
        assert any(item["code"] == "no_authorized_variables" for item in decision["blocking"])
        assert EMPTY_SELECTION_MESSAGE in decision["blocking"][0]["message"] or any(
            EMPTY_SELECTION_MESSAGE in item["message"] for item in decision["blocking"]
        )

    def test_empty_selection_helper_is_empty_list_not_all_columns(self):
        assert candidate_cols_from_selection([], auto=False) == []
        assert candidate_cols_from_selection(["bairro"], auto=True) is None

    def test_unsupported_category_blocks_until_resolved(self):
        schema = PREVIEW_BAIRRO_FORMATTED["feature_schema"]
        subject = build_subject_payload(schema, {"bairro": "Sul", "area": "1.234,56"})
        assert subject["supported"] is False
        assert any(i.get("requires_resolution") for i in subject["issues"])
        spec = _spec_from_preview(candidate_cols=["bairro", "area"], target_unit="BRL")
        decision = validate_dispatch(spec, subject, preview=PREVIEW_BAIRRO_FORMATTED)
        assert decision["ok"] is False

        resolved = build_subject_payload(
            schema,
            {"bairro": "Sul", "area": "1.234,56"},
            resolutions={"bairro": {"action": "map_to_supported", "mapped_value": "Centro"}},
        )
        assert resolved["supported"] is True
        assert resolved["raw_values"]["bairro"] == "Centro"
        decision_ok = validate_dispatch(spec, resolved, preview=PREVIEW_BAIRRO_FORMATTED)
        assert decision_ok["ok"] is True

    def test_dates_are_own_fields_when_provided(self):
        spec = _spec_from_preview(
            candidate_cols=["bairro", "area"],
            target_unit="BRL",
            reference_date="2024-02-01",
            inspection_date="2024-01-20",
        )
        assert spec["reference_date"] == "2024-02-01"
        assert spec["inspection_date"] == "2024-01-20"
        assert spec["reference_date"] != spec["inspection_date"]
