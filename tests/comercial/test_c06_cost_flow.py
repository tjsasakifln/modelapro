"""C06 real cost route. All monetary/source data are synthetic TEST fixtures."""
from __future__ import annotations

import copy
import io
import json
import math
import zipfile

import pytest

from backend.worker import compose_valuation_job, resolve_peers
from modules.cost_valuation import compute_reconstruction_cost
from modules.job_store import JobStore
from modules.qualification_profile import resolve_profile
from modules.report_export.workflow import (
    create_signature_request,
    generate_documents,
    import_signed_report,
    record_review,
    store_document_attachment,
)
from modules.result_contract import RequestSpecError, validate_request_spec
from modules.results_generator import build_report_view
from tests.comercial.c01.conftest import gold_spec


def _bom() -> dict:
    return {
        "schema_version": "MP-COST-BOM/1",
        "reference_location": "TESTE-Cidade-X",
        "reference_date": "2026-09-12",
        "currency": "BRL",
        "direct_cost": {
            "mode": "synthetic_budget",
            "source": {"reference": "ORCAMENTO-SINTETICO-TESTE", "synthetic_test_only": True},
        },
        "items": [
            {"item_id": "estrutura", "description": "Estrutura TESTE", "category": "building_component",
             "quantity": 10, "unit": "m2", "unit_cost": 100, "currency": "BRL",
             "reference_date": "2026-09-12", "source": "COMPOSICAO-TESTE-01"},
            {"item_id": "terreno", "description": "Terreno TESTE", "category": "land",
             "quantity": 1, "unit": "lote", "unit_cost": 500, "currency": "BRL",
             "reference_date": "2026-09-12", "source": "TERRENO-TESTE", "include_land": True},
        ],
        "bdi": {"mode": "calculated", "rate": 0.15,
                "components": {"administracao": 0.10, "risco": 0.05},
                "formula": "additive", "source": "MEMORIA-BDI-TESTE"},
        "depreciation": {"mode": "technical_method", "rate": 0.20,
                         "method": "METODO-TECNICO-TESTE", "age": 10,
                         "useful_life": 50, "condition": "regular",
                         "source": "VISTORIA-SINTETICA-TESTE"},
    }


def _cost_spec() -> dict:
    resolved = resolve_profile({"id": "abnt-14653-2-custo-reedicao", "version": "0.2.0"})
    profile = {key: resolved.get(key) for key in (
        "id", "version", "source_set_sha256", "purpose", "value_basis", "method", "asset_scope"
    )}
    spec = gold_spec()
    spec.update({
        "target_col": "", "candidate_cols": [], "roles": {}, "units": {},
        "target_unit": "BRL", "reference_date": "2026-09-12",
        "inspection_date": "2026-09-10", "purpose": "TESTE custo de reedição",
        "qualification_profile": profile, "cost_bom": _bom(),
        "report_context": {
            "synthetic_test_only": True,
            "asset_identification": {"id": "BEM-CUSTO-TESTE"},
            "rights": "TESTE: benfeitoria segurável sintética",
            "region_characterization": "TESTE: região sintética",
            "property_characterization": "TESTE: benfeitoria sintética",
            "methodology_justification": "TESTE: quantificação por orçamento sintético",
            "assumptions": ["TESTE: sem validade externa"],
        },
    })
    return validate_request_spec(spec)


