"""C14-A03: complete reuse key, invalidation, reproduction, idempotency."""

from __future__ import annotations

import copy

from modules.valuation_batch import (
    ReuseLedger,
    compute_reuse_key,
    evaluate_batch,
)

from .conftest import make_frozen_project, make_request_spec, make_subject


def _two_subjects():
    return [
        make_subject("a", area=90.0, bairro="Centro"),
        make_subject("b", area=110.0, bairro="Sul"),
    ]


def test_filename_rowcount_or_target_alone_do_not_form_the_key():
    frozen = make_frozen_project()
    spec = make_request_spec()
    key = compute_reuse_key(frozen, spec)

    renamed = copy.deepcopy(frozen)
    renamed["provenance"]["filename"] = "other_name.xlsx"
    assert compute_reuse_key(renamed, spec) == key

    # A lone row-count field must not be the identity.
    with_count = copy.deepcopy(frozen)
    with_count["sample_ledger"]["n_rows"] = 999
    with_count["provenance"]["n_rows"] = 999
    assert compute_reuse_key(with_count, spec) == key

    # Changing only the isolated target column name in provenance is not enough
    # to keep identity if the real target_col in request_spec stays the same —
    # and changing request_spec.target_col DOES invalidate.
    spec_same_target = make_request_spec()
    assert compute_reuse_key(frozen, spec_same_target) == key
    spec_other_target = make_request_spec(target_col="valor")
    assert compute_reuse_key(frozen, spec_other_target) != key


def test_mutating_base_sample_schema_transform_unit_policy_or_version_invalidates():
    frozen = make_frozen_project()
    spec = make_request_spec()
    base_key = compute_reuse_key(frozen, spec)
    ledger = ReuseLedger()
    evaluate_batch(frozen, _two_subjects(), spec, reuse_ledger=ledger)
    assert ledger.lookup(base_key) is not None

    mutations = []

    other_base = copy.deepcopy(frozen)
    other_base["input_sha256"] = "abc" * 16
    mutations.append(("input_sha256", other_base, spec))

    other_dataset = copy.deepcopy(frozen)
    other_dataset["dataset_sha256"] = "def" * 16
    mutations.append(("dataset_sha256", other_dataset, spec))

    other_excl = copy.deepcopy(frozen)
    other_excl["sample_ledger"]["excluded_row_ids"] = ["r30", "r29"]
    other_excl["sample_ledger"]["used_row_ids"] = [f"r{i}" for i in range(1, 29)]
    mutations.append(("exclusion", other_excl, spec))

    other_schema = copy.deepcopy(frozen)
    other_schema["feature_schema"]["columns"]["area"]["unit"] = "ft2"
    mutations.append(("schema", other_schema, spec))

    other_tx = copy.deepcopy(frozen)
    other_tx["model_spec"]["x_transformations"] = {"area": "ln"}
    mutations.append(("transformation", other_tx, spec))

    other_unit = copy.deepcopy(frozen)
    spec_unit = make_request_spec(target_unit="BRL/m2")
    other_unit["request_spec"]["target_unit"] = "BRL/m2"
    mutations.append(("target_unit", other_unit, spec_unit))

    other_policy = copy.deepcopy(frozen)
    spec_pol = make_request_spec(missing_policy={"target": "never_impute", "predictors": "mean"})
    other_policy["request_spec"]["missing_policy"] = spec_pol["missing_policy"]
    mutations.append(("policy", other_policy, spec_pol))

    other_ver = copy.deepcopy(frozen)
    other_ver["normative_version"] = "NBR 14653-2:2011+errata"
    mutations.append(("normative_version", other_ver, spec))

    other_scope = copy.deepcopy(frozen)
    other_scope["model_scope"] = "subject_specific"
    other_scope["subject_constraints"] = {"selection_subject_id": "a"}
    mutations.append(("subject_constraints", other_scope, spec))

    for label, mutated, mutated_spec in mutations:
        new_key = compute_reuse_key(mutated, mutated_spec)
        assert new_key != base_key, label
        assert ledger.lookup(new_key) is None, label


def test_identical_inputs_reproduce_and_second_call_is_idempotent():
    frozen = make_frozen_project()
    spec = make_request_spec()
    subjects = _two_subjects()
    ledger = ReuseLedger()

    first = evaluate_batch(frozen, subjects, spec, reuse_ledger=ledger)
    second = evaluate_batch(frozen, subjects, spec, reuse_ledger=ledger)
    assert first["reuse"]["key"] == second["reuse"]["key"]
    assert second["reuse"]["ledger_hit"] is True
    assert [i["subject_id"] for i in second["items"]] == ["a", "b"]
    assert len(second["items"]) == 2
    for left, right in zip(first["items"], second["items"]):
        assert left["value"]["point"] == right["value"]["point"]
        assert left["status"] == right["status"]
        assert left["assessment"]["normative"]["fundamentacao"]["grade"] == right["assessment"]["normative"]["fundamentacao"]["grade"]

    duplicated = evaluate_batch(frozen, subjects + subjects, spec, reuse_ledger=ledger)
    assert [i["subject_id"] for i in duplicated["items"]] == ["a", "b"]
    assert duplicated["summary"]["total"] == 2

    resumed = evaluate_batch(frozen, subjects, spec, resume_from=first, reuse_ledger=ledger)
    assert [i["subject_id"] for i in resumed["items"]] == ["a", "b"]
    assert resumed["items"][0]["value"]["point"] == first["items"][0]["value"]["point"]
