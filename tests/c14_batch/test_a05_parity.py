"""C14-A05: batch item matches the individual frozen-model path in original unit."""

from __future__ import annotations

import math

from modules.valuation_batch import (
    evaluate_batch,
    resolve_adapters,
    restore_candidate_fit,
)

from .conftest import expected_point, make_frozen_project, make_request_spec, make_subject


def _close(a, b, rel=1e-9, abs_tol=1e-6):
    if a is None or b is None:
        return a is b
    return math.isclose(float(a), float(b), rel_tol=rel, abs_tol=abs_tol)


def test_batch_matches_individual_evaluate_fitted_in_original_unit():
    frozen = make_frozen_project()
    spec = make_request_spec()
    subjects = [
        make_subject("p-centro", area=95.0, bairro="Centro"),
        make_subject("p-sul", area=140.0, bairro="Sul"),
    ]
    batch = evaluate_batch(frozen, subjects, spec)
    adapters = resolve_adapters()
    fit = restore_candidate_fit(frozen)

    for subject, item in zip(subjects, batch["items"]):
        design = adapters["transform_subject"](
            subject["raw"], frozen["feature_schema"], frozen["encoder_state"]
        )
        individual = adapters["evaluate_fitted"](fit, design, spec)
        batch_value = item["value"]
        ind_value = individual["value"]
        oracle = expected_point(subject["raw"]["area"], subject["raw"]["bairro"])
        assert _close(batch_value["point"], oracle)
        assert _close(ind_value["point"], oracle)
        assert _close(batch_value["point"], ind_value["point"])
        if batch_value.get("mean_ci80") and ind_value.get("mean_ci80"):
            assert _close(batch_value["mean_ci80"]["lower"], ind_value["mean_ci80"]["lower"])
            assert _close(batch_value["mean_ci80"]["upper"], ind_value["mean_ci80"]["upper"])
        assert item["unit"] == spec["target_unit"]
        assert item["version_link"]["revision_id"] == frozen["revision_id"]
        assert item["version_link"]["reuse_key"] == batch["reuse"]["key"]
        assert "fundamentacao" in item["assessment"]["normative"]
        assert "precisao" in item["assessment"]["normative"]


def test_one_by_one_batch_calls_match_single_lote():
    frozen = make_frozen_project()
    spec = make_request_spec()
    subjects = [
        make_subject("q1", area=70.0, bairro="Centro"),
        make_subject("q2", area=160.0, bairro="Sul"),
    ]
    lote = evaluate_batch(frozen, subjects, spec)
    individuals = [evaluate_batch(frozen, [s], spec)["items"][0] for s in subjects]
    for left, right in zip(lote["items"], individuals):
        assert _close(left["value"]["point"], right["value"]["point"])
        if left["value"].get("mean_ci80"):
            assert _close(left["value"]["mean_ci80"]["lower"], right["value"]["mean_ci80"]["lower"])


def test_export_is_structured_mapping_not_a_pdf():
    frozen = make_frozen_project()
    spec = make_request_spec()
    result = evaluate_batch(frozen, [make_subject("e1", area=88.0, bairro="Centro")], spec)
    export = result["export"]
    assert isinstance(export, dict)
    assert export["schema_version"] == "MP/1"
    assert export["items"][0]["assessment"]["issues"] is not None
    # No consolidated PDF bytes that would erase per-item ressalvas.
    assert not isinstance(export, (bytes, bytearray))
    assert "pdf" not in export
