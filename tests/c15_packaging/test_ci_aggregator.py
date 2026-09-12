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


# --- R20-A: a green job whose own evidence records failure must not pass -----
#
# The historical gap: the p04-harness job piped run.py into tee without
# pipefail and ran the diagnostic mode, so the job returned 0 while
# artifacts/p04/run.json recorded exit_code 1. Job conclusions alone cannot
# see that, so these injections drive the artifact readers directly.

import json
import xml.etree.ElementTree as ET

import pytest

from c15_local.aggregate_required import (
    check_c16,
    check_junit,
    check_p04_run,
    verify_artifacts,
)

CANDIDATE_SHA = "8d66c7973c659174e06d7223c9a9a8181e8eeabf"


def _clean_run(**over):
    payload = {
        "mode": "accept-candidate",
        "sha": CANDIDATE_SHA,
        "exit_code": 0,
        "skip_xfail_count": 0,
        "findings": [],
        "runs": [
            {"name": "core-1", "returncode": 0, "passed": 40, "failed": 0},
            {"name": "core-2", "returncode": 0, "passed": 40, "failed": 0},
            {"name": "extensions", "returncode": 0, "passed": 8, "failed": 0},
        ],
    }
    payload.update(over)
    return payload


def _write_run(tmp_path, payload):
    path = tmp_path / "run.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _junit(tmp_path, cases=705, failures=0, name="wide.junit.xml"):
    suite = ET.Element("testsuite")
    for i in range(cases):
        case = ET.SubElement(suite, "testcase", classname="t", name=f"t{i}")
        if i < failures:
            ET.SubElement(case, "failure", message="boom")
    path = tmp_path / name
    ET.ElementTree(suite).write(path)
    return path


def _clean_c16(**over):
    payload = {
        "sha": CANDIDATE_SHA,
        "counts": {
            "aprovados": 120,
            "reprovados": 0,
            "nao_executados": 0,
            "violacoes_a04_skip_xfail": 0,
            "disjoint": True,
        },
    }
    payload.update(over)
    return payload


def test_clean_run_artifact_has_no_problems(tmp_path):
    assert check_p04_run(_write_run(tmp_path, _clean_run()), expected_sha=CANDIDATE_SHA) == []


def test_r20a_exit_code_one_in_artifact_is_caught_even_though_job_was_green(tmp_path):
    """The exact R20-A symptom: job returned 0, artifact says exit_code 1."""
    problems = check_p04_run(_write_run(tmp_path, _clean_run(exit_code=1)), expected_sha=CANDIDATE_SHA)
    assert any("exit_code" in p for p in problems), problems


def test_lost_exit_code_key_is_caught(tmp_path):
    payload = _clean_run()
    payload.pop("exit_code")
    problems = check_p04_run(_write_run(tmp_path, payload), expected_sha=CANDIDATE_SHA)
    assert any("exit_code absent" in p for p in problems), problems


def test_diagnostic_mode_cannot_accept_the_candidate(tmp_path):
    problems = check_p04_run(_write_run(tmp_path, _clean_run(mode="diagnose-base")), expected_sha=CANDIDATE_SHA)
    assert any("mode" in p for p in problems), problems


def test_absent_run_artifact_is_caught(tmp_path):
    assert any("absent" in p for p in check_p04_run(tmp_path / "run.json"))


def test_empty_and_unparseable_run_artifact_are_caught(tmp_path):
    (tmp_path / "run.json").write_text("", encoding="utf-8")
    assert any("empty" in p for p in check_p04_run(tmp_path / "run.json"))
    (tmp_path / "run.json").write_text("{not json", encoding="utf-8")
    assert any("parseable" in p for p in check_p04_run(tmp_path / "run.json"))


def test_stale_artifact_from_another_sha_is_caught(tmp_path):
    problems = check_p04_run(
        _write_run(tmp_path, _clean_run(sha="0" * 40)),
        expected_sha=CANDIDATE_SHA,
    )
    assert any("stale" in p for p in problems), problems


def test_short_sha_prefix_still_matches(tmp_path):
    assert check_p04_run(_write_run(tmp_path, _clean_run(sha="8d66c79")), expected_sha=CANDIDATE_SHA) == []


def test_suite_that_never_ran_is_caught(tmp_path):
    assert any("no runs" in p for p in check_p04_run(_write_run(tmp_path, _clean_run(runs=[]))))


def test_run_with_zero_passed_cases_is_caught(tmp_path):
    payload = _clean_run(runs=[{"name": "core-1", "returncode": 0, "passed": 0, "failed": 0}])
    problems = check_p04_run(_write_run(tmp_path, payload))
    assert any("zero passed" in p for p in problems), problems


def test_missing_strict_extensions_suite_is_caught(tmp_path):
    payload = _clean_run(runs=[{"name": "core-1", "returncode": 0, "passed": 40, "failed": 0}])
    problems = check_p04_run(_write_run(tmp_path, payload))
    assert any("extensions suite is absent" in p for p in problems), problems


def test_nonzero_returncode_inside_a_run_is_caught(tmp_path):
    payload = _clean_run()
    payload["runs"][2] = {"name": "extensions", "returncode": 1, "passed": 7, "failed": 1}
    problems = check_p04_run(_write_run(tmp_path, payload))
    assert any("returncode" in p for p in problems), problems


def test_skip_xfail_is_caught(tmp_path):
    assert any("skip/xfail" in p for p in check_p04_run(_write_run(tmp_path, _clean_run(skip_xfail_count=2))))


