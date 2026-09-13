"""Independent analytic oracles for C16.

These helpers never import production modules. Expected values come from
literal arithmetic, locale rules documented here, or explicit MP/1
invariants. Callers compare SUT observations against these functions —
they must not assign expected values from the code under test.
"""
from __future__ import annotations

import csv
import io
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ABNT NBR 14653-2:2011 is the edition cited by the audited codebase for
# urban-property valuation. Exact table wording was not independently
# confirmed from the local PDF in this campaign (extraction failed /
# document not in the git tree). Interval bounds below are therefore
# labelled pending — they match the campaign requirement to *distinguish*
# faixa ampliada from efeito monetário, not a claim that NBR item 4 is
# the monetary-effect test.
NBR_14653_2 = {
    "standard": "ABNT NBR 14653-2",
    "edition": "2011",
    "verification_status": "pending",
    "note": (
        "Item 4 / characteristic-interval language is cited from the "
        "audited implementation comments and campaign brief. C16 does not "
        "declare a verified oracle that item 4 equals monetary effect, nor "
        "that 0.5*min–2*max is the exclusive normative rule."
    ),
}

FIXTURES_DIR = Path(__file__).resolve().parent

# Independently counted missing-target pattern for f01_missing_target.csv:
# 30 rows, area = 50 + 5*i, preco = 1000*area except i in MISSING_TARGET_ROWS.
MISSING_TARGET_ROWS = (0, 5, 10, 15, 20)
F01_N_RECEIVED = 30
F01_N_OBSERVED_TARGET = F01_N_RECEIVED - len(MISSING_TARGET_ROWS)  # 25


def math_sqrt(value: float) -> float:
    """Principal square root on the reals. sqrt(0) is 0, not a domain error."""
    if value < 0:
        raise ValueError("sqrt is undefined for negative reals in this oracle")
    return math.sqrt(value)


def parse_number(text: str, locale: str) -> float:
    """Locale-aware numeric parse. Ambiguous auto-detect is not this function.

    Independent rules (not copied from modules.utils.safe_float_conversion):
    - Strip an optional leading/trailing 'R$' and surrounding whitespace.
    - pt-BR: '.' is thousands, ',' is decimal → remove thousands, ',' → '.'.
    - en-US: ',' is thousands, '.' is decimal → remove thousands, keep '.'.
    """
    if locale not in {"pt-BR", "en-US"}:
        raise ValueError(f"locale must be pt-BR or en-US, got {locale!r}")
    raw = str(text).strip()
    raw = re.sub(r"R\$\s*", "", raw).strip()
    if locale == "pt-BR":
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        # no decimal comma: dots are thousands
        elif raw.count(".") > 1:
            raw = raw.replace(".", "")
        elif raw.count(".") == 1:
            # Ambiguous single-dot without a comma: caller must not use
            # parse_number with pt-BR on that token — see is_ambiguous_number.
            raw = raw.replace(".", "")
        return float(raw)
    # en-US
    raw = raw.replace(",", "")
    return float(raw)


def is_ambiguous_number(text: str) -> bool:
    """True when thousands/decimal grouping cannot be decided without locale.

    '1.234' is 1234 in pt-BR grouping or 1.234 in en-US decimal.
    '1,234' is 1.234 in pt-BR decimal or 1234 in en-US grouping.
    """
    s = re.sub(r"R\$\s*", "", str(text).strip())
    if re.fullmatch(r"\d{1,3}\.\d{3}", s):
        return True
    if re.fullmatch(r"\d{1,3},\d{3}", s):
        return True
    return False


def count_observed_target(rows: Sequence[Dict[str, Any]], target_col: str) -> int:
    """Count rows whose target cell is a non-empty, non-null token."""
    n = 0
    for row in rows:
        val = row.get(target_col)
        if val is None:
            continue
        if isinstance(val, float) and math.isnan(val):
            continue
        text = str(val).strip()
        if text == "" or text.lower() in {"nan", "none", "null"}:
            continue
        n += 1
    return n


def faixa_ampliada(
    value: float, sample_min: float, sample_max: float
) -> str:
    """Classify a predictor against the sample interval and a 0.5–2 extended band.

    Returns one of: in_sample, extended, outside_extended.
    The 0.5*min / 2*max band is the *faixa ampliada* used by the audited
    code; NBR wording for that factor is pending (see NBR_14653_2).
    """
    if sample_min <= value <= sample_max:
        return "in_sample"
    ext_min = 0.5 * sample_min
    ext_max = 2.0 * sample_max
    if ext_min <= value <= ext_max:
        return "extended"
    return "outside_extended"


def efeito_monetario(
    predicted: float, sample_y_min: float, sample_y_max: float
) -> str:
    """Classify a predicted price against the sample target range.

    Distinct from faixa_ampliada: a subject can sit inside an extended
    predictor interval while the implied price is outside the sample
    prices, and vice versa.
    """
    if sample_y_min <= predicted <= sample_y_max:
        return "price_in_sample"
    return "price_outside_sample"


def empty_candidate_cols_is_none_authorized() -> str:
    """MP/1 invariant: candidate_cols=[] authorizes no predictors, never all."""
    return "explicit_error_no_authorized_variables"


def unknown_unit_must_remain_pending() -> str:
    return "pending"


def unknown_date_must_remain_pending() -> str:
    return "pending"


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def f01_independent_n(path: Optional[Path] = None) -> Dict[str, int]:
    path = path or (FIXTURES_DIR / "f01_missing_target.csv")
    rows = read_csv_rows(path)
    return {
        "received": len(rows),
        "observed_target": count_observed_target(rows, "preco"),
    }


def f01_observed_mean_preco(path: Optional[Path] = None) -> float:
    """Mean of *observed* target cells only. Missing cells are not 0 and not imputed."""
    path = path or (FIXTURES_DIR / "f01_missing_target.csv")
    values: List[float] = []
    for row in read_csv_rows(path):
        text = (row.get("preco") or "").strip()
        if text == "":
            continue
        values.append(float(text))
    if not values:
        raise ValueError("no observed target values")
    return sum(values) / len(values)


def linear_price(area: float, slope: float = 1000.0, intercept: float = 0.0) -> float:
    return intercept + slope * area


def generate_large_market_csv(n_rows: int, seed: int = 16) -> bytes:
    """Deterministic synthetic market table. No client data."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["area", "quartos", "preco"])
    for i in range(n_rows):
        area = 50 + (i * 3) % 151
        quartos = 1 + (i + seed) % 4
        preco = 800 * area + 12000 * quartos
        writer.writerow([area, quartos, preco])
    return buf.getvalue().encode("utf-8")


def generate_wide_bytes(n_bytes: int) -> bytes:
    """CSV whose payload exceeds n_bytes. Header + repeating synthetic rows."""
    header = b"area,quartos,preco\n"
    row = b"80,2,160000\n"
    chunks = [header]
    size = len(header)
    i = 0
    while size < n_bytes:
        # vary slightly so it is a real table, still synthetic
        line = f"{50 + (i % 100)},{1 + (i % 4)},{100000 + i}\n".encode("utf-8")
        chunks.append(line)
        size += len(line)
        i += 1
    return b"".join(chunks)
