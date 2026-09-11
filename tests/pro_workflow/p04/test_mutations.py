"""Controlled copy mutations must fail for the intended cause."""
from __future__ import annotations

import copy

from tests.fixtures.pro_workflow import corpus
from tests.fixtures.pro_workflow.mutations import CAUSES, assert_cause, detect, mutate
from tests.pro_workflow.p04.helpers import client, run_job


def _holdout_snapshot():
    case = corpus.s04_holdout_reserve_category()
    payload = corpus.rows_to_csv_bytes(case["rows"], case["fieldnames"])
    spec = corpus.pinned_identity_spec(
        evaluation_policy={"method": "holdout", "partitions": 1, "groups": None, "seed": 17},
        roles={"preco": "target", "area": "predictor", "id": "identifier", "bairro": "excluded"},
    )
    out = run_job(client(), payload, spec=spec, subject=case["subject_known"])
    snap = out["snapshot"]
    snap = copy.deepcopy(snap)
    snap.setdefault("provenance", {})["request_spec"] = spec
    return snap


def _identity_snapshot():
    case = corpus.s02_ptbr_and_missing()
    spec = corpus.pinned_identity_spec(
        import_options={"locale": "pt-BR", "delimiter": ";", "encoding": "utf-8"},
    )
    out = run_job(client(), corpus.s02_csv_bytes(case), spec=spec, subject=case["subject"])
    snap = copy.deepcopy(out["snapshot"])
    snap.setdefault("provenance", {})["request_spec"] = spec
    return snap


def test_each_mutation_fails_for_its_declared_cause(isolated_p04_runtime):
    identity = _identity_snapshot()
    holdout = _holdout_snapshot()
    sources = {
        "wrong_coefficient_order": identity,
        "missing_ci": identity,
        "percent_band_replacing_uncertainty": identity,
        "none_instead_of_holdout": holdout,
        "swapped_unit": identity,
        "omitted_row": identity,
        "incompatible_recommendation": identity,
    }
    for cause in CAUSES:
        original = sources[cause]
        mutated = mutate(original, cause)
        result = detect(original, mutated, expected_cause=cause)
        assert result["matched_expected"], result
        assert result["primary"] == cause, result
        assert_cause(original, mutated, cause)
        # A valid copy must not be flagged as this cause.
        untouched = detect(original, copy.deepcopy(original), expected_cause=cause)
        assert cause not in untouched["detected"]


def test_unrelated_mutation_does_not_count_as_missing_ci(isolated_p04_runtime):
    original = _identity_snapshot()
    mutated = mutate(original, "omitted_row")
    result = detect(original, mutated, expected_cause="omitted_row")
    assert result["primary"] == "omitted_row"
    assert "missing_ci" not in result["detected"]
