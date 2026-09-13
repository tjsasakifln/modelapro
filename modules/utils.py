import datetime
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

# Unicode spaces that appear as thousands separators or padding in spreadsheets.
_UNICODE_SPACES = dict.fromkeys(
    map(ord, "\u00a0\u202f\u2007\u2009\u200a\u2008\u2006\ufeff"),
    " ",
)
_CURRENCY_PREFIX = re.compile(
    r"^(R\$|US\$|USD|BRL|EUR|GBP|€|£|\$)\s*",
    re.IGNORECASE,
)
_CURRENCY_SUFFIX = re.compile(
    r"\s*(R\$|US\$|USD|BRL|EUR|GBP|€|£|\$)$",
    re.IGNORECASE,
)
_MISSING_TOKENS = {
    "",
    "-",
    "--",
    "na",
    "n/a",
    "nan",
    "null",
    "none",
    "nil",
    "#n/d",
    "#nd",
    "#n/a",
    "s/n",
    "...",
    "sem valor",
    "ausente",
}
_INF_TOKENS = {"inf", "+inf", "infinity", "-inf", "-infinity"}
_LEADING_ZERO_RE = re.compile(r"^0\d")
_CEP_RE = re.compile(r"^\d{5}-?\d{3}$")
_DATE_RE = re.compile(
    r"^("
    r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?"
    r"|"
    r"\d{2}/\d{2}/\d{4}"
    r"|"
    r"\d{2}-\d{2}-\d{4}"
    r")$"
)
_PHONE_SEP_RE = re.compile(r"[\(\)\-\s]")
_SCIENTIFIC_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?e[+-]?\d+$", re.IGNORECASE)
_DIGIT_SPACE_RE = re.compile(r"(?<=\d) (?=\d)")

NON_QUANTITATIVE_ROLES = frozenset({"identifier", "source", "date", "excluded"})
IDENTIFIER_NAME_HINTS = frozenset(
    {
        "id",
        "codigo",
        "código",
        "identifier",
        "identificador",
        "cep",
        "telefone",
        "fone",
        "celular",
        "phone",
        "cpf",
        "cnpj",
        "rg",
        "matricula",
        "matrícula",
    }
)


def clean_column_name(name: str) -> str:
    """
    Cleans a column name by removing special characters and converting to snake_case.

    Meaning is frozen for API/worker callers (they clean target/candidate names
    with this function). The reversible ingest map lives in build_column_map.
    """
    # Remove accents and special chars
    name = re.sub(r"[^\w\s]", "", name)
    # Convert to snake_case
    name = name.lower().strip().replace(" ", "_")
    return name


def validate_dataframe(df: pd.DataFrame) -> bool:
    """
    Validates if the dataframe is not empty and has columns.
    """
    if df is None or df.empty:
        return False
    return True


@dataclass(frozen=True)
class NumericParse:
    status: str
    value: Optional[float]
    original: Any
    locale_applied: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=dict)


def normalize_spaces(text: str) -> str:
    return text.translate(_UNICODE_SPACES)


