"""Record the actual selected obligations and calls for the candidate wide suite."""
import json
import os
from pathlib import Path

_calls = {}


def pytest_runtest_logreport(report):
    if report.when == "call" or report.failed or report.skipped:
        _calls[report.nodeid] = {"outcome": report.outcome, "phase": report.when}


def pytest_sessionfinish(session, exitstatus):
    target = Path(os.environ["C06_COLLECTION_OUTPUT"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "schema": "MP-C06-COLLECTION/1",
        "tested_commit_sha": os.environ.get("GITHUB_SHA"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "nodeids": [item.nodeid for item in session.items],
        "calls": _calls,
        "exit_code": int(exitstatus),
    }, indent=2) + "\n", encoding="utf-8")
