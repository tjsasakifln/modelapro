"""Provenance helpers for the C12 evidence dossier (lote MP-20260911).

This module is the exclusive owner of hashing, path safety, numeric encoding,
completeness statuses, and CSV formula-neutralization primitives used by
``modules.evidence_bundle``. It never loads pickle, never eval/exec's package
text, and never attaches market datasets to log or telemetry payloads.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union


SCHEMA_VERSION_MP = "MP/1"
BUNDLE_VERSION = "C12/1"

COMPLETENESS_PRESENT = "presente"
COMPLETENESS_DECLARED = "declarado"
COMPLETENESS_VERIFIED = "verificado"
COMPLETENESS_MISSING = "faltante"
COMPLETENESS_STATUSES = (
    COMPLETENESS_PRESENT,
    COMPLETENESS_DECLARED,
    COMPLETENESS_VERIFIED,
    COMPLETENESS_MISSING,
)

# Spreadsheet formula / injection prefixes (ASCII + common fullwidth forms).
FORMULA_PREFIXES: Tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r", "\n")
FULLWIDTH_FORMULA_PREFIXES: Tuple[str, ...] = ("＝", "＋", "－", "＠")

FORBIDDEN_LOG_KEYS = frozenset(
    {
        "raw_frame",
        "parsed_frame",
        "base_frame",
        "dataframe",
        "X",
        "y",
        "rows",
        "records",
        "dataset",
        "source_bytes",
        "file_bytes",
        "file_content",
        "identification_df",
    }
)

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_SAFE_NAME_MAX = 120

PathLike = Union[str, Path]


def sha256_bytes(data: bytes) -> str:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("sha256_bytes expects bytes")
    return hashlib.sha256(bytes(data)).hexdigest()


def sha256_file(path: PathLike) -> str:
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(obj: Any) -> str:
    """UTF-8 JSON with sorted keys and a trailing newline (deterministic)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2, default=_json_default) + "\n"


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return {"kind": "decimal", "text": format(obj, "f")}
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def write_text_utf8(path: PathLike, text: str) -> int:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    p.write_bytes(data)
    return len(data)


def write_json(path: PathLike, obj: Any) -> int:
    return write_text_utf8(path, canonical_json(obj))


def write_bytes_atomic(path: PathLike, data: bytes) -> int:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, p)
    return len(data)


def encode_number(value: Any) -> Optional[Dict[str, str]]:
    """Encode a number without rounding to display precision.

    Integers stay exact. IEEE float64 values keep an ``ieee_hex`` round-trip
    plus a decimal ``text`` for inspection. Decimal values keep their digits.
    Non-finite values are rejected (they cannot appear in MP/1 JSON).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("boolean is not a numeric evidence value")
    if isinstance(value, int):
        return {"kind": "int", "text": str(value)}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite Decimal rejected")
        return {"kind": "decimal", "text": format(value, "f")}
    if isinstance(value, str):
        parsed = Decimal(value)
        if not parsed.is_finite():
            raise ValueError("non-finite numeric text rejected")
        return {"kind": "decimal", "text": value}
    fv = float(value)
    if not math.isfinite(fv):
        raise ValueError("non-finite numbers cannot enter evidence")
    return {
        "kind": "float64",
        "text": format(fv, ".17g"),
        "ieee_hex": fv.hex(),
    }


def decode_number(encoded: Any) -> Any:
    """Inverse of ``encode_number``. Float64 uses ieee_hex when present."""
    if encoded is None:
        return None
    if isinstance(encoded, bool):
        raise TypeError("boolean is not a numeric evidence value")
    if isinstance(encoded, int):
        return encoded
    if isinstance(encoded, float):
        if not math.isfinite(encoded):
            raise ValueError("non-finite numbers cannot enter evidence")
        return encoded
    if isinstance(encoded, Decimal):
        return encoded
    if isinstance(encoded, str):
        if encoded.startswith("0x") or encoded.startswith("-0x"):
            return float.fromhex(encoded)
        return Decimal(encoded)
    if isinstance(encoded, Mapping):
        kind = encoded.get("kind")
        text = encoded.get("text")
        ieee = encoded.get("ieee_hex")
        if kind == "int":
            return int(text)
        if kind == "decimal":
            return Decimal(text)
        if kind == "float64" and ieee:
            return float.fromhex(str(ieee))
        if text is not None:
            if kind == "float64":
                return float(text)
            return Decimal(str(text))
    raise TypeError(f"unrecognized numeric encoding: {encoded!r}")


def number_as_float64(value: Any) -> float:
    decoded = decode_number(value) if isinstance(value, (Mapping, str)) else value
    if isinstance(decoded, Decimal):
        fv = float(decoded)
    else:
        fv = float(decoded)
    if not math.isfinite(fv):
        raise ValueError("non-finite numbers cannot enter evidence")
    return fv


def number_to_cell_text(value: Any) -> str:
    """Cell text that preserves monetary / coefficient precision."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite numbers cannot enter evidence CSV")
        return format(value, ".17g")
    if isinstance(value, Mapping) and "text" in value:
        return str(value["text"])
    return str(value)


def is_formula_cell(text: str) -> bool:
    if text is None:
        return False
    if not isinstance(text, str):
        text = str(text)
    if text == "":
        return False
    first = text[0]
    if first in FORMULA_PREFIXES or first in FULLWIDTH_FORMULA_PREFIXES:
        return True
    # Unicode Cf / control that Excel may strip before seeing '='.
    stripped = text.lstrip("\ufeff\u200b\u200c\u200d")
    if stripped and stripped is not text:
        return is_formula_cell(stripped)
    return False


