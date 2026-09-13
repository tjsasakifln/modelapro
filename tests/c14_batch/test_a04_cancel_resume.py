"""C14-A04: cancel then reopen does not rewrite completed or promote pending."""

from __future__ import annotations

from modules.valuation_batch import (
    STATUS_PENDING,
    STATUS_SUCCEEDED,
    evaluate_batch,
)

from .conftest import make_frozen_project, make_request_spec, make_subject


def test_cancel_leaves_remaining_pending_and_resume_skips_completed():
    frozen = make_frozen_project()
    spec = make_request_spec()
    subjects = [
        make_subject("one", area=80.0, bairro="Centro"),
        make_subject("two", area=90.0, bairro="Sul"),
        make_subject("three", area=100.0, bairro="Centro"),
    ]

    seen = {"n": 0}

    def cancel_after_first() -> bool:
        return seen["n"] >= 1

    def progress(payload):
        if payload.get("event") == "item_completed":
            seen["n"] += 1

    cancelled = evaluate_batch(
        frozen,
        subjects,
        spec,
        progress_callback=progress,
        cancel_requested=cancel_after_first,
        max_workers=1,
    )
    assert cancelled["state"] == "cancelled"
    statuses = [item["status"] for item in cancelled["items"]]
    assert statuses[0] == STATUS_SUCCEEDED
    assert statuses[1] == STATUS_PENDING
    assert statuses[2] == STATUS_PENDING
    assert cancelled["summary"]["succeeded"] == 1
    assert cancelled["summary"]["pending"] == 2
    assert cancelled["summary"]["failed"] == 0
    assert cancelled["items"][1]["value"]["point"] is None
    assert cancelled["items"][2]["status"] != STATUS_SUCCEEDED

    # Tamper-evident: completed item must be copied, not recomputed/rewritten.
    original_point = cancelled["items"][0]["value"]["point"]
    cancelled["items"][0]["value"]["point"] = original_point + 12345.0
    cancelled["items"][0]["assessment"]["value"]["point"] = original_point + 12345.0

    reopened = evaluate_batch(
        frozen,
        subjects,
        spec,
        resume_from=cancelled,
        max_workers=1,
    )
    assert [item["subject_id"] for item in reopened["items"]] == ["one", "two", "three"]
    # Completed item is preserved as stored (not recomputed to the true point).
    assert reopened["items"][0]["value"]["point"] == original_point + 12345.0
    assert reopened["items"][1]["status"] == STATUS_SUCCEEDED
    assert reopened["items"][2]["status"] == STATUS_SUCCEEDED
    assert reopened["items"][1]["value"]["point"] is not None
    assert reopened["summary"]["pending"] == 0
    assert reopened["state"] == "succeeded"


def test_progress_is_honest_fraction_not_invented_percent():
    frozen = make_frozen_project()
    spec = make_request_spec()
    subjects = [
        make_subject("p1", area=70.0, bairro="Centro"),
        make_subject("p2", area=80.0, bairro="Centro"),
    ]
    events = []

    def progress(payload):
        events.append(dict(payload))

    result = evaluate_batch(frozen, subjects, spec, progress_callback=progress, max_workers=1)
    assert events[0]["event"] == "batch_started"
    assert events[0]["progress"] == 0.0
    item_events = [e for e in events if e["event"] == "item_completed"]
    assert len(item_events) == 2
    assert item_events[0]["completed"] == 1
    assert item_events[0]["total"] == 2
    assert item_events[0]["progress"] == 0.5
    assert item_events[1]["progress"] == 1.0
    assert 0.0 <= result["progress"] <= 1.0
    assert result["progress"] == 1.0


def test_max_workers_is_capped_locally():
    frozen = make_frozen_project()
    spec = make_request_spec()
    subjects = [make_subject("w1", area=75.0, bairro="Centro")]
    result = evaluate_batch(frozen, subjects, spec, max_workers=64)
    assert result["max_workers"] <= 8
    assert result["items"][0]["status"] == STATUS_SUCCEEDED


def test_parallel_cancel_does_not_submit_remaining_as_success():
    """C14-A04 with max_workers>1: cancel after the first completion must not
    promote unstarted items to success (the pool used to submit every index
    before cancel_requested could fire)."""
    frozen = make_frozen_project()
    spec = make_request_spec()
    subjects = [
        make_subject(f"p{i}", area=70.0 + i, bairro="Centro")
        for i in range(5)
    ]
    seen = {"n": 0}

    def cancel_after_first() -> bool:
        return seen["n"] >= 1

    def progress(payload):
        if payload.get("event") == "item_completed":
            seen["n"] += 1

    result = evaluate_batch(
        frozen,
        subjects,
        spec,
        progress_callback=progress,
        cancel_requested=cancel_after_first,
        max_workers=4,
    )
    statuses = [item["status"] for item in result["items"]]
    assert result["state"] == "cancelled"
    assert STATUS_PENDING in statuses
    assert statuses.count(STATUS_SUCCEEDED) < 5
    assert result["summary"]["pending"] >= 1
    assert result["summary"]["succeeded"] + result["summary"]["failed"] + result["summary"]["unsupported"] < 5
    for item in result["items"]:
        if item["status"] == STATUS_PENDING:
            assert item["value"]["point"] is None
            assert item["status"] != STATUS_SUCCEEDED
    assert result["summary"]["total"] == 5
    # Resume still evaluates only the proven pending items.
    reopened = evaluate_batch(frozen, subjects, spec, resume_from=result, max_workers=4)
    assert len(reopened["items"]) == 5
    assert reopened["summary"]["pending"] == 0
    for prev, nxt in zip(result["items"], reopened["items"]):
        if prev["status"] in {STATUS_SUCCEEDED, "failed", "unsupported"}:
            assert nxt["value"]["point"] == prev["value"]["point"]
            assert nxt["status"] == prev["status"]
