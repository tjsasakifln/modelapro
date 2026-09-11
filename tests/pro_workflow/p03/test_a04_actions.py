"""P03-A04: workflow_context subject is recognized; unit/docs stay explicit; validation optional."""

from __future__ import annotations

from modules.decision_support import (
    CODE_CONSIDER_EXTERNAL_VALIDATION,
    CODE_DOCUMENT_SOURCE,
    CODE_PROVIDE_SUBJECT_CHARACTERISTIC,
    CODE_RESOLVE_UNIT_OR_PARSE,
    recommend_next_actions,
)
from tests.pro_workflow.p03.fixtures import feature_schema_area_quartos, old_mp1_snapshot, workflow_context_snapshot


def _codes(actions):
    return [a["code"] for a in actions]


def test_p03_a04_workflow_context_subject_does_not_ask_characteristics():
    snap = workflow_context_snapshot(with_unit=True, docs_pending=True)
    actions = recommend_next_actions(snap, feature_schema=feature_schema_area_quartos())
    for action in actions:
        assert set(action.keys()) >= {"code", "priority", "reason", "next_step", "evidence_refs", "limitations"}
    codes = _codes(actions)
    assert CODE_PROVIDE_SUBJECT_CHARACTERISTIC not in codes
    assert CODE_DOCUMENT_SOURCE in codes
    assert CODE_CONSIDER_EXTERNAL_VALIDATION in codes
    optional = next(a for a in actions if a["code"] == CODE_CONSIDER_EXTERNAL_VALIDATION)
    assert optional["priority"] >= 90
    assert "não é defeito" in optional["reason"].lower() or "nao e defeito" in optional["reason"].lower() or "não é defeito" in optional["reason"]
    assert "excluir" not in " ".join(optional["next_step"].lower() for _ in [0])


def test_p03_a04_missing_unit_and_docs_remain_explicit():
    snap = workflow_context_snapshot(with_unit=False, docs_pending=True)
    actions = recommend_next_actions(snap, feature_schema=feature_schema_area_quartos())
    codes = set(_codes(actions))
    assert CODE_RESOLVE_UNIT_OR_PARSE in codes
    assert CODE_DOCUMENT_SOURCE in codes
    assert CODE_PROVIDE_SUBJECT_CHARACTERISTIC not in codes


def test_p03_a04_old_snapshot_without_workflow_context_does_not_invent_subject():
    snap = old_mp1_snapshot()
    actions = recommend_next_actions(snap, feature_schema=feature_schema_area_quartos())
    # Missing workflow_context must not be treated as "subject present".
    # Item 1 is declared-only in the known snapshot — characteristics action may appear.
    codes = set(_codes(actions))
    assert CODE_CONSIDER_EXTERNAL_VALIDATION not in codes


def test_p03_a04_no_exclude_to_raise_r2():
    snap = workflow_context_snapshot()
    snap["issues"] = [
        {
            "code": "LOW_R2",
            "severity": "info",
            "origin": "evaluation",
            "message": "R² limitado",
            "affected_ids": ["r1"],
            "evidence": {"r2": 0.4},
        }
    ]
    actions = recommend_next_actions(snap)
    blob = " ".join(
        " ".join([a["reason"], a["next_step"], " ".join(a["limitations"])]) for a in actions
    ).lower()
    assert "aumentar o r²" in blob or "aumentar o r2" in blob or "r²" in blob
    assert "excluir dado apenas para aumentar" in blob
    assert not any("remove_to_raise" in a["code"] for a in actions)
