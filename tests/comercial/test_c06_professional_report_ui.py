"""C06: native professional fields reach the real frontend contracts."""

from __future__ import annotations

import textwrap

import pytest
from streamlit.testing.v1 import AppTest

from frontend.components.documents import _document_sample_rows
from frontend.components.forms import _sample_evidence_seed
from modules.pro_workflow.report_context import complete_report_context


def _by_label(elements, label: str):
    for element in elements:
        if getattr(element, "label", None) == label:
            return element
    raise AssertionError(f"widget not found: {label}")


def _select_sample_mapping(at: AppTest) -> None:
    for label, value in {
        "Coluna do endereço da amostra": "endereco",
        "Coluna da latitude da amostra": "latitude",
        "Coluna da longitude da amostra": "longitude",
        "Coluna da fonte da amostra": "fonte",
    }.items():
        _by_label(at.selectbox, label).select(value)


UPLOAD_APP = textwrap.dedent(
    '''
    import streamlit as st
    from frontend.components.forms import upload_form

    preview = {
        "schema_version": "MP/1",
        "input_sha256": "ui-input",
        "column_map": {
            "id": {"original_name": "id", "kind": "identifier"},
            "area": {"original_name": "area", "kind": "numeric"},
            "preco": {"original_name": "preco", "kind": "numeric"},
            "endereco": {"original_name": "endereco", "kind": "categorical"},
            "latitude": {"original_name": "latitude", "kind": "numeric"},
            "longitude": {"original_name": "longitude", "kind": "numeric"},
            "fonte": {"original_name": "fonte", "kind": "categorical"},
        },
        "feature_schema": {"columns": {
            "id": {"original_name": "id", "kind": "identifier"},
            "area": {"original_name": "area", "kind": "numeric"},
            "preco": {"original_name": "preco", "kind": "numeric", "role": "target"},
            "endereco": {"original_name": "endereco", "kind": "categorical", "categories": ["Rua A"]},
            "latitude": {"original_name": "latitude", "kind": "numeric"},
            "longitude": {"original_name": "longitude", "kind": "numeric"},
            "fonte": {"original_name": "fonte", "kind": "categorical", "categories": ["Anúncio"]},
        }},
        "row_ledger": [{"row_id": "R000000"}],
        "sample_preview": [{
            "id": "A1", "area": 73.5, "preco": 735000,
            "endereco": "Rua A", "latitude": -23.5, "longitude": -46.6, "fonte": "Anúncio",
        }],
        "issues": [],
    }

    def preview_provider(*args, **kwargs):
        return preview

    result = upload_form(preview_provider=preview_provider)
    if result.get("request_spec"):
        st.session_state["captured_request_spec"] = result["request_spec"]
        st.session_state["captured_dispatch"] = result["dispatch"]
        st.session_state["captured_execute"] = result["execute"]
    '''
)


DOCUMENT_APP = textwrap.dedent(
    '''
    import json
    import streamlit as st
    from frontend.components.documents import render_document_workflow

    CONTEXT = {
        "schema_version": "MP-REPORT-CONTEXT/1",
        "purpose": "garantia imobiliária",
        "objective": "valor de mercado para compra e venda",
        "market_diagnosis": "mercado com oferta regular",
        "observations": ["faixa admissível registrada", "revisão necessária"],
        "asset_identification": {"matricula": "123", "municipio": "São Paulo"},
        "variable_classification": {
            "area": {"criterion": "área privativa", "coding": {"m2": "contínua"}},
            "id": {"criterion": "identificador", "coding": "texto"},
        },
        "professional_identity": {
            "name": "Ana Avaliadora", "council": "CREA", "registration": "12345",
            "art_rrt": "ART-12345", "documentary_reference": "certidão 7",
        },
        "subject": {
            "area": "73,5",
            "geolocation": {"latitude": -23.5, "longitude": -46.6, "address": "Rua A, 10", "source": "vistoria"},
        },
        "sample_evidence_columns": {
            "address": "endereco", "latitude": "lat", "longitude": "lon", "source": "fonte",
        },
        "used_rows": [{"row_id": "R000000", "values": {
            "id": "CSV-947",
            "area": 70, "preco": 700000, "endereco": "Rua B, 20",
            "lat": -23.6, "lon": -46.7, "fonte": "anúncio",
        }, "geolocation": {
            "address": "Rua B, 20", "latitude": -23.6,
            "longitude": -46.7, "source": "anúncio", "complete": True, "issues": [],
        }}],
        "excluded_rows": [],
        "target_col": "preco",
        "output_evidence": {"producer_owned": {"status": "computed"}},
    }

    class FakeClient:
        job_id = "job-ui"
        access_token = "token"
        last_status = {"artifact_states": {"evidence_bundle.zip": {"state": "ready"}}}
        last_request_spec = {
            "purpose": "garantia imobiliária",
            "candidate_cols": ["area", "id", "endereco", "lat", "lon", "fonte"],
            "roles": {"area": "predictor", "id": "identifier", "preco": "target"},
        }

        def documents(self, action="", method="GET", **kwargs):
            if method == "POST":
                st.session_state["document_post"] = kwargs.get("json")
            return {"state": {"case_release_status": "pending"}, "artifacts": []}

        def get_artifact(self, name, *args):
            if name == "report_context.json":
                return json.dumps(CONTEXT, ensure_ascii=False).encode()
            return b"artifact"

        def get_result(self, *args):
            return {"job_id": self.job_id}

    render_document_workflow(FakeClient(), {"provenance": {"qualification_context": {
        "profile": {"id": "bb-meci-avaliacao-imovel-pf", "version": "0.3.0"}
    }}})
    '''
)


