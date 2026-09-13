"""C14-A02: unknown category fails only that item; summary keeps all counts."""

from __future__ import annotations

from modules.valuation_batch import (
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    evaluate_batch,
)

from .conftest import make_frozen_project, make_request_spec, make_subject


def test_unknown_category_fails_only_that_item_and_stays_in_summary():
    frozen = make_frozen_project()
    spec = make_request_spec()
    ok_a = make_subject("ok-a", area=80.0, bairro="Centro")
    unknown = make_subject("bad-cat", area=80.0, bairro="Norte")
    ok_b = make_subject("ok-b", area=120.0, bairro="Sul")

    result = evaluate_batch(frozen, [ok_a, unknown, ok_b], spec)
    items = {item["subject_id"]: item for item in result["items"]}

    assert list(item["subject_id"] for item in result["items"]) == ["ok-a", "bad-cat", "ok-b"]
    assert items["ok-a"]["status"] == STATUS_SUCCEEDED
    assert items["ok-b"]["status"] == STATUS_SUCCEEDED
    assert items["ok-a"]["value"]["point"] is not None
    assert items["ok-b"]["value"]["point"] is not None

    bad = items["bad-cat"]
    assert bad["status"] == STATUS_FAILED
    assert bad["value"]["point"] is None
    codes = [i.get("code") for i in bad["assessment"]["issues"]]
    assert "unknown_category" in codes
    assert bad["assessment"]["model_eligibility"]["status"] == "error"
    # Item remains in the list and in the totals.
    assert result["summary"]["total"] == 3
    assert result["summary"]["succeeded"] == 2
    assert result["summary"]["failed"] == 1
    assert result["summary"]["pending"] == 0
    assert result["summary"]["unsupported"] == 0


def test_unknown_category_does_not_zero_fill_prediction():
    frozen = make_frozen_project()
    spec = make_request_spec()
    unknown = make_subject("ghost", area=80.0, bairro="Industrial")
    result = evaluate_batch(frozen, [unknown], spec)
    item = result["items"][0]
    assert item["value"]["point"] is None
    assert item["value"]["mean_ci80"] is None
    assert item["value"]["point"] != 0