def test_sum_bdi_depreciation_land_and_tabela6_are_replayable():
    result = compute_reconstruction_cost(_bom(), market_point=999999,
                                         value_basis="depreciated_cost", include_depreciation=True)
    assert result["computable"] is True
    assert result["memory"] == {
        "direct_subtotal": 1000.0, "bdi_rate": 0.15, "bdi_amount": 150.0,
        "reproduction_building": 1150.0, "depreciation_rate": 0.2,
        "depreciation_amount": 230.0, "depreciated_building": 920.0,
        "land_subtotal": 500.0, "total": 1420.0,
        "formula": "direct + BDI - physical depreciation + explicitly included land",
        "automatic_currency_or_date_adjustment": False,
    }
    assert result["value"]["point"] == 1420.0
    assert result["market_point_ignored"] == 999999.0
    assert result["used_market_factor"] is False
    assert [item["grade"] for item in result["fundamentacao"]["items"]] == [3, 3, 2]
    assert result["fundamentacao"]["grade"] == 3


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda b: b.update(schema_version="MP-COST-BOM/999"), "cost_bom_schema_invalid"),
        (lambda b: b["items"][0].update(category="mystery"), "cost_category_unknown"),
        (lambda b: b["items"][0].update(quantity=-1), "cost_item_amount_invalid"),
        (lambda b: b["items"][0].update(unit_cost=math.inf), "cost_item_amount_invalid"),
        (lambda b: b["items"][0].update(currency="USD"), "cost_currency_mismatch"),
        (lambda b: b["items"][0].update(reference_date="2025-01-01"), "cost_reference_date_mismatch"),
        (lambda b: b["items"][0].update(location="Outra cidade"), "cost_reference_location_mismatch"),
        (lambda b: b["items"][0].pop("source"), "cost_item_source_missing"),
        (lambda b: b.update(items=[]), "cost_items_missing"),
        (lambda b: b["bdi"].update(rate=0.10), "bdi_rate_mismatch"),
        (lambda b: b["depreciation"].update(rate=None), "depreciation_invalid"),
    ],
)
def test_material_invalid_inputs_never_fall_back_to_gross_cost(mutate, code):
    bom = _bom(); mutate(bom)
    result = compute_reconstruction_cost(bom, value_basis="depreciated_cost", include_depreciation=True)
    assert result["computable"] is False
    assert result["value"]["point"] is None
    assert code in {item["code"] for item in result["issues"]}


def test_zero_is_distinct_from_missing_and_client_grade_is_ignored():
    bom = _bom()
    bom["bdi"] = {"mode": "calculated", "rate": 0, "components": {"risco": 0}, "source": "BDI-ZERO-TESTE", "grade": 1}
    bom["depreciation"] = {"mode": "new_asset", "rate": 0, "source": "BEM-NOVO-TESTE", "grade": 1}
    result = compute_reconstruction_cost(bom, value_basis="depreciated_cost", include_depreciation=True)
    assert result["computable"] is True
    assert result["memory"]["bdi_rate"] == 0
    assert result["memory"]["depreciation_rate"] == 0
    assert [item["grade"] for item in result["fundamentacao"]["items"]] == [3, 3, 3]
    bom["depreciation"] = None
    missing = compute_reconstruction_cost(bom, value_basis="depreciated_cost", include_depreciation=True)
    assert missing["computable"] is False and missing["value"]["point"] is None


def test_contract_allows_empty_market_shape_only_for_resolved_cost_identity():
    spec = _cost_spec()
    assert spec["target_col"] == "" and spec["candidate_cols"] == []
    not_cost = copy.deepcopy(spec)
    not_cost["qualification_profile"]["method"] = "metodo_comparativo_direto_de_dados_de_mercado"
    with pytest.raises(RequestSpecError):
        validate_request_spec(not_cost)