def test_real_upload_fields_build_request_spec_and_keep_metadata_out_of_predictors():
    at = AppTest.from_string(UPLOAD_APP, default_timeout=30).run()
    assert not at.exception
    at.file_uploader(key="p02_uploader").set_value(
        ("mercado.csv", b"id;area;preco;endereco;latitude;longitude;fonte\n", "text/csv")
    )
    at.run()
    assert not at.exception

    _select_sample_mapping(at)
    _by_label(at.text_input, "Objetivo da avaliação").input("determinar valor de mercado para compra e venda")
    _by_label(at.text_area, "Diagnóstico de mercado").input("oferta regular e liquidez média")
    _by_label(at.text_area, "Justificativa para adoção do Grau I").input("amostra restrita, declarada pelo responsável")
    _by_label(at.text_area, "Observações do laudo").input("intervalo admissível sujeito à revisão")
    _by_label(at.text_input, "Critério de enquadramento — area").input("área privativa em m²")
    _by_label(at.text_input, "Codificação ou escala — area").input("numérica contínua")
    _by_label(at.text_input, "Latitude do avaliando (graus decimais)").input("-23,5505")
    _by_label(at.text_input, "Longitude do avaliando (graus decimais)").input("-46,6333")
    _by_label(at.text_input, "Endereço completo do avaliando").input("Praça da Sé, São Paulo - SP")
    _by_label(at.text_input, "Fonte da localização do avaliando").input("vistoria do responsável")
    at.run()
    assert not at.exception

    spec = at.session_state["captured_request_spec"]
    context = spec["report_context"]
    assert context["objective"] == "determinar valor de mercado para compra e venda"
    assert context["market_diagnosis"] == "oferta regular e liquidez média"
    assert context["variable_classification"] == {
        "area": {"criterion": "área privativa em m²", "coding": "numérica contínua"}
    }
    assert context["subject"]["geolocation"]["latitude"] == -23.5505
    assert context["sample_evidence_columns"] == {
        "address": "endereco", "latitude": "latitude", "longitude": "longitude", "source": "fonte"
    }
    assert set(context["sample_evidence_columns"].values()).isdisjoint(spec["candidate_cols"])
    assert all(spec["roles"][name] == "source" for name in context["sample_evidence_columns"].values())
    assert context["objective"] != spec["purpose"]


def test_invalid_subject_coordinates_block_the_real_execute_control():
    at = AppTest.from_string(UPLOAD_APP, default_timeout=30).run()
    at.file_uploader(key="p02_uploader").set_value(
        ("mercado.csv", b"id;area;preco\n", "text/csv")
    )
    at.run()
    _by_label(at.text_input, "Latitude do avaliando (graus decimais)").input("-91")
    _by_label(at.text_input, "Longitude do avaliando (graus decimais)").input("-46")
    _by_label(at.text_input, "Endereço completo do avaliando").input("Rua A")
    _by_label(at.text_input, "Fonte da localização do avaliando").input("vistoria")
    _by_label(at.button, "Executar avaliação").click()
    at.run()
    assert not at.exception
    dispatch = at.session_state["captured_dispatch"]
    assert dispatch["ok"] is False
    assert any("latitude deve estar entre -90 e 90" in item["message"] for item in dispatch["blocking"])
    assert at.session_state["captured_execute"] is True
    assert any("latitude deve estar entre -90 e 90" in error.value for error in at.error)


@pytest.mark.parametrize(
    ("latitude", "expected"),
    [
        ("True", "latitude deve ser um número"),
        ("91", "latitude deve estar entre -90 e 90 graus"),
    ],
)
def test_mapped_preview_rejects_invalid_coordinate_before_execute(latitude, expected):
    broken = UPLOAD_APP.replace(
        '"endereco": "Rua A", "latitude": -23.5,',
        f'"endereco": "Rua A", "latitude": {latitude},',
    )
    at = AppTest.from_string(broken, default_timeout=30).run()
    at.file_uploader(key="p02_uploader").set_value(
        ("mercado.csv", b"id;area;preco;endereco;latitude;longitude;fonte\n", "text/csv")
    )
    at.run()
    _select_sample_mapping(at)
    _by_label(at.button, "Executar avaliação").click()
    at.run()

    assert not at.exception
    assert at.session_state["captured_execute"] is True
    blocking = at.session_state["captured_dispatch"]["blocking"]
    assert any(
        f"Amostra R000000 (colunas associadas): {expected}" in item["message"]
        for item in blocking
    )