def neutralize_formula_cell(text: str) -> str:
    """Safe visualization form: prefix so spreadsheets treat the cell as text.

    The raw evidence file is never passed through this function.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    if not is_formula_cell(text):
        return text
    if text.startswith("'"):
        return text
    return "'" + text


def sanitize_internal_name(name: str, *, fallback: str = "unnamed") -> str:
    """Safe path-component / internal identifier (no traversal, no spaces)."""
    if name is None:
        return fallback
    text = unicodedata.normalize("NFKC", str(name)).strip()
    text = text.replace("\\", "_").replace("/", "_")
    text = _SAFE_NAME_RE.sub("_", text)
    text = text.strip("._")
    if text in {"", ".", ".."}:
        return fallback
    if len(text) > _SAFE_NAME_MAX:
        digest = hashlib.sha256(str(name).encode("utf-8")).hexdigest()[:8]
        text = text[: _SAFE_NAME_MAX - 9] + "_" + digest
    return text


def resolve_inside(root: PathLike, relative: str) -> Path:
    """Resolve ``relative`` under ``root`` or raise on traversal / absolute path."""
    root_path = Path(root).resolve()
    if relative is None:
        raise ValueError("relative path is required")
    rel = str(relative).replace("\\", "/")
    if rel.startswith("/") or rel.startswith("~") or (len(rel) >= 2 and rel[1] == ":"):
        raise ValueError(f"absolute path rejected: {relative!r}")
    if "\x00" in rel:
        raise ValueError("null byte in path rejected")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError(f"path traversal rejected: {relative!r}")
    if not parts:
        raise ValueError("empty relative path rejected")
    candidate = root_path.joinpath(*parts).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise ValueError(f"path escapes bundle root: {relative!r}") from exc
    return candidate


def iter_regular_files(root: PathLike) -> List[Path]:
    root_path = Path(root)
    files = [p for p in root_path.rglob("*") if p.is_file()]
    files.sort(key=lambda p: p.relative_to(root_path).as_posix())
    return files


def relative_posix(root: PathLike, path: PathLike) -> str:
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


def refuse_code_execution(reason: str) -> None:
    raise RuntimeError(f"refused to execute untrusted content: {reason}")


def looks_like_pickle(data: bytes) -> bool:
    if not data:
        return False
    # Classic pickle opcodes start with protocol marker \x80 or ASCII pickle.
    if data[:1] == b"\x80":
        return True
    if data[:1] in (b"(", b"]", b"}", b"l", b"c") and b"\n" in data[:40]:
        # Heuristic only; callers still must never pickle.loads.
        if b"pickle" in data[:200].lower() or data.startswith(b"(dp") or data.startswith(b"(lp"):
            return True
    return False


def strip_dataset_from_log_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Drop in-memory frames / file bytes so logs never carry the dataset."""
    safe: Dict[str, Any] = {}
    for key, value in payload.items():
        if key in FORBIDDEN_LOG_KEYS:
            safe[key] = "<redacted: dataset not logged>"
            continue
        if key.endswith("_bytes") or key.endswith("_frame") or key.endswith("_df"):
            safe[key] = "<redacted: dataset not logged>"
            continue
        if isinstance(value, (bytes, bytearray)):
            safe[key] = f"<redacted bytes n={len(value)} sha256={sha256_bytes(bytes(value))[:12]}>"
            continue
        safe[key] = value
    return safe


class CompletenessLedger:
    """Tracks whether each dossier component is present, declared, verified, or missing."""

    def __init__(self) -> None:
        self._items: Dict[str, Dict[str, Any]] = {}

    def set(
        self,
        component: str,
        status: str,
        *,
        notes: str = "",
        declared: bool = False,
        source: Optional[str] = None,
        evidence: Optional[Mapping[str, Any]] = None,
        absence_kind: Optional[str] = None,
    ) -> None:
        if status not in COMPLETENESS_STATUSES:
            raise ValueError(f"invalid completeness status {status!r}")
        item = {
            "component": component,
            "status": status,
            "declared": bool(declared) or status in {COMPLETENESS_DECLARED, COMPLETENESS_VERIFIED},
            "notes": notes,
            "source": source,
            "evidence": dict(evidence) if evidence else {},
        }
        if absence_kind:
            item["absence_kind"] = str(absence_kind)
        elif status == COMPLETENESS_MISSING:
            item["absence_kind"] = "not_provided"
        self._items[component] = item

    def get(self, component: str) -> Optional[Dict[str, Any]]:
        item = self._items.get(component)
        return dict(item) if item else None

    def status_of(self, component: str) -> str:
        item = self._items.get(component)
        return item["status"] if item else COMPLETENESS_MISSING

    def missing(self) -> List[str]:
        return [name for name, item in self._items.items() if item["status"] == COMPLETENESS_MISSING]

    def to_list(self) -> List[Dict[str, Any]]:
        return [self._items[k] for k in sorted(self._items)]

    def to_dict(self) -> Dict[str, Any]:
        counts = {s: 0 for s in COMPLETENESS_STATUSES}
        for item in self._items.values():
            counts[item["status"]] += 1
        return {
            "schema_version": SCHEMA_VERSION_MP,
            "bundle_version": BUNDLE_VERSION,
            "counts": counts,
            "missing": self.missing(),
            "items": self.to_list(),
        }


def policy_id_from_mapping(policies: Mapping[str, Any]) -> str:
    payload = canonical_json(policies).encode("utf-8")
    return sha256_bytes(payload)


def schema_id_from_mapping(feature_schema: Mapping[str, Any]) -> str:
    payload = canonical_json(feature_schema).encode("utf-8")
    return sha256_bytes(payload)
