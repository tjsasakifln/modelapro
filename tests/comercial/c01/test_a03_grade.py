"""C01-A03: grade request preserved; fitted analysis is not NO_WINNER."""

from __future__ import annotations

import pytest

from backend.worker import CompositionError, compose_valuation_job, resolve_peers
from modules.optimal_combination import search_models
from modules.result_contract import RequestSpecError, validate_request_spec
from tests.c05_search.helpers import make_prepared, request_spec
from tests.comercial.c01.conftest import gold_csv_bytes, gold_spec, gold_subject
from tests.pro_workflow.p01.conftest import documented_identity_ols_frame
from tests.pro_workflow.p01.test_a01_ols_oracle import _prepared


def test_grade_alias_conflict_is_structured_error():
    spec = gold_spec()
    spec["search_policy"] = dict(spec["search_policy"])
    spec["search_policy"]["minimum_fundamentacao_grade"] = 2
    spec["search_policy"]["target_degree"] = 3
    with pytest.raises(RequestSpecError) as exc:
        validate_request_spec(spec)
    codes = {i.get("code") for i in exc.value.issues}
    assert "GRADE_ALIAS_CONFLICT" in codes


def test_fitted_but_grade_not_met_is_analysis_not_no_winner(isolated_c01_runtime):
    store = isolated_c01_runtime["job_store"]
    created = store.create(payload={"filename": "gold.csv"})
    spec = gold_spec()
    spec["search_policy"] = dict(spec["search_policy"])
    spec["search_policy"]["minimum_fundamentacao_grade"] = 3
    spec["evaluation_policy"] = dict(spec["evaluation_policy"])
    spec["evaluation_policy"]["minimum_fundamentacao_grade"] = 3
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
    codes = {i.get("code") for i in snap.get("issues") or []}
    assert "NO_WINNER" not in codes
    assert snap["value"]["point"] is not None
    wf = (snap.get("provenance") or {}).get("workflow_context") or {}
    assert wf.get("requested_minimum_grade") == 3
    assert wf.get("grade_requirement_status") in {"not_met", "pending"}
    qc = (snap.get("provenance") or {}).get("qualification_context") or {}
    assert qc.get("schema_version") == "MP-QUAL/1"
    assert qc.get("grade_requirement_status") in {"not_met", "pending"}
    assert qc.get("case_release_status") in {"analysis_only", "review_required"}
    assert qc.get("case_release_status") != "ready_for_professional_signoff"
    assert qc.get("calculation_status") == "fitted"
    issuance = (snap.get("validation") or {}).get("issuance") or {}
    assert issuance.get("status") != "ready_for_professional_review" or qc.get("grade_requirement_status") == "met"


def test_search_returns_numeric_winner_when_grade_fails():
    frame = documented_identity_ols_frame()
    prepared = _prepared(frame)
    spec = request_spec(
        "preco",
        candidate_cols=["area", "bairro_Sul"],
        search_policy={"mode": "exact", "budget": 32, "use_cache": False, "y_transformations": ["identity"]},
        evaluation_policy={"minimum_fundamentacao_grade": 3},
    )
    # prepared target column is preco in p01 helper? _prepared uses preco as y name
    prepared = dict(prepared)
    result = search_models(prepared, None, {**spec, "target_col": "preco"})
    assert result["winner"] is not None
    assert result["winner"]["status"] == "fitted"
    adm = result["winner"]["admissibility"]
    assert adm["numeric_technical"] is True
    codes = {i.get("code") for i in result.get("issues") or []}
    assert "NO_WINNER" not in codes


def test_reachable_grade_has_professional_review_path(isolated_c01_runtime):
    store = isolated_c01_runtime["job_store"]
    created = store.create(payload={"filename": "gold.csv"})
    spec = gold_spec()
    spec["search_policy"] = dict(spec["search_policy"])
    spec["search_policy"]["minimum_fundamentacao_grade"] = 1
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
    wf = (snap.get("provenance") or {}).get("workflow_context") or {}
    qc = (snap.get("provenance") or {}).get("qualification_context") or {}
    assert wf.get("requested_minimum_grade") == 1
    assert wf.get("grade_requirement_status") in {"met", "pending"}
    assert qc.get("case_release_status") in {
        "review_required",
        "ready_for_professional_signoff",
    }
    assert qc.get("case_release_status") != "analysis_only"
    assert snap["value"]["point"] is not None
    assert "NO_WINNER" not in {i.get("code") for i in snap.get("issues") or []}


def test_corrupted_input_is_error_not_warning_pass(isolated_c01_runtime):
    store = isolated_c01_runtime["job_store"]
    created = store.create(payload={"filename": "bad.txt"})
    spec = gold_spec()
    with pytest.raises(CompositionError) as exc:
        compose_valuation_job(
            job_id=created["job_id"],
            file_bytes=b"this is not a table",
            filename="notes.txt",
            request_spec=spec,
            subject_raw=gold_subject(),
            project_id=None,
            peers=resolve_peers(),
            job_store=store,
        )
    codes = {i.get("code") for i in exc.value.issues}
    assert "unsupported_format" in codes or "csv_parse_error" in codes or "empty_file" in codes
    assert "NO_WINNER" not in codes
