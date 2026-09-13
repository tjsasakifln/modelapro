"""P01/P02/P03 extensions: diagnose on BASE_SHA, require on the composed candidate.

The job is always executed. Absence is a finding, not skip/xfail.
Set P04_REQUIRE_EXTENSIONS=1 to make missing extensions fail the suite.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from tests.fixtures.pro_workflow import corpus
from tests.pro_workflow.p04.helpers import client, run_job

REQUIRE = os.environ.get("P04_REQUIRE_EXTENSIONS", "") in {"1", "true", "yes"}


def _findings_dir() -> Path:
    raw = os.environ.get("P04_FINDINGS_DIR")
    if raw:
        path = Path(raw)
    else:
        path = Path(__file__).resolve().parent / "_findings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_finding(name: str, payload: dict) -> None:
    path = _findings_dir() / f"finding_{name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def test_minimum_fundamentacao_grade_canonical_field(isolated_p04_runtime):
    case = corpus.s02_ptbr_and_missing()
    spec = corpus.pinned_identity_spec(
        import_options={"locale": "pt-BR", "delimiter": ";", "encoding": "utf-8"},
        search_policy={
            "mode": "exact",
            "budget": 16,
            "objective": "aic",
            "seed": 17,
            "y_transformations": ["identity"],
            "minimum_fundamentacao_grade": 2,
        },
    )
    out = run_job(
        client(),
        corpus.s02_csv_bytes(case),
        spec=spec,
        subject=case["subject"],
        require_success=False,
    )
    snap = out["snapshot"] or {}
    ctx = (snap.get("provenance") or {}).get("workflow_context")
    present = isinstance(ctx, dict) and ctx.get("schema_version") == "MP-PRO/1"
    finding = {
        "id": "P04-EXT-minimum_grade",
        "present": present,
        "requested": 2,
        "observed": ctx,
        "require_extensions": REQUIRE,
    }
    _write_finding("minimum_grade", finding)
    if REQUIRE:
        assert present, finding
        assert ctx.get("requested_minimum_grade") == 2
        assert ctx.get("grade_requirement_status") in {"met", "not_met", "pending", "error"}
    else:
        assert finding["id"] == "P04-EXT-minimum_grade"


def test_model_formula_extension_when_derivable(isolated_p04_runtime):
    case = corpus.s02_ptbr_and_missing()
    spec = corpus.pinned_identity_spec(
        import_options={"locale": "pt-BR", "delimiter": ";", "encoding": "utf-8"},
    )
    out = run_job(client(), corpus.s02_csv_bytes(case), spec=spec, subject=case["subject"])
    formula = (out["snapshot"].get("model") or {}).get("formula")
    finding = {"id": "P04-EXT-formula", "present": bool(formula), "formula": formula, "require_extensions": REQUIRE}
    _write_finding("formula", finding)
    if REQUIRE:
        assert formula, finding
    else:
        assert finding["id"] == "P04-EXT-formula"


def test_conflicting_grade_aliases_are_structured_errors(isolated_p04_runtime):
    case = corpus.s02_ptbr_and_missing()
    spec = corpus.pinned_identity_spec(
        import_options={"locale": "pt-BR", "delimiter": ";", "encoding": "utf-8"},
        search_policy={
            "mode": "exact",
            "budget": 16,
            "objective": "aic",
            "seed": 17,
            "minimum_fundamentacao_grade": 2,
            "min_fundamentacao_grade": 3,
            "target_degree": 1,
            "y_transformations": ["identity"],
        },
    )
    out = run_job(
        client(),
        corpus.s02_csv_bytes(case),
        spec=spec,
        subject=case["subject"],
        require_success=False,
    )
    status = out["response"].status_code
    issues = []
    ctype = out["response"].headers.get("content-type", "")
    body = out["response"].json() if ctype.startswith("application/json") else {}
    if isinstance(body, dict):
        issues = body.get("issues") or (body.get("detail") or {}).get("issues") or []
    codes = {i.get("code") for i in issues if isinstance(i, dict)}
    conflict = status in {400, 422} or any("conflict" in str(c).lower() for c in codes)
    finding = {
        "id": "P04-EXT-alias_conflict",
        "present": conflict,
        "http_status": status,
        "codes": sorted(str(c) for c in codes),
        "require_extensions": REQUIRE,
    }
    _write_finding("alias_conflict", finding)
    if REQUIRE:
        assert conflict, finding
    else:
        assert finding["id"] == "P04-EXT-alias_conflict"
