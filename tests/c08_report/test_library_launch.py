"""Fresh-process import of render_report must work twice with the same numbers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.c08_report.fixtures import KNOWN_POINT
from tests.c08_report.pdf_text import extract_pdf_text, parse_frozen_lines

SCRATCH = Path("/tmp/grok-goal-5bf97f948c30/implementer")
SCRIPT = r"""
import sys
from pathlib import Path
from modules.results_generator import render_report, format_snapshot_number
from tests.c08_report.fixtures import known_snapshot, known_context, KNOWN_POINT

out = Path(sys.argv[1])
pdf = render_report(known_snapshot(), known_context())
out.write_bytes(pdf)
print("POINT", format_snapshot_number(KNOWN_POINT))
print("BYTES", len(pdf))
print("PREFIX", pdf[:4])
"""


def test_library_launch_twice_consistent(tmp_path):
    SCRATCH.mkdir(parents=True, exist_ok=True)
    outputs = [SCRATCH / "render_report_run1.pdf", SCRATCH / "render_report_run2.pdf"]
    extracted = []
    for path in outputs:
        proc = subprocess.run(
            [sys.executable, "-c", SCRIPT, str(path)],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
        assert path.exists() and path.stat().st_size > 0
        pdf = path.read_bytes()
        assert pdf.startswith(b"%PDF")
        frozen = parse_frozen_lines(extract_pdf_text(pdf))
        extracted.append(frozen["MP1_POINT"])
    assert extracted[0] == extracted[1]
    assert extracted[0] == "350000"
    assert float(extracted[0]) == KNOWN_POINT