def test_failure_shaped_findings_are_caught_but_success_records_are_not(tmp_path):
    """`findings` is an event log: run.py appends success records too."""
    success_records = [
        {"id": "P04-EXT-formula", "present": True, "formula": "preco = -0 + 10000*area"},
        {"id": "P04-EXT-alias_conflict", "present": True, "http_status": 400},
    ]
    assert check_p04_run(_write_run(tmp_path, _clean_run(findings=success_records)), expected_sha=CANDIDATE_SHA) == []

    for bad in (
        {"suite": "extensions", "nodeid": "t::test_x", "message": "AssertionError: boom"},
        {"id": "P04-EXT-minimum_grade", "present": False, "requested": 2, "observed": None},
        {"file": "x.json", "parse": "error"},
    ):
        problems = check_p04_run(_write_run(tmp_path, _clean_run(findings=[bad])), expected_sha=CANDIDATE_SHA)
        assert any("failure findings" in p for p in problems), (bad, problems)


def test_junit_clean_is_accepted_and_red_is_caught(tmp_path):
    assert check_junit(_junit(tmp_path), min_tests=700) == []
    assert any("failed" in p for p in check_junit(_junit(tmp_path, failures=3), min_tests=700))


def test_truncated_or_empty_junit_is_caught(tmp_path):
    problems = check_junit(_junit(tmp_path, cases=12), min_tests=700)
    assert any("floor" in p for p in problems), problems
    assert any("floor" in p for p in check_junit(_junit(tmp_path, cases=0), min_tests=700))


def test_absent_or_unparseable_junit_is_caught(tmp_path):
    assert any("absent" in p for p in check_junit(tmp_path / "wide.junit.xml", min_tests=1))
    (tmp_path / "wide.junit.xml").write_text("<testsuite", encoding="utf-8")
    assert any("parseable" in p for p in check_junit(tmp_path / "wide.junit.xml", min_tests=1))


def test_c16_summary_injections(tmp_path):
    def run(payload):
        (tmp_path / "c16.json").write_text(json.dumps(payload), encoding="utf-8")
        return check_c16(tmp_path / "c16.json", expected_sha=CANDIDATE_SHA)

    assert run(_clean_c16()) == []
    bad = _clean_c16()
    bad["counts"]["reprovados"] = 2
    assert any("reprovados" in p for p in run(bad))
    bad = _clean_c16()
    bad["counts"]["violacoes_a04_skip_xfail"] = 1
    assert any("skip/xfail" in p for p in run(bad))
    bad = _clean_c16()
    bad["counts"]["aprovados"] = 0
    assert any("zero aprovados" in p for p in run(bad))
    bad = _clean_c16()
    bad["counts"]["disjoint"] = False
    assert any("disjoint" in p for p in run(bad))
    assert any("stale" in p for p in run(_clean_c16(sha="f" * 40)))


def _populate(tmp_path, run_over=None, junit_kw=None, c16_over=None):
    _write_run(tmp_path, _clean_run(**(run_over or {})))
    _junit(tmp_path, **(junit_kw or {}))
    (tmp_path / "c16.json").write_text(json.dumps(_clean_c16(**(c16_over or {}))), encoding="utf-8")
    return tmp_path


def test_verify_artifacts_clean_is_green(tmp_path):
    assert verify_artifacts(_populate(tmp_path), expected_sha=CANDIDATE_SHA, min_wide_tests=700) == []


def test_verify_artifacts_absent_directory_is_red(tmp_path):
    problems = verify_artifacts(tmp_path / "nope", expected_sha=CANDIDATE_SHA)
    assert any("no evidence was downloaded" in p for p in problems), problems


@pytest.mark.parametrize(
    "kwargs",
    [
        {"run_over": {"exit_code": 1}},
        {"run_over": {"mode": "diagnose-base"}},
        {"run_over": {"skip_xfail_count": 3}},
        {"run_over": {"sha": "0" * 40}},
        {"junit_kw": {"failures": 1}},
        {"junit_kw": {"cases": 10}},
        {"c16_over": {"counts": {"aprovados": 1, "reprovados": 1, "disjoint": True}}},
    ],
)
def test_every_mandatory_injection_makes_the_gate_red(tmp_path, kwargs):
    assert verify_artifacts(_populate(tmp_path, **kwargs), expected_sha=CANDIDATE_SHA, min_wide_tests=700)


def test_main_is_red_when_all_jobs_are_green_but_evidence_records_failure(tmp_path):
    """The discriminating case for C06-A01."""
    from c15_local.aggregate_required import main

    _populate(tmp_path, run_over={"exit_code": 1})
    all_green = json.dumps({name: {"result": "success"} for name in ("lint", "p04-harness")})
    rc = main(
        [
            "--results-json", all_green,
            "--required-jobs", "lint,p04-harness",
            "--artifacts-dir", str(tmp_path),
            "--expected-sha", CANDIDATE_SHA,
            "--min-wide-tests", "700",
        ]
    )
    assert rc != 0


def test_main_is_green_only_when_jobs_and_evidence_both_agree(tmp_path):
    from c15_local.aggregate_required import main

    _populate(tmp_path)
    all_green = json.dumps({name: {"result": "success"} for name in ("lint", "p04-harness")})
    assert (
        main(
            [
                "--results-json", all_green,
                "--required-jobs", "lint,p04-harness",
                "--artifacts-dir", str(tmp_path),
                "--expected-sha", CANDIDATE_SHA,
                "--min-wide-tests", "700",
            ]
        )
        == 0
    )
