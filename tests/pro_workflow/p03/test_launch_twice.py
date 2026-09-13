"""Fresh-process launch of render_report and recommend_next_actions, twice."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRATCH = Path("/tmp/grok-goal-d0eb863d4777/implementer")

RENDER_SCRIPT = r"""
import sys
from pathlib import Path
from modules.results_generator import render_report, format_snapshot_number
from tests.c08_report.fixtures import known_snapshot, known_context, KNOWN_POINT
from tests.c08_report.pdf_text import extract_pdf_text, parse_frozen_lines

out = Path(sys.argv[1])
txt = Path(sys.argv[2])
pdf = render_report(known_snapshot(), known_context())
out.write_bytes(pdf)
text = extract_pdf_text(pdf)
txt.write_text(text, encoding="utf-8")
frozen = parse_frozen_lines(text)
print("POINT", frozen["MP1_POINT"])
print("UNIT", frozen["MP1_TARGET_UNIT"])
print("BYTES", len(pdf))
print("PREFIX", pdf[:4])
assert frozen["MP1_POINT"] == format_snapshot_number(KNOWN_POINT)
"""

ACTIONS_SCRIPT = r"""
import json, sys
from pathlib import Path
from modules.decision_support import recommend_next_actions
from tests.pro_workflow.p03.fixtures import workflow_context_snapshot, feature_schema_area_quartos

out = Path(sys.argv[1])
actions = recommend_next_actions(
    workflow_context_snapshot(),
    feature_schema=feature_schema_area_quartos(),
)
out.write_text(json.dumps(actions, ensure_ascii=False, indent=2), encoding="utf-8")
print("N", len(actions))
print("CODES", [a["code"] for a in actions])
"""


def _run(script: str, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", script, *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(cwd)},
    )


def test_render_report_twice_same_frozen_numbers(tmp_path):
    cwd = Path(__file__).resolve().parents[3]
    SCRATCH.mkdir(parents=True, exist_ok=True)
    pairs = [
        (SCRATCH / "p03_launch_run1.pdf", SCRATCH / "p03_launch_run1.txt"),
        (SCRATCH / "p03_launch_run2.pdf", SCRATCH / "p03_launch_run2.txt"),
    ]
    points = []
    for pdf_path, txt_path in pairs:
        proc = _run(RENDER_SCRIPT, [str(pdf_path), str(txt_path)], cwd)
        assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
        assert pdf_path.read_bytes()[:4] == b"%PDF"
        points.append(proc.stdout.strip().splitlines()[0])
    assert points[0] == points[1]
    assert "POINT 350000" in points[0]


def test_recommend_next_actions_twice_identical(tmp_path):
    cwd = Path(__file__).resolve().parents[3]
    SCRATCH.mkdir(parents=True, exist_ok=True)
    paths = [SCRATCH / "p03_actions_run1.json", SCRATCH / "p03_actions_run2.json"]
    payloads = []
    for path in paths:
        proc = _run(ACTIONS_SCRIPT, [str(path)], cwd)
        assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
        payloads.append(json.loads(path.read_text(encoding="utf-8")))
    assert payloads[0] == payloads[1]
    codes = [a["code"] for a in payloads[0]]
    assert "provide_subject_characteristic" not in codes
