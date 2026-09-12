"""C18/P04 workflow must check PRs against integracao-final and the consolidation branch."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "c15-ci.yml"


def _load() -> str:
    assert WORKFLOW.is_file(), WORKFLOW
    return WORKFLOW.read_text(encoding="utf-8")


def test_pull_request_includes_integration_and_p04_branches():
    text = _load()
    assert "pull_request:" in text
    assert "mp-20260911/integracao-final" in text
    assert "mp-pro-20260911/p04-referencia-consolidacao" in text
    assert "workflow_dispatch:" in text
    assert "pull_request_target" not in text


def test_permissions_remain_contents_read():
    text = _load()
    assert "permissions:" in text
    assert "contents: read" in text


def test_aggregator_is_always_and_lists_p04_harness():
    text = _load()
    assert "if: always()" in text
    assert "p04-harness" in text
    assert "--required-jobs" in text
    assert "aggregate_required.py" in text


def test_p04_harness_job_accepts_the_candidate_strictly():
    """R20-A: the candidate is accepted with accept-candidate, never diagnosed."""
    text = _load()
    assert "scripts/pro_workflow/run.py --mode accept-candidate" in text
    assert "run.py --mode diagnose-base" not in text


# --- R20-A structural guards -------------------------------------------------
#
# The gap was not a bad assertion, it was a shell default: GitHub's default
# `bash -e {0}` has no pipefail, so `run.py | tee` returned tee's zero while
# the runner had failed. These tests fail if that default ever comes back.

from tests.c15_packaging._workflow_yaml import load as _load_yaml  # noqa: E402

LINUX_JOBS = (
    "lint",
    "c15-tests-linux",
    "build-sdist-wheel",
    "install-eval-linux",
    "wide-suite-linux",
    "c16-harness",
    "p04-harness",
    "acceptance",
)


def _jobs() -> dict:
    return _load_yaml(_load())["jobs"]


def _shell_of(job: dict) -> str:
    return str(((job.get("defaults") or {}).get("run") or {}).get("shell") or "")


def test_every_linux_job_declares_pipefail_by_default():
    jobs = _jobs()
    for name in LINUX_JOBS:
        assert name in jobs, f"job {name} disappeared from the workflow"
        shell = _shell_of(jobs[name])
        assert "pipefail" in shell, f"job {name} has no pipefail default: {shell!r}"


def test_no_linux_run_step_pipes_without_pipefail_in_effect():
    """Every pipe must propagate failure, by job default or by set -o pipefail."""
    jobs = _jobs()
    offenders = []
    for name, job in jobs.items():
        if "windows" in str(job.get("runs-on", "")):
            continue
        job_pipefail = "pipefail" in _shell_of(job)
        for step in job.get("steps") or []:
            body = step.get("run")
            if not body or "|" not in body:
                continue
            piped = [
                line
                for line in body.splitlines()
                if "|" in line and not line.strip().startswith("#")
            ]
            if not piped:
                continue
            step_pipefail = "pipefail" in str(step.get("shell") or "") or "set -o pipefail" in body
            if not (job_pipefail or step_pipefail):
                offenders.append(f"{name}:{step.get('name')}")
    assert not offenders, f"piped run steps with no pipefail: {offenders}"


def test_windows_job_is_untouched_by_the_bash_defaults():
    job = _jobs()["c15-tests-windows"]
    assert "pipefail" not in _shell_of(job)
    for step in job["steps"]:
        if step.get("run"):
            assert step.get("shell") == "pwsh", step


def test_aggregator_opens_the_evidence_not_only_the_job_results():
    """Job conclusions alone are structurally blind to R20-A."""
    steps = _jobs()["acceptance"]["steps"]
    uses = [s.get("uses", "") for s in steps]
    assert any(u.startswith("actions/download-artifact@") for u in uses), uses
    download = next(s for s in steps if str(s.get("uses", "")).startswith("actions/download-artifact@"))
    assert download["with"].get("merge-multiple") is True
    run_bodies = " ".join(s.get("run", "") for s in steps)
    assert "--artifacts-dir" in run_bodies
    assert "--expected-sha" in run_bodies
    assert "--min-wide-tests" in run_bodies
    assert "--p04-mode accept-candidate" in run_bodies


def test_expected_sha_uses_the_pr_head_not_the_merge_commit():
    """On pull_request, github.sha is the merge commit; artifacts carry the head."""
    step = next(
        s
        for s in _jobs()["acceptance"]["steps"]
        if "--expected-sha" in str(s.get("run", ""))
    )
    expr = str((step.get("env") or {}).get("CANDIDATE_SHA") or "")
    assert "pull_request.head.sha" in expr, expr


def test_no_mandatory_upload_may_vanish_silently():
    for name, job in _jobs().items():
        for step in job.get("steps") or []:
            if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
                found = (step.get("with") or {}).get("if-no-files-found")
                assert found == "error", f"{name}:{step.get('name')} -> {found!r}"


# --- the reader itself must not be silently wrong ------------------------
#
# Every guard above is only as good as _workflow_yaml.load. A reader that
# quietly returned an empty mapping would make all of them vacuous, so it is
# pinned against known content of the real file and against a hand-built
# sample with the shapes it claims to support.


def test_reader_sees_every_job_of_the_real_workflow():
    jobs = _jobs()
    assert set(LINUX_JOBS) | {"c15-tests-windows"} == set(jobs), sorted(jobs)
    for name, job in jobs.items():
        assert job.get("runs-on"), name
        assert job.get("steps"), name


def test_reader_handles_the_shapes_it_claims():
    sample = """
name: demo
on:
  push:
    branches:
      - main
jobs:
  build:
    runs-on: ubuntu-latest
    defaults:
      run:
        shell: bash -eo pipefail {0}
    steps:
      - uses: actions/checkout@v4
      - name: piped
        env:
          K: v
        run: |
          echo a | tee b.log
          echo done
      - uses: actions/upload-artifact@v4
        with:
          name: out
          path: x/
          if-no-files-found: error
          merge-multiple: true
"""
    doc = _load_yaml(sample)
    job = doc["jobs"]["build"]
    assert job["runs-on"] == "ubuntu-latest"
    assert job["defaults"]["run"]["shell"] == "bash -eo pipefail {0}"
    steps = job["steps"]
    assert len(steps) == 3, steps
    assert steps[0]["uses"] == "actions/checkout@v4"
    assert steps[1]["name"] == "piped"
    assert steps[1]["env"] == {"K": "v"}
    assert steps[1]["run"].splitlines() == ["echo a | tee b.log", "echo done"]
    assert steps[2]["with"]["if-no-files-found"] == "error"
    assert steps[2]["with"]["merge-multiple"] is True
    assert doc["on"]["push"]["branches"] == ["main"]


def test_reader_does_not_silently_return_empty():
    assert _load_yaml("") == {}
    assert _jobs(), "reader returned nothing for the real workflow"
