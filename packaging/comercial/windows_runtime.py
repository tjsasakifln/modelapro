"""Bind the frozen renderer to configuration shipped inside the bundle."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _early_log(message: str) -> None:
    try:
        if os.name == "nt":
            base = os.environ.get("LOCALAPPDATA") or str(
                Path.home() / "AppData" / "Local"
            )
            log_dir = Path(base) / "MODELAPro" / "logs"
        else:
            log_dir = Path.home() / ".local" / "share" / "modelapro" / "logs"
        if "program files" in str(log_dir).lower():
            return
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "startup.log").open("a", encoding="utf-8") as handle:
            handle.write(f"windows_runtime pid={os.getpid()} {message}\n")
    except OSError:
        pass


_early_log("begin")
bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
fontconfig_file = bundle_root / "native-runtime" / "fontconfig" / "fonts.conf"
if not fontconfig_file.is_file():
    _early_log(f"missing fontconfig at {fontconfig_file}")
    raise RuntimeError("bundled fontconfig configuration is absent")
os.environ["FONTCONFIG_FILE"] = str(fontconfig_file)
_early_log("fontconfig bound")
