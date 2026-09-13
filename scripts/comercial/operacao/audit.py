"""Invoke pip-audit with a machine-readable report and fail closed."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def audit(python: str, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [python, "-m", "pip_audit", "--format", "json", "--output", str(output)], check=False
    )
    # pip-audit uses non-zero when vulnerabilities are found or it cannot audit.
    # Both conditions block a release until explicitly investigated.
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    return audit(args.python, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