def test_mapped_preview_accepts_zero_coordinates():
    zero = UPLOAD_APP.replace(
        '"endereco": "Rua A", "latitude": -23.5, "longitude": -46.6,',
        '"endereco": "Rua A", "latitude": 0, "longitude": 0,',
    )
    at = AppTest.from_string(zero, default_timeout=30).run()
    at.file_uploader(key="p02_uploader").set_value(
        ("mercado.csv", b"id;area;preco;endereco;latitude;longitude;fonte\n", "text/csv")
    )
    at.run()
    _select_sample_mapping(at)
    at.run()

    assert not at.exception
    assert not any("colunas associadas" in error.value for error in at.error)
    context = at.session_state["captured_request_spec"]["report_context"]
    assert context["sample_evidence_columns"]["latitude"] == "latitude"


def test_reopened_document_fields_preserve_structures_and_post_native_edits():
    at = AppTest.from_string(DOCUMENT_APP, default_timeout=30).run()
    assert not at.exception
    assert not any("{'matricula'" in area.value for area in at.text_area)
    sample_table = at.dataframe(key="documents_job-ui_report_sample_evidence_table").value
    assert sample_table.to_dict(orient="records")[0] == {
        "row_id": "R000000",
        "address": "Rua B, 20",
        "latitude": "-23.6",
        "longitude": "-46.7",
        "source": "anúncio",
        "justification": "",
    }
    assert _by_label(at.text_area, "Observações do laudo").value == (
        "faixa admissível registrada\nrevisão necessária"
    )
    _by_label(at.text_area, "Diagnóstico de mercado").input("mercado aquecido, revisão de setembro")
    _by_label(at.button, "Gerar PDF, DOCX e dossiê").click()
    at.run()
    assert not at.exception

    posted = at.session_state["document_post"]["report_context"]
    assert posted["market_diagnosis"] == "mercado aquecido, revisão de setembro"
    assert posted["observations"] == ["faixa admissível registrada", "revisão necessária"]
    assert posted["variable_classification"] == {
        "area": {"criterion": "área privativa", "coding": {"m2": "contínua"}}
    }
    assert posted["subject"]["area"] == "73,5"
    assert posted["subject"]["geolocation"]["longitude"] == -46.6
    assert posted["sample_evidence"]["R000000"]["latitude"] == -23.6
    assert "output_evidence" not in posted
    assert "id" not in posted["variable_classification"]


def test_invalid_reopened_sample_coordinates_prevent_document_post():
    broken = DOCUMENT_APP.replace(
        '"address": "Rua B, 20", "latitude": -23.6,',
        '"address": "Rua B, 20", "latitude": "sul",',
    )
    at = AppTest.from_string(broken, default_timeout=30).run()
    assert not at.exception
    _by_label(at.button, "Gerar PDF, DOCX e dossiê").click()
    at.run()
    assert not at.exception
    assert "document_post" not in at.session_state.filtered_state
    errors = "\n".join(error.value for error in at.error)
    assert "Amostra R000000: latitude deve ser um número" in errors
    assert "Corrija os campos do laudo" in errors


def test_reopened_mapping_blocks_column_that_is_no_longer_materialized():
    stale = DOCUMENT_APP.replace(', "fonte": "anúncio",', ",")
    at = AppTest.from_string(stale, default_timeout=30).run()
    assert not at.exception
    _by_label(at.button, "Gerar PDF, DOCX e dossiê").click()
    at.run()

    assert not at.exception
    assert "document_post" not in at.session_state.filtered_state
    errors = "\n".join(error.value for error in at.error)
    assert "source → fonte" in errors
    assert "não estão disponíveis nos dados reabertos" in errors


def test_real_report_context_reopens_all_canonical_rows_and_explicit_zero_override():
    base = {
        "used_rows": [
            {
                "row_id": f"R{index:06d}",
                "values": {"id": f"CSV-{900 + index}"},
                "geolocation": {
                    "address": f"Rua materializada, {index}",
                    "latitude": -23.0 - index / 100,
                    "longitude": -46.0 - index / 100,
                    "source": "planilha",
                    "complete": True,
                    "issues": [],
                },
            }
            for index in range(10)
        ],
        "excluded_rows": [],
        "sample_evidence": {
            "R000009": {
                "address": "Meridiano de Greenwich",
                "latitude": 0,
                "longitude": 0,
                "source": "vistoria",
            }
        },
    }
    context = complete_report_context(base, request_spec={}, snapshot={})

    rows = _document_sample_rows(context)
    seed = _sample_evidence_seed(rows, context)

    assert [row["row_id"] for row in seed] == [f"R{index:06d}" for index in range(10)]
    assert all(row["row_id"] != f"CSV-{900 + index}" for index, row in enumerate(seed))
    assert seed[0]["address"] == "Rua materializada, 0"
    assert seed[9] == {
        "row_id": "R000009",
        "address": "Meridiano de Greenwich",
        "latitude": "0",
        "longitude": "0",
        "source": "vistoria",
        "justification": "",
    }
