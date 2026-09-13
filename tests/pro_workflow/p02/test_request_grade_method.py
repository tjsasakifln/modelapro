"""P02-A02: pedido canônico de grau/método; pending ≠ atingido; validação não pedida ≠ erro."""

from frontend.components.forms import build_request_spec, request_spec_json
from frontend.components.layout import present_snapshot
from frontend.components.workflow import (
    CANONICAL_GRADE_KEY,
    cost_estimate_from_payload,
    policies_on_the_wire,
    present_grade_requirement,
    present_validation_execution,
    request_grade_keys,
)
from tests.c09_frontend.fixtures import SNAPSHOT_CLASSIFIED, SNAPSHOT_NOT_COMPUTED


def _spec(**kwargs):
    base = dict(
        target_col="preco",
        candidate_cols=["area", "bairro"],
        roles={"preco": "target", "area": "predictor", "bairro": "predictor"},
        target_unit="BRL",
        reference_date="2024-01-15",
    )
    base.update(kwargs)
    return build_request_spec(**base)


def test_canonical_grade_only_in_search_policy():
    spec = _spec(minimum_fundamentacao_grade=2, evaluation_method="holdout")
    keys = request_grade_keys(spec)
    assert keys["canonical"] == 2
    assert keys["canonical_only"] is True
    body = request_spec_json(spec)
    assert "minimum_fundamentacao_grade" in body
    assert "target_degree" not in body
    assert "min_fundamentacao_grade" not in body
    assert spec["evaluation_policy"]["method"] == "holdout"
    policies = policies_on_the_wire(spec)
    assert policies["minimum_fundamentacao_grade"] == 2
    assert policies["evaluation_method"] == "holdout"
    assert policies["validation_requested"] is True


def test_null_grade_is_not_requested_and_holdout_is_explicit():
    spec = _spec(minimum_fundamentacao_grade=None, evaluation_method="none")
    assert spec["search_policy"][CANONICAL_GRADE_KEY] is None
    assert spec["evaluation_policy"]["method"] == "none"
    view = present_grade_requirement(SNAPSHOT_NOT_COMPUTED, requested_minimum_grade=None)
    assert view["requested"] is None
    assert view["display_status"] == "not_requested"
    assert view["requested_shown_as_attained"] is False
    execution = present_validation_execution(SNAPSHOT_NOT_COMPUTED, spec)
    assert execution["requested"] is False
    assert execution["executed"] is False
    assert execution["not_an_error"] is True
    assert execution["not_zero"] is True
    assert "não executada" in execution["label"].lower()


def test_pending_grade_is_not_presented_as_met():
    snap = dict(SNAPSHOT_NOT_COMPUTED)
    snap["provenance"] = {
        "workflow_context": {
            "schema_version": "MP-PRO/1",
            "subject_raw": {"area": "73,5"},
            "requested_minimum_grade": 2,
            "grade_requirement_status": "pending",
            "selection_scope": "unknown",
            "selection_conditioned_on_subject": None,
            "limitation_codes": [],
        }
    }
    view = present_grade_requirement(snap, requested_minimum_grade=2)
    assert view["status"] == "pending"
    assert view["label"] != "Grau mínimo atingido"
    assert view["requested_shown_as_attained"] is False
    presented = present_snapshot(snap, request_spec=_spec(minimum_fundamentacao_grade=2))
    assert presented["grade_requirement"]["status"] == "pending"
    assert presented["grade_requirement"]["attained"] is None


def test_not_met_stays_distinct_from_pending_and_from_met():
    labels = {}
    for status in ("pending", "not_met", "met", "not_requested", "error"):
        snap = {
            **SNAPSHOT_CLASSIFIED,
            "provenance": {
                "workflow_context": {
                    "schema_version": "MP-PRO/1",
                    "grade_requirement_status": status,
                    "requested_minimum_grade": 2,
                    "subject_raw": {"area": 1},
                }
            },
        }
        labels[status] = present_grade_requirement(snap)["label"]
    assert len(set(labels.values())) == 5
    assert labels["pending"] != labels["not_met"]
    assert labels["not_requested"] != labels["met"]


def test_cost_is_absent_unless_payload_has_it():
    assert cost_estimate_from_payload(SNAPSHOT_CLASSIFIED) is None
    with_cost = {"search": {"audit": {"estimated_cost": {"candidates": 12}}}}
    shown = cost_estimate_from_payload(with_cost)
    assert shown is not None
    assert shown["value"]["candidates"] == 12
