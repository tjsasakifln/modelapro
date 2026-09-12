"""Cost reports do not fabricate a statistical precision classification."""

from __future__ import annotations

from modules.results_generator import build_report_view
from tests.comercial.c03.fixtures import qualified_case


def test_explicit_cost_route_marks_statistical_precision_as_not_applicable():
    snapshot, context = qualified_case()
    snapshot["validation"]["precisao"] = {
        "status": "not_computed",
        "grade": None,
        "reason": "not_applicable_to_cost_quantification",
    }
    snapshot["validation"]["statistical"] = {
        "route": "cost_quantification",
        "market_sample_applicable": False,
        "precision_grade_applicable": False,
    }

    view = build_report_view(snapshot, context)

    assert view["precisao_status"] == "not_applicable_cost_quantification"
    assert view["precisao_status_label"] == "Não aplicável à quantificação de custo"
    assert view["grau_precisao_label"] == "Não aplicável à quantificação de custo"
    assert view["precisao_grade"] is None


def test_market_route_without_precision_remains_not_computed():
    snapshot, context = qualified_case()
    snapshot["validation"]["precisao"] = {"status": "not_computed", "grade": None}

    view = build_report_view(snapshot, context)

    assert view["precisao_status"] == "not_computed"
    assert view["precisao_status_label"] == "Precisão não calculada"
    assert view["grau_precisao_label"] == "Não calculado"


def test_automatic_approval_warning_uses_neutral_document_subject():
    snapshot, context = qualified_case()
    snapshot["validation"]["issuance"]["reasons"] = [
        "no_automatic_report_approval"
    ]

    view = build_report_view(snapshot, context)

    assert "Este documento não constitui aprovação automática de laudo." in view[
        "issuance_reasons"
    ]
    assert all("Esta minuta" not in reason for reason in view["issuance_reasons"])
