"""Synthetic fixtures and HTTP helpers for C17. Identified as synthetic."""

from __future__ import annotations

import io
import json
import math
import re
import time
from typing import Any, Mapping, Optional

from fastapi.testclient import TestClient

from backend.api import app
from backend.worker import peer_kind, resolve_peers
from modules.result_contract import SCHEMA_VERSION

TERMINAL = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
BAIRROS = ("Centro", "Sul", "Norte")


def fmt_ptbr(value: float) -> str:
    formatted = f"{value:,.2f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def market_rows(*, n: int = 24, missing_target_at: Optional[int] = 7):
    rows = []
    for i in range(n):
        area = 60.0 + i * 3.0
        bairro = BAIRROS[i % 3]
        price = 4000.0 * area + (25000.0 if bairro == "Centro" else 0.0) + i * 137.0
        rows.append(
            {
                "id": f"IM-{i + 1:02d}",
                "bairro": bairro,
                "area": area,
                "preco": None if missing_target_at is not None and i == missing_target_at else price,
            }
        )
    return rows


def analytic_linear_csv(
    *,
    n: int = 24,
    slope: float = 10000.0,
    intercept: float = 0.0,
    missing_target_at: Optional[int] = None,
    tag: str = "LIN",
) -> bytes:
    """Identified linear market: preco = intercept + slope * area. Synthetic."""
    lines = ["id;bairro;area;preco"]
    for i in range(n):
        area = 50.0 + i * 2.0
        price = intercept + slope * area
        price_txt = "" if missing_target_at is not None and i == missing_target_at else fmt_ptbr(price)
        lines.append(f"{tag}-{i + 1:03d};Centro;{fmt_ptbr(area)};{price_txt}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def analytic_point(*, area: float, slope: float = 10000.0, intercept: float = 0.0) -> float:
    return intercept + slope * float(area)


# Not on the analytic_linear_csv grid (50, 52, …, 50+2*(n-1)).
UNIQUE_SUBJECT_AREA = 73.5


def analytic_linear_sample_areas(*, n: int = 24) -> set[float]:
    return {50.0 + i * 2.0 for i in range(n)}


def analytic_bairro_csv(
    *,
    n_per: int = 16,
    slope: float = 10000.0,
    sul_add: float = 80000.0,
    tag: str = "AB",
) -> bytes:
    """Identified two-bairro market: Centro = slope*area; Sul = slope*area + sul_add."""
    lines = ["id;bairro;area;preco"]
    for i in range(n_per):
        area = 50.0 + i * 2.0
        price = slope * area
        lines.append(f"{tag}-C{i + 1:03d};Centro;{fmt_ptbr(area)};{fmt_ptbr(price)}")
    for i in range(n_per):
        area = 51.0 + i * 2.0
        price = slope * area + sul_add
        lines.append(f"{tag}-S{i + 1:03d};Sul;{fmt_ptbr(area)};{fmt_ptbr(price)}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def analytic_bairro_point(
    *,
    area: float,
    bairro: str,
    slope: float = 10000.0,
    sul_add: float = 80000.0,
) -> float:
    extra = sul_add if bairro == "Sul" else 0.0
    return slope * float(area) + extra


def pdf_frozen_fields(pdf_bytes: bytes) -> dict:
    from tests.c08_report.pdf_text import extract_pdf_text, parse_frozen_lines

    text = extract_pdf_text(pdf_bytes)
    frozen = parse_frozen_lines(text)
    return {"text": text, "frozen": frozen}


def assert_pdf_conclusion_point(pdf_bytes: bytes, expected: float, *, tol: float = 1.0) -> None:
    """Require the labeled conclusion field, not a digit substring of the annex."""
    parsed = pdf_frozen_fields(pdf_bytes)
    frozen = parsed["frozen"]
    raw = frozen.get("MP1_POINT")
    assert raw not in (None, "", "null"), f"MP1_POINT missing in frozen lines: {frozen}"
    # format_snapshot_number emits 735000 or 735000.5 — never a thousands grouping.
    observed = float(str(raw))
    assert math.isfinite(observed), raw
    assert abs(observed - float(expected)) < tol, f"MP1_POINT={raw!r} expected {expected}"
    assert "Estimativa pontual (snapshot.value.point)" in parsed["text"]


def ptbr_csv_bytes(*, n: int = 24, missing_target_at: Optional[int] = 7, tag: str = "A") -> bytes:
    lines = ["id;bairro;area;preco"]
    for row in market_rows(n=n, missing_target_at=missing_target_at):
        area = fmt_ptbr(row["area"])
        price = "" if row["preco"] is None else fmt_ptbr(row["preco"])
        lines.append(f"{row['id']};{row['bairro']};{area};{price}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def excel_bytes(*, n: int = 24, missing_target_at: Optional[int] = 7) -> bytes:
    import pandas as pd

    df = pd.DataFrame(market_rows(n=n, missing_target_at=missing_target_at))
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def request_spec(**overrides: Any) -> dict:
    spec = {
        "schema_version": SCHEMA_VERSION,
        "target_col": "preco",
        "candidate_cols": ["area", "bairro"],
        "roles": {
            "preco": "target",
            "area": "predictor",
            "bairro": "predictor",
            "id": "identifier",
        },
        "units": {"area": "m2", "preco": ""},
        "import_options": {"locale": "pt-BR", "delimiter": ";", "encoding": "utf-8"},
        "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
        "outlier_policy": {"mode": "report_only", "reviewed_exclusions": []},
        "search_policy": {
            "mode": "exact",
            "budget": 64,
            "objective": "aic",
            "seed": 17,
            "target_degree": 1,
            "y_transformations": ["identity"],
        },
        "evaluation_policy": {
            "method": "none",
            "partitions": None,
            "groups": None,
            "seed": 17,
        },
        "reference_date": "2024-06-01",
        "inspection_date": "2024-06-15",
        "target_unit": "",
        "applicant": "Sintetico C17",
        "purpose": "aceite-integracao",
    }
    spec.update(overrides)
    return spec


def subject_raw(*, bairro: str = "Centro", area: float = 85.5) -> dict:
    return {"bairro": bairro, "area": area}


def client() -> TestClient:
    return TestClient(app)


def issues_of(resp) -> list:
    body = resp.json()
    if isinstance(body, dict) and "issues" in body:
        return list(body["issues"] or [])
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        return list(detail.get("issues") or [])
    return []


def issue_codes(resp) -> set:
    return {item.get("code") for item in issues_of(resp) if isinstance(item, Mapping)}


def post_job(
    test_client: TestClient,
    *,
    file_bytes: bytes,
    filename: str = "mercado.csv",
    spec: Optional[Mapping[str, Any]] = None,
    subject: Optional[Mapping[str, Any]] = None,
    content_type: str = "text/csv",
):
    data = {"request_json": json.dumps(spec or request_spec())}
    if subject is not None:
        data["subject_json"] = json.dumps(subject)
    return test_client.post(
        "/jobs",
        files={"file": (filename, file_bytes, content_type)},
        data=data,
    )


def wait_job(test_client: TestClient, job_id: str, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = test_client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last.get("state") in TERMINAL:
            return last
        time.sleep(0.15)
    raise AssertionError(f"job {job_id} did not reach a terminal state: {last}")


def get_result(test_client: TestClient, job_id: str):
    return test_client.get(f"/jobs/{job_id}/result")


def production_peers():
    peers = resolve_peers()
    for name, fn in peers.items():
        kind, ref = peer_kind(fn)
        assert kind != "simulator", f"{name} resolved to labeled simulator {ref}"
    return peers


def _inflate_pdf_streams(pdf_bytes: bytes) -> str:
    import zlib

    chunks: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.+?)\r?\nendstream", pdf_bytes, re.DOTALL):
        blob = match.group(1)
        decoded = None
        for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                decoded = zlib.decompress(blob, wbits)
                break
            except zlib.error:
                continue
        if decoded is None:
            decoded = blob
        text = decoded.decode("latin-1", errors="replace")
        literals = re.findall(r"\((?:\\.|[^\\)])*\)", text)
        if literals:
            chunks.append(" ".join(literals))
        else:
            chunks.append(text)
    return "\n".join(chunks)


def pdf_text(pdf_bytes: bytes) -> str:
    """Inspect rendered PDF text. pypdf is optional; inflate streams if needed."""
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        raise AssertionError("not a PDF")
    try:
        from tests.c08_report.pdf_text import extract_pdf_text

        text = extract_pdf_text(pdf_bytes)
        if text and text.strip():
            return text
    except Exception:
        pass
    inflated = _inflate_pdf_streams(pdf_bytes)
    if inflated.strip():
        return inflated
    decoded = pdf_bytes.decode("latin-1", errors="replace")
    literals = re.findall(r"\(([^)]{2,})\)", decoded)
    return "\n".join(literals) or decoded


def finite_or_null(value) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)