def test_worker_cost_route_does_not_call_market_peers_and_preserves_honest_review_boundary(tmp_path):
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("market/regression peer must not run for a cost BOM")
    forbidden.contract_simulator = True
    forbidden.simulator_label = "TESTE fail if market peer runs"
    peers = resolve_peers()
    for name in ("ingest_market", "fit_dataset", "transform_subject", "search_models", "assess_normative", "evaluate_procedure"):
        peers[name] = forbidden
    store = JobStore(tmp_path / "cost-store")
    spec = _cost_spec()
    created = store.create(payload={"filename": "cost-bom.json", "request_spec": spec})
    ctx = compose_valuation_job(
        job_id=created["job_id"], file_bytes=b"", filename="cost-bom.json",
        request_spec=spec, subject_raw=None, project_id=None,
        peers=peers, job_store=store,
    )
    assert calls == []
    snap = ctx["snapshot"]
    assert snap["sample"]["received"] == snap["sample"]["used"] == 0
    assert snap["value"]["point"] == 1420.0
    assert snap["provenance"]["cost_result"]["memory"]["total"] == snap["value"]["point"]
    qc = snap["provenance"]["qualification_context"]
    assert qc["calculation_status"] == "ok"
    assert qc["achieved_fundamentacao_grade"] == 3
    by_rule = {item["rule_id"]: item["status"] for item in qc["rule_results"]}
    assert by_rule["tabela6_7.custo.enquadramento"] == "passed"
    assert by_rule["metodos.custo.calculo"] == "passed"
    assert qc["profile"]["state"] == "verified"
    assert qc["case_release_status"] in {"review_required", "analysis_only"}
    assert "profile_not_verified" not in {b["code"] for b in qc["release_blockers"]}
    assert ctx["report_context"]["cost_memory"]["total"] == 1420.0
    assert store.get_artifact(created["job_id"], "report.pdf").startswith(b"%PDF")
    assert ctx["frozen_project"]["model_state"]["cost_result"]["memory"]["total"] == 1420.0
    view = build_report_view(snap, ctx["report_context"])
    assert view["cost_route"] is True
    assert {row["key"]: row["raw"] for row in view["cost_memory_rows"]}["total"] == "1420"
    bundle = store.get_artifact(created["job_id"], "evidence_bundle.zip")
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert {"snapshot/result_snapshot.json", "calculation/cost_bom.json",
                "calculation/cost_result.json", "documents/report.pdf", "MANIFEST.json"} <= set(archive.namelist())
        replay = json.loads(archive.read("calculation/cost_result.json"))
        assert replay["memory"]["total"] == snap["value"]["point"]
    store_document_attachment(
        store, created["job_id"], filename="memoria-custo-TESTE.txt", media_type="text/plain",
        content=b"TESTE: memoria documental sintetica", source="ORCAMENTO-SINTETICO-TESTE",
        authorized_for_report=True, category="document", synthetic_test_only=True,
        requirement_ids=["9.3.1.laudo_completo"],
    )
    generated = generate_documents(store, created["job_id"])
    assert generated["case_release_status"] == "review_required"
    assert store.get_artifact(created["job_id"], "report.docx").startswith(b"PK")
    reviewed = record_review(
        store, created["job_id"], professional_id="CREA-TESTE-000",
        professional_name="PROFISSIONAL TESTE", motive="TESTE: revisão sem validade externa",
        version="CUSTO-TESTE-1", synthetic_test_only=True,
    )
    assert reviewed["case_release_status"] == "ready_for_professional_signoff"
    signature_request = create_signature_request(store, created["job_id"], revision_id="CUSTO-TESTE-1")
    assert signature_request["profile_id"] == "abnt-14653-2-custo-reedicao"
    assert signature_request["unsigned_pdf_sha256"]
    from tests.comercial.test_c06_document_flow import _sign_with_test_certificate
    unsigned = store.get_artifact(created["job_id"], "report.pdf")
    from pypdf import PdfReader
    pdf_text = "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(unsigned)).pages)
    assert "Método da quantificação de custo" in pdf_text
    assert "Método Comparativo Direto de Dados de Mercado" not in pdf_text
    signed, validation_context = _sign_with_test_certificate(unsigned)
    imported = import_signed_report(
        store, created["job_id"], signed_pdf=signed,
        validation_context=validation_context,
    )
    assert imported["document_state"]["case_release_status"] == "signed_integrity_verified"
    assert imported["signature"]["revision_id"] == "CUSTO-TESTE-1"
    assert store.get_artifact(created["job_id"], "submission.zip")
    history = store.get_artifact(created["job_id"], "document_history.zip")
    with zipfile.ZipFile(io.BytesIO(history)) as archive:
        assert any(name.endswith("/report.pdf") for name in archive.namelist())
