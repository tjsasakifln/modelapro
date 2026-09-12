"""Synthetic C03 contract examples; never client or institutional evidence."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Tuple

from tests.c08_report.fixtures import (
    known_context,
    known_snapshot,
    long_table_context,
    long_table_snapshot,
)

SYNTHETIC = "SYNTHETIC_MP_COM_C03_NOT_REAL_CASE"


def qualification_context(
    *, release: str = "ready_for_professional_signoff", rule_status: str = "passed"
) -> Dict[str, Any]:
    return {
        "schema_version": "MP-QUAL/1",
        "resolved_profile": {
            "id": "urban-market-regression",
            "version": "2026.09-test",
            "source_set_sha256": "1" * 64,
            "purpose": "garantia imobiliária — fixture sintética",
            "value_basis": "market_value",
            "method": "direct_market_comparison_regression",
            "asset_scope": "urban_residential_property",
            "recipient_id": "neutral-institution-test",
        },
        "result_fingerprint": "2" * 64,
        "calculation_status": "valid",
        "grade_requirement_status": "met",
        "case_release_status": release,
        "rule_results": [
            {
                "rule_id": "TEST-RULE-01",
                "source_id": "legitimate-source-index-test",
                "edition_or_version": "2026-test",
                "clause": "fixture-clause-1",
                "applicability": "applicable",
                "status": rule_status,
                "observed": {"grade": 2},
                "criterion_ref": "validation.fundamentacao.grade",
                "evidence_refs": ["snapshot:validation.fundamentacao"],
                "explanation": "Regra sintética para teste do contrato; não é texto normativo.",
            }
        ],
        "review_events": [
            {
                "fingerprint": "2" * 64,
                "decision": "approved",
                "professional_id": "professional-test-001",
                "motive": "Conferência controlada da fixture sintética.",
                "version": "rev-test-001",
                "stale": False,
            }
        ],
        "institution_acceptance": {"status": "not_recorded"},
        "synthetic": True,
        "label": SYNTHETIC,
    }


def qualified_case(*, long: bool = False) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    snapshot = deepcopy(long_table_snapshot() if long else known_snapshot())
    context = deepcopy(long_table_context() if long else known_context())
    snapshot.setdefault("provenance", {})["qualification_context"] = (
        qualification_context()
    )
    snapshot["value"]["adopted_value"] = {
        "point": snapshot["value"]["point"],
        "policy_ref": "fixture-policy:adopt-point",
    }
    context.update(
        {
            "asset_identification": {
                "matricula": "SYNTH-001",
                "municipio": "Cidade Sintética",
            },
            "rights": "domínio pleno — fixture sintética",
            "region_characterization": "Região urbana sintética com infraestrutura declarada na fixture.",
            "property_characterization": "Imóvel residencial urbano sintético.",
            "methodology_justification": "Comparativo direto por regressão para valor de mercado.",
            "assumptions": ["Dados e revisão são inteiramente sintéticos."],
            "synthetic": True,
            "synthetic_label": SYNTHETIC,
        }
    )
    from modules.report_presenter.qualification import report_content_fingerprint

    snapshot["provenance"]["qualification_context"]["review_events"][0][
        "report_content_fingerprint"
    ] = report_content_fingerprint(snapshot, context)
    return snapshot, context
