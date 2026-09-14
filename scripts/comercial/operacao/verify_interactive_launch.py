"""Observe Explorer/shortcut launch; join the browser the PRODUCT opened.

This is not verify_installed_ui.py: it must not create Chromium and page.goto
before proving the product opened the default-browser URL itself.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _ps(script: str) -> str:
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout or "powershell failed")
    return completed.stdout


def _browser_cmds() -> list[str]:
    raw = _ps(
        r"""
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'chrome|msedge|firefox|iexplore' -and $_.CommandLine } |
  ForEach-Object { $_.CommandLine }
"""
    )
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _product_cmds() -> list[str]:
    raw = _ps(
        r"""
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'MODELA-PRO.exe' } |
  ForEach-Object { '{0}|{1}|{2}' -f $_.ProcessId, $_.ParentProcessId, $_.CommandLine }
"""
    )
    return [line.strip() for line in raw.splitlines() if line.strip()]


def observe(shortcut: Path, evidence: Path, timeout: float = 45.0) -> dict[str, Any]:
    evidence.mkdir(parents=True, exist_ok=True)
    before_browsers = set(_browser_cmds())
    before_product = set(_product_cmds())
    result: dict[str, Any] = {
        "schema_version": "MP-COM-INTERACTIVE-LAUNCH/1",
        "shortcut": str(shortcut),
        "status": "RUNNING",
        "product_opened_browser": False,
        "tester_created_browser": False,
        "flashes": [],
        "new_product_commands": [],
        "matched_url": None,
    }
    _ps(f'Start-Process -FilePath "explorer.exe" -ArgumentList \'"{shortcut}"\'')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        product = set(_product_cmds()) - before_product
        browsers = set(_browser_cmds()) - before_browsers
        result["new_product_commands"] = sorted(product)
        for line in product:
            if "whoami" in line.lower() or "icacls" in line.lower():
                result["flashes"].append(line)
        for cmd in browsers:
            if "127.0.0.1" in cmd or "localhost" in cmd:
                result["product_opened_browser"] = True
                result["matched_url"] = cmd
                result["status"] = "PASS"
                (evidence / "interactive-launch.json").write_text(
                    json.dumps(result, indent=2) + "\n", encoding="utf-8"
                )
                return result
        time.sleep(0.5)
    result["status"] = "FAIL"
    (evidence / "interactive-launch.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    raise SystemExit(f"product did not open a browser URL: {result}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shortcut", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args(argv)
    observe(Path(args.shortcut), Path(args.evidence), timeout=args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
