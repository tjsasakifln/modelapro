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


def test_p04_harness_job_exists():
    text = _load()
    assert "scripts/pro_workflow/run.py --mode diagnose-base" in text
