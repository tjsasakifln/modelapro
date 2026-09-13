"""Bind the frozen renderer to configuration shipped inside the bundle."""

from __future__ import annotations

import os
import sys
from pathlib import Path


bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
fontconfig_file = bundle_root / "native-runtime" / "fontconfig" / "fonts.conf"
if not fontconfig_file.is_file():
    raise RuntimeError("bundled fontconfig configuration is absent")
os.environ["FONTCONFIG_FILE"] = str(fontconfig_file)