def is_missing_token(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (ValueError, TypeError):
        pass
    if isinstance(value, str):
        token = normalize_spaces(value).strip().lower()
        return token in _MISSING_TOKENS
    return False


def parse_numeric_token(value: Any, locale: str = "auto") -> NumericParse:
    """Parse a scalar without guessing locale.

    Ambiguous tokens such as ``1.234`` with locale ``auto`` stay unconverted
    (magnitude unchanged — dots are not stripped). Already-numeric values keep
    their magnitude. Non-finite numbers are not turned into substitutes.
    """
    if is_missing_token(value):
        return NumericParse("missing", None, value, None, {"reason": "missing"})

    if isinstance(value, bool):
        return NumericParse(
            "non_numeric",
            None,
            value,
            None,
            {"reason": "boolean_not_quantitative"},
        )

    if isinstance(value, (datetime.datetime, datetime.date, pd.Timestamp)):
        return NumericParse(
            "non_numeric",
            None,
            value,
            None,
            {"reason": "datetime_not_quantitative"},
        )

    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        if not np.isfinite(number):
            return NumericParse(
                "non_finite",
                None,
                value,
                None,
                {"raw": repr(value)},
            )
        return NumericParse("already_numeric", number, value, None, {"magnitude_preserved": True})

    if not isinstance(value, str):
        try:
            number = float(value)
        except (ValueError, TypeError):
            return NumericParse("non_numeric", None, value, None, {"type": type(value).__name__})
        if not np.isfinite(number):
            return NumericParse("non_finite", None, value, None, {})
        return NumericParse("already_numeric", number, value, None, {"magnitude_preserved": True})

    stripped = normalize_spaces(value).strip()
    if not stripped:
        return NumericParse("missing", None, value, None, {"reason": "blank"})

    currency = None
    body = stripped
    prefix = _CURRENCY_PREFIX.match(body)
    if prefix:
        currency = prefix.group(1)
        body = body[prefix.end() :]
    suffix = _CURRENCY_SUFFIX.search(body)
    if suffix:
        currency = currency or suffix.group(1)
        body = body[: suffix.start()]
    body = body.strip()
    body = _DIGIT_SPACE_RE.sub("", body)

    sign = 1.0
    if body.startswith("+"):
        body = body[1:]
    elif body.startswith("-"):
        sign = -1.0
        body = body[1:]
    body = body.strip()
    if not body:
        return NumericParse("malformed", None, value, None, {"reason": "sign_only"})

    lower = body.lower()
    if lower in _INF_TOKENS:
        return NumericParse("non_finite", None, value, locale if locale != "auto" else None, {"token": lower})

    if _SCIENTIFIC_RE.match(body):
        try:
            number = sign * float(body)
        except ValueError:
            return NumericParse("malformed", None, value, None, {"reason": "scientific"})
        if not np.isfinite(number):
            return NumericParse("non_finite", None, value, None, {"token": body})
        return NumericParse("parsed", number, value, "scientific", {"currency": currency})

    locale_key = locale or "auto"
    if locale_key == "pt-BR":
        return _finalize_locale_parse(value, body, sign, currency, "pt-BR", ",", ".")
    if locale_key == "en-US":
        return _finalize_locale_parse(value, body, sign, currency, "en-US", ".", ",")
    if locale_key != "auto":
        return NumericParse(
            "malformed",
            None,
            value,
            None,
            {"reason": "unsupported_locale", "locale": locale_key},
        )
    return _parse_auto(value, body, sign, currency)


def _finalize_locale_parse(
    original: Any,
    body: str,
    sign: float,
    currency: Optional[str],
    locale: str,
    decimal_sep: str,
    thousands_sep: str,
) -> NumericParse:
    if not re.fullmatch(r"[0-9.,]+", body):
        return NumericParse("non_numeric", None, original, locale, {"reason": "not_digits"})
    try:
        number = sign * _apply_separators(body, decimal_sep, thousands_sep)
    except ValueError as exc:
        return NumericParse("malformed", None, original, locale, {"reason": str(exc)})
    if not np.isfinite(number):
        return NumericParse("non_finite", None, original, locale, {})
    return NumericParse("parsed", number, original, locale, {"currency": currency})


def _parse_auto(original: Any, body: str, sign: float, currency: Optional[str]) -> NumericParse:
    if not re.fullmatch(r"[0-9.,]+", body):
        return NumericParse("non_numeric", None, original, None, {"reason": "not_digits"})

    has_dot = "." in body
    has_comma = "," in body
    if has_dot and has_comma:
        if body.rfind(",") > body.rfind("."):
            return _finalize_locale_parse(original, body, sign, currency, "pt-BR", ",", ".")
        return _finalize_locale_parse(original, body, sign, currency, "en-US", ".", ",")

    if has_comma and not has_dot:
        return _auto_single_separator(original, body, sign, currency, ",", "pt-BR", "en-US")
    if has_dot and not has_comma:
        return _auto_single_separator(original, body, sign, currency, ".", "en-US", "pt-BR")

    try:
        number = sign * float(body)
    except ValueError:
        return NumericParse("malformed", None, original, None, {"reason": "plain_digits"})
    return NumericParse("parsed", number, original, None, {"currency": currency})


def _auto_single_separator(
    original: Any,
    body: str,
    sign: float,
    currency: Optional[str],
    sep: str,
    decimal_locale: str,
    thousands_locale: str,
) -> NumericParse:
    parts = body.split(sep)
    if any(p == "" for p in parts):
        return NumericParse("malformed", None, original, None, {"reason": "empty_group", "sep": sep})
    if len(parts) == 1:
        return NumericParse("parsed", sign * float(parts[0]), original, None, {"currency": currency})
    if len(parts) == 2:
        left, right = parts
        if not left.isdigit() or not right.isdigit():
            return NumericParse("malformed", None, original, None, {"reason": "non_digit_group"})
        if len(right) in (1, 2):
            number = sign * float(f"{left}.{right}")
            return NumericParse(
                "parsed",
                number,
                original,
                decimal_locale if sep == "," else "decimal_point",
                {"currency": currency, "reason": "fraction_1_or_2_digits"},
            )
        if len(right) > 3:
            number = sign * float(f"{left}.{right}")
            return NumericParse(
                "parsed",
                number,
                original,
                "decimal_point" if sep == "." else decimal_locale,
                {"currency": currency, "reason": "fraction_gt_3_not_thousands"},
            )
        pt_value = float(left + right) if sep == "." else float(f"{left}.{right}")
        en_value = float(f"{left}.{right}") if sep == "." else float(left + right)
        return NumericParse(
            "ambiguous",
            None,
            original,
            None,
            {
                "token": body,
                "separator": sep,
                "candidates": {"pt-BR": sign * pt_value, "en-US": sign * en_value},
                "currency": currency,
            },
        )
    if all(len(p) == 3 and p.isdigit() for p in parts[1:]) and parts[0].isdigit():
        number = sign * float("".join(parts))
        locale = thousands_locale
        return NumericParse("parsed", number, original, locale, {"currency": currency, "thousands_groups": True})
    return NumericParse("malformed", None, original, None, {"reason": "incoherent_groups", "sep": sep})


def _apply_separators(body: str, decimal_sep: str, thousands_sep: str) -> float:
    if thousands_sep and thousands_sep in body:
        if decimal_sep in body:
            integer, frac = body.rsplit(decimal_sep, 1)
            if decimal_sep in integer:
                raise ValueError("multiple_decimals")
            _assert_thousands(integer, thousands_sep)
            integer = integer.replace(thousands_sep, "")
            if not integer.isdigit() or not frac.isdigit():
                raise ValueError("non_digit_after_separators")
            return float(f"{integer}.{frac}")
        try:
            _assert_thousands(body, thousands_sep)
        except ValueError:
            if body.count(thousands_sep) == 1:
                left, right = body.split(thousands_sep, 1)
                if left.isdigit() and right.isdigit() and 1 <= len(right) <= 2:
                    return float(f"{left}.{right}")
            raise
        compact = body.replace(thousands_sep, "")
        if not compact.isdigit():
            raise ValueError("non_digit_thousands")
        return float(compact)
    if decimal_sep in body:
        if body.count(decimal_sep) > 1:
            raise ValueError("multiple_decimals")
        integer, frac = body.split(decimal_sep, 1)
        if integer == "" or not integer.isdigit() or not frac.isdigit():
            raise ValueError("invalid_decimal")
        return float(f"{integer}.{frac}")
    if not body.isdigit():
        raise ValueError("not_digits")
    return float(body)


def _assert_thousands(integer_part: str, sep: str) -> None:
    groups = integer_part.split(sep)
    if len(groups) <= 1:
        return
    if not groups[0].isdigit() or groups[0] == "":
        raise ValueError("invalid_thousands_head")
    for group in groups[1:]:
        if len(group) != 3 or not group.isdigit():
            raise ValueError("invalid_thousands_group")


def safe_float_conversion(value: Any, locale: str = "auto") -> Optional[float]:
    """
    Safely converts a value to float. Returns None if conversion fails.

    Does not strip every ``.`` (that inverted 123.45 → 12345 and 1.234 → 1234).
    Ambiguous tokens without a locale decision return None, leaving magnitude
    unchanged for the caller.
    """
    parsed = parse_numeric_token(value, locale=locale)
    if parsed.status in {"parsed", "already_numeric"}:
        return parsed.value
    return None


def format_currency(value: float) -> str:
    """
    Formats a float value as Brazilian currency.
    """
    try:
        return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(value)


def build_column_map(
    columns: Sequence[Any],
    reserved: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Reversible original → internal map, including collisions after cleanup."""
    used = set(reserved or [])
    original_to_internal: Dict[Any, str] = {}
    internal_to_original: Dict[str, Any] = {}
    entries: List[Dict[str, Any]] = []
    collisions: List[Dict[str, Any]] = []

    for position, original in enumerate(columns):
        rendered = original if isinstance(original, str) else str(original)
        base = clean_column_name(rendered)
        if not base:
            base = f"col_{position}"
        internal = base
        suffix = 2
        collided = False
        while internal in used:
            collided = True
            internal = f"{base}__{suffix}"
            suffix += 1
        if collided:
            collisions.append(
                {
                    "position": position,
                    "original": original,
                    "base": base,
                    "internal": internal,
                }
            )
        used.add(internal)
        original_to_internal[original] = internal
        internal_to_original[internal] = original
        entries.append(
            {
                "position": position,
                "original": original,
                "original_type": type(original).__name__,
                "original_repr": rendered,
                "internal": internal,
                "collision": collided,
            }
        )

    return {
        "original_to_internal": original_to_internal,
        "internal_to_original": internal_to_original,
        "entries": entries,
        "collisions": collisions,
    }


def looks_like_non_quantitative(values: Iterable[Any]) -> bool:
    """True when a column is a code/id/date/phone, not a magnitude.

    Presence of leading zeros, CEP, telephone or date shapes must not be
    overridden by "most values happen to parse as numbers".
    """
    observed = [v for v in values if not is_missing_token(v)]
    if not observed:
        return False
    if all(
        isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool)
        for v in observed
    ):
        return False
    if any(isinstance(v, (datetime.datetime, datetime.date, pd.Timestamp)) for v in observed):
        return True

    texts = [normalize_spaces(str(v)).strip() for v in observed]
    if any(_LEADING_ZERO_RE.match(t.replace(" ", "").replace("-", "")) for t in texts):
        return True
    if texts and all(_CEP_RE.match(t) for t in texts):
        return True
    if texts and all(_DATE_RE.match(t) for t in texts):
        return True

    def _is_phone(token: str) -> bool:
        digits = re.sub(r"\D", "", token)
        return len(digits) >= 8 and bool(_PHONE_SEP_RE.search(token))

    if texts and all(_is_phone(t) for t in texts):
        return True
    return False


def resolve_column_name(name: Any, column_map: Dict[str, Any]) -> Optional[str]:
    """Resolve a user-supplied name to an internal column name, or None."""
    if name is None or name == "":
        return None
    original_to_internal = column_map.get("original_to_internal") or {}
    internal_to_original = column_map.get("internal_to_original") or {}
    if name in original_to_internal:
        return original_to_internal[name]
    if name in internal_to_original:
        return name
    rendered = str(name)
    if rendered in original_to_internal:
        return original_to_internal[rendered]
    cleaned = clean_column_name(rendered)
    if cleaned in internal_to_original:
        return cleaned
    for entry in column_map.get("entries") or []:
        if entry.get("original") == name or entry.get("original_repr") == rendered:
            return entry["internal"]
        if entry.get("internal") == name or entry.get("internal") == cleaned:
            return entry["internal"]
    return None
