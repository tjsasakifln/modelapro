"""Shared helpers for C16 acceptance tests.

Import production modules only at the call site of each test. This file
loads independent oracles and optional MP/1 exports — it does not
reimplement DataLoader, Transformer, or the search.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
INDEPENDENT = ROOT / "tests" / "fixtures" / "independent"

import sys

if str(INDEPENDENT) not in sys.path:
    sys.path.insert(0, str(INDEPENDENT))

import oracles  # noqa: E402  (canonical independent oracles)


def load_mapping() -> dict:
    with (INDEPENDENT / "mapping.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def load_request_specs() -> dict:
    with (INDEPENDENT / "request_specs.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def fixture_bytes(name: str) -> bytes:
    return (INDEPENDENT / name).read_bytes()


def fixture_path(name: str) -> Path:
    return INDEPENDENT / name


def try_export(module_name: str, attr: str) -> Optional[Any]:
    try:
        mod = importlib.import_module(module_name)
    except ImportError:
        return None
    return getattr(mod, attr, None)


def require_export(module_name: str, attr: str, owner: str):
    obj = try_export(module_name, attr)
    assert obj is not None, (
        f"UNMET_DEPENDENCY:{owner} missing {module_name}.{attr}"
    )
    return obj


def route_paths(app) -> list:
    paths = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if path:
            paths.append(path)
    return paths


def unpack_transform(result):
    """apply_transformation is a 2-tuple at the frozen MP/1 seam."""
    if isinstance(result, tuple) and len(result) >= 2:
        return result[0], bool(result[1])
    raise AssertionError(
        f"apply_transformation must remain a 2-tuple-compatible result, got {type(result)}"
    )
