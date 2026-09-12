"""C01-A06: reconstruction cost is a BOM sum, not k × market."""

from __future__ import annotations

from modules.cost_valuation import compute_reconstruction_cost
from modules.result_contract import validate_request_spec
from modules.qualification_profile import resolve_profile
from backend.worker import compose_valuation_job, resolve_peers
from tests.comercial.c01.conftest import gold_csv_bytes, gold_spec, gold_subject


SYNTHETIC_BOM = {
    "reference_location": "SYNTHETIC-Cidade-X",
    "reference_date": "2024-06-01",
    "currency": "BRL",
    "items": [
        {
            "item_id": "walls",
            "description": "Alvenaria sintetica",
            "quantity": 80.0,
            "unit": "m2",
            "unit_cost": 450.0,
            "origin": "synthetic-schedule-c01",
            "category": "building_component",
        },
        {
            "item_id": "roof",
            "description": "Cobertura sintetica",
            "quantity": 80.0,
            "unit": "m2",
            "unit_cost": 220.0,
            "origin": "synthetic-schedule-c01",
            "category": "building_component",
        },
        {
            "item_id": "fees",
            "description": "Despesas adicionais",
            "quantity": 1.0,
            "unit": "un",
            "unit_cost": 8000.0,
            "origin": "synthetic-schedule-c01",
            "category": "additional_expense",
        },
        {
            "item_id": "land",
            "description": "Terreno (nao entra sem flag)",
            "quantity": 1.0,
            "unit": "lote",
            "unit_cost": 200000.0,
            "origin": "synthetic-schedule-c01",
            "category": "land",
        },
        {
            "item_id": "personal",
            "description": "Bens nao cobertos",
            "quantity": 1.0,
            "unit": "un",
            "unit_cost": 5000.0,
            "origin": "synthetic-schedule-c01",
            "category": "exclusion",
            "reason": "not_covered",
        },
    ],
}


def test_bom_sum_excludes_implicit_land_and_is_not_market_factor():
    market = 456108.03
    result = compute_reconstruction_cost(SYNTHETIC_BOM, market_point=market)
    assert result["computable"] is True
    point = result["value"]["point"]
    assert point == 80 * 450 + 80 * 220 + 8000
    assert point == 61600.0
    assert result["land_included"] is True
    assert not any(i["item_id"] == "land" for i in result["items"])
    assert any(e["item_id"] == "land" for e in result["exclusions"])
    assert result["value"]["basis"] == "reconstruction_cost"
    for k in (0.5, 0.7, 0.8, 1.0, 1.2, 1.5, 2.0):
        assert abs(point - market * k) > 1.0
    assert result["used_market_factor"] is False


def test_missing_bom_blocks_insurance_profile_but_allows_analysis(isolated_c01_runtime):
    store = isolated_c01_runtime["job_store"]
    created = store.create(payload={"filename": "gold.csv"})
    spec = gold_spec()
    resolved = resolve_profile({"id": "abnt-14653-2-custo-reedicao", "version": "0.1.0"})
    spec["qualification_profile"] = {
        key: resolved.get(key)
        for key in (
            "id", "version", "source_set_sha256", "purpose", "value_basis",
            "method", "asset_scope",
        )
    }
    spec = validate_request_spec(spec)
    ctx = compose_valuation_job(
        job_id=created["job_id"],
        file_bytes=gold_csv_bytes(),
        filename="gold.csv",
        request_spec=spec,
        subject_raw=gold_subject(),
        project_id=None,
        peers=resolve_peers(),
        job_store=store,
    )
    snap = ctx["snapshot"]
    qc = (snap.get("provenance") or {}).get("qualification_context") or {}
    assert snap["value"]["point"] is None or snap["value"].get("basis") == "reconstruction_cost"
    assert qc.get("case_release_status") != "ready_for_professional_signoff"
    assert qc.get("case_release_status") == "analysis_only"
    assert "profile_not_verified" in {
        blocker.get("code") for blocker in qc.get("release_blockers") or []
    }
    assert qc["profile"]["id"] == "abnt-14653-2-custo-reedicao"


def test_explicit_land_only_when_flagged():
    bom = dict(SYNTHETIC_BOM)
    items = [dict(i) for i in bom["items"]]
    for item in items:
        if item["item_id"] == "land":
            item["include_land"] = True
    bom["items"] = items
    result = compute_reconstruction_cost(bom)
    assert any(i["item_id"] == "land" for i in result["items"])
    assert result["value"]["point"] == 61600.0 + 200000.0
