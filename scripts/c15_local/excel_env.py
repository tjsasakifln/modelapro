"""Direct Excel/CSV engine probe for announced input formats."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class EngineStatus:
    name: str
    import_name: str
    available: bool
    detail: str


def _probe_module(name: str, import_name: str) -> EngineStatus:
    try:
        module = __import__(import_name)
    except ImportError as exc:
        return EngineStatus(
            name=name,
            import_name=import_name,
            available=False,
            detail=f"missing direct dependency {import_name}: {exc}",
        )
    version = getattr(module, "__version__", "unknown")
    return EngineStatus(
        name=name,
        import_name=import_name,
        available=True,
        detail=f"{import_name} {version}",
    )


def probe_excel_engines() -> Dict[str, EngineStatus]:
    """CSV uses pandas; .xlsx requires openpyxl; .xls requires xlrd. Direct, not transitive."""
    return {
        "csv": _probe_module("csv", "pandas"),
        "xlsx": _probe_module("xlsx", "openpyxl"),
        "xls": _probe_module("xls", "xlrd"),
    }
