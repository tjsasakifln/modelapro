"""Contract shape of assess_normative and n/k intercept handling."""

from modules.nbr14653_validation import assess_normative
from modules.normative_rules import (
    VS_PARTIAL,
    VS_PENDING,
    VS_VERIFIED_RULES_LISTED,
    resolve_effective_n_k,
)

from .helpers import a01_context

import pandas as pd


ALLOWED_PRECISAO = {"not_computed", "classified", "unclassified", "error"}
ALLOWED_VS = {VS_VERIFIED_RULES_LISTED, VS_PARTIAL, VS_PENDING}
ALLOWED_EVIDENCE = {"calculated", "declared", "verified", "pending", "not_applicable"}


def test_assessment_mapping_fields():
    assessment = assess_normative(a01_context())
    for key in (
        "edition",
        "rule_sources",
        "verification_status",
        "fundamentacao",
        "precisao",
        "documentary",
        "issues",
    ):
        assert key in assessment
    assert assessment["verification_status"] in ALLOWED_VS
    fund = assessment["fundamentacao"]
    assert "grade" in fund and "points" in fund and "items" in fund
    prec = assessment["precisao"]
    assert prec["status"] in ALLOWED_PRECISAO
    item4 = next(i for i in fund["items"] if i["item"] == 4)
    assert item4["evidence_status"] in ALLOWED_EVIDENCE
    assert item4["source"]["edition"] == "ABNT NBR 14653-2:2011"


def test_k_not_guessed_by_shape_minus_one():
    X = pd.DataFrame({"area": [1, 2, 3], "frente": [4, 5, 6]})
    resolved = resolve_effective_n_k({}, X=X, y=[10, 20, 30])
    assert resolved["k"] is None
    assert resolved["intercept"] is None
    assert any(i["code"] == "intercept_unknown" for i in resolved["issues"])

    Xc = pd.DataFrame({"const": 1, "area": [1, 2, 3]})
    resolved_c = resolve_effective_n_k({}, X=Xc, y=[10, 20, 30])
    assert resolved_c["k"] == 1
    assert resolved_c["intercept"] is True

    resolved_explicit = resolve_effective_n_k({"n": 30, "k": 2, "intercept": False})
    assert resolved_explicit["k"] == 2
    assert resolved_explicit["k_source"] == "context"


def test_unverified_rules_are_listed_not_claimed():
    assessment = assess_normative(a01_context())
    assert "unverified_rules" in assessment
    assert "9.2.1.6.1.homogeneous" in assessment["unverified_rules"]
    unverified_ids = {r["id"] for r in assessment["rule_sources"] if r.get("status") == "unverified"}
    assert "tabelas3_4.fatores" in unverified_ids
