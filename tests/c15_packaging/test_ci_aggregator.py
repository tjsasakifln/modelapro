"""Aggregator must not go green on failed/absent/cancelled required jobs."""

from __future__ import annotations

from c15_local.aggregate_required import evaluate


def test_all_success_is_green():
    assert evaluate({"lint": "success", "wide": "success", "c16": "success"}) == 0


def test_failed_job_is_red():
    assert evaluate({"lint": "success", "wide": "failure"}) == 1


def test_cancelled_is_not_success():
    assert evaluate({"wide": "cancelled"}) == 1


def test_skipped_is_not_success():
    assert evaluate({"wide": "skipped"}) == 1


def test_empty_results_is_not_success():
    assert evaluate({}) == 1


def test_absent_status_is_not_success():
    assert evaluate({"wide": ""}) == 1


def test_github_needs_nested_result_is_normalized():
    from c15_local.aggregate_required import main

    assert (
        main(
            [
                "--results-json",
                '{"lint": {"result": "success"}, "wide": {"result": "failure"}}',
            ]
        )
        == 1
    )
    assert main(["--results-json", '{"lint": {"result": "success"}}']) == 0


def test_missing_required_job_is_red_even_if_others_succeeded():
    from c15_local.aggregate_required import evaluate

    assert (
        evaluate(
            {"lint": "success", "wide-suite-linux": "success"},
            required=["lint", "wide-suite-linux", "p04-harness"],
        )
        == 1
    )


def test_unrun_empty_status_with_inventory_is_red():
    from c15_local.aggregate_required import evaluate

    assert evaluate({"lint": "success", "p04-harness": ""}, required=["lint", "p04-harness"]) == 1


def test_inventory_all_success_is_green():
    from c15_local.aggregate_required import evaluate

    assert (
        evaluate(
            {"lint": "success", "p04-harness": "success"},
            required=["lint", "p04-harness"],
        )
        == 0
    )


def test_cli_required_jobs_flag():
    from c15_local.aggregate_required import main

    assert (
        main(
            [
                "--results-json",
                '{"lint": {"result": "success"}}',
                "--required-jobs",
                "lint,p04-harness",
            ]
        )
        == 1
    )
