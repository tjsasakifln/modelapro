"""P01-A04: subject-conditioned selection vs true population_model."""

from __future__ import annotations

import numpy as np
import pandas as pd

from modules.optimal_combination import build_search_cache_key, search_models
from modules.search_space import search_units_from_prepared
from tests.c05_search.helpers import make_prepared, request_spec


def _idade_frame(n=24, seed=1):
    rng = np.random.RandomState(seed)
    idade = rng.uniform(1, 50, n)
    y = 100 - 2 * idade + rng.normal(0, 1, n)
    return pd.DataFrame({"idade": idade, "y": y})


def test_p01_a04_subject_invalid_transform_conditions_selection():
    prepared = make_prepared(_idade_frame(), "y")
    spec_subj = request_spec(
        "y",
        search_policy={"mode": "exact", "budget": 200, "model_scope": "subject_specific", "use_cache": False},
    )
    valid_subject = {"raw_values": {"idade": 10.0}, "X": None, "issues": [], "supported": True}
    invalid_subject = {"raw_values": {"idade": 0.0}, "X": None, "issues": [], "supported": True}
    a = search_models(prepared, valid_subject, spec_subj)
    b = search_models(prepared, invalid_subject, spec_subj)
    space_a = set(a["search_audit"].get("unit_ids") or [])
    hist_a = {v for e in a["search_audit"]["history"] for v in (e.get("variables") or [])}
    hist_b = {v for e in b["search_audit"]["history"] for v in (e.get("variables") or [])}
    assert a["search_audit"]["selection_conditioned_on_subject"] is True
    assert b["search_audit"]["selection_conditioned_on_subject"] is True
    assert any(v.startswith("ln(") for v in hist_a)
    assert not any(v.startswith("ln(") for v in hist_b)
    assert hist_a != hist_b


def test_p01_a04_population_model_space_independent_of_subject():
    prepared = make_prepared(_idade_frame(), "y")
    spec_pop = request_spec(
        "y",
        search_policy={"mode": "exact", "budget": 200, "model_scope": "population_model", "use_cache": False},
    )
    s1 = {"raw_values": {"idade": 10.0}, "X": None, "issues": [], "supported": True}
    s2 = {"raw_values": {"idade": 0.0}, "X": None, "issues": [], "supported": True}
    a = search_models(prepared, s1, spec_pop)
    b = search_models(prepared, s2, spec_pop)
    hist_a = sorted(
        {tuple(e.get("variables") or []) for e in a["search_audit"]["history"]}
    )
    hist_b = sorted(
        {tuple(e.get("variables") or []) for e in b["search_audit"]["history"]}
    )
    assert a["search_audit"]["selection_scope"] == "population_model"
    assert a["search_audit"]["selection_conditioned_on_subject"] is False
    assert hist_a == hist_b
    d1, c1 = build_search_cache_key(prepared, s1, spec_pop)
    d2, c2 = build_search_cache_key(prepared, s2, spec_pop)
    assert d1 == d2
    assert c1.get("subject") is None


def test_p01_a04_reuse_out_of_support_is_item_limitation_not_inherited_note():
    from modules.valuation_batch import builtin_evaluate_fitted, restore_candidate_fit
    from backend.worker import build_frozen_project
    from modules.model_builder import CandidateSpec, fit_candidate
    from tests.pro_workflow.p01.conftest import documented_request_spec
    from tests.pro_workflow.p01.test_a01_ols_oracle import _prepared
    from tests.pro_workflow.p01.conftest import documented_identity_ols_frame

    frame = documented_identity_ols_frame()
    prepared = _prepared(frame)
    spec = CandidateSpec(
        candidate_id="p01-a04",
        features=["area", "bairro_Sul"],
        base_variables=["area", "bairro"],
        feature_groups={"bairro": ["bairro_Sul"]},
        x_transformations={},
        intercept=True,
        y_transformation="identity",
    )
    req = documented_request_spec()
    req["search_policy"]["model_scope"] = "population_model"
    fit = fit_candidate(prepared, spec, req)
    frozen = build_frozen_project(
        project_id="p01-a04",
        revision_id="rev",
        request_spec=req,
        input_bundle={"input_sha256": "x", "raw_frame": frame},
        prepared_dataset=prepared,
        winner_fit=fit,
        subject_design={"subject_id": "orig", "raw_values": {"area": 90.0, "bairro": "Centro"}, "supported": True},
        normative={"edition": "NBR 14653-2:2011"},
        artifact_refs={},
        sample_ledger=prepared["sample_ledger"],
        search_audit={"selection_scope": "population_model", "selection_conditioned_on_subject": False},
    )
    assert frozen["model_scope"] == "population_model"
    assert frozen["selection_conditioned_on_subject"] is False
    unsupported = builtin_evaluate_fitted(
        restore_candidate_fit(frozen),
        {
            "subject_id": "unknown-cat",
            "raw_values": {"area": 90.0, "bairro": "Leste"},
            "X": {},
            "supported": False,
            "issues": [{"code": "unknown_category", "severity": "error", "origin": "c14", "message": "unknown"}],
        },
        req,
    )
    assert unsupported["value"]["point"] is None
    assert unsupported["model_eligibility"]["status"] in {"unsupported", "error"}
    reasons = unsupported["model_eligibility"].get("reasons") or []
    assert "unknown_category" in reasons or any("unsupported" in str(r) for r in reasons)
