"""Regenerate constraints/linux-py3.txt from a clean pip install of this project."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from .packaging_meta import commercial_build_specs, requirement_name, runtime_dependency_specs, source_root


def _run(cmd: list[str]) -> str:
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return completed.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Interpreter used to create the throwaway venv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="explicit target, e.g. constraints/windows-py312-x64.txt on the Windows build host",
    )
    parser.add_argument(
        "--commercial-build",
        action="store_true",
        help="regenerate constraints/commercial-build.txt from the release-tools extra",
    )
    args = parser.parse_args(argv)
    root = source_root()
    out = (args.output.resolve() if args.output else
           root / "constraints" / ("commercial-build.txt" if args.commercial_build else "linux-py3.txt"))
    extra = "commercial-build" if args.commercial_build else "dev"
    with tempfile.TemporaryDirectory(prefix="modelapro-c15-lock-") as tmp:
        venv = Path(tmp) / "venv"
        subprocess.run([args.python, "-m", "venv", str(venv)], check=True)
        if sys.platform.startswith("win"):
            python = venv / "Scripts" / "python.exe"
        else:
            python = venv / "bin" / "python"
        subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
        subprocess.run(
            [str(python), "-m", "pip", "install", str(root) + f"[{extra}]"],
            check=True,
        )
        freeze = _run([str(python), "-m", "pip", "freeze", "--all"])
    direct_specs = commercial_build_specs(root) if args.commercial_build else runtime_dependency_specs(root)
    direct = ", ".join(sorted(requirement_name(spec) for spec in direct_specs))
    lines = [
        "# Locked from a clean venv. Update with:",
        "#   python -m c15_local.update_constraints" + (" --commercial-build" if args.commercial_build else ""),
        "# Do not hand-edit pins without re-running the installer.",
        f"# python: {sys.version.split()[0]}",
        f"# direct runtime: {direct}",
        "",
    ]
    for raw in freeze.splitlines():
        if " @ " in raw or raw.startswith("-e "):
            continue
        name = requirement_name(raw)
        if name == "modelapro":
            continue
        lines.append(raw)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"Wrote {out} ({sum(1 for line in lines if line and not line.startswith('#'))} pins)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
