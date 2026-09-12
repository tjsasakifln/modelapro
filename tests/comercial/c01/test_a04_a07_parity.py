"""C01-A04/A07: persist/reproduce parity, mutation detection, MP-QUAL/1 context."""

from __future__ import annotations

import copy
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from backend.worker import build_frozen_project, compose_valuation_job, resolve_peers
from modules.valuation_batch import evaluate_batch
from modules.valuation_policy.qualification import fingerprint_result, invalidate_reviews_on_material_change
from tests.comercial.c01.conftest import gold_csv_bytes, gold_spec, gold_subject

PROC = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from modules.preprocessing import transform_subject
from modules.valuation_batch import restore_candidate_fit, builtin_evaluate_fitted
frozen_path, subjects_path, out_path = sys.argv[2], sys.argv[3], sys.argv[4]
with open(frozen_path, encoding="utf-8") as fh:
    frozen = json.load(fh)
with open(subjects_path, encoding="utf-8") as fh:
    subjects = json.load(fh)
spec = frozen["request_spec"]
fit = restore_candidate_fit(frozen)
items = []
for sub in subjects:
    design = transform_subject(sub["raw"], frozen["feature_schema"], frozen["encoder_state"])
    got = builtin_evaluate_fitted(fit, design, spec)
    val = got.get("value") or {}
    items.append({
        "point": val.get("point"),
        "mean_ci80": val.get("mean_ci80"),
        "prediction_interval": val.get("prediction_interval"),
        "arbitration_interval": val.get("arbitration_interval"),
        "admissible_interval": val.get("admissible_interval"),
        "issues": list(got.get("issues") or []),
        "supported": getattr(design, "supported", None) if not isinstance(design, dict) else design.get("supported"),
    })
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump({"items": items}, fh)
"""


def _close(a, b):
    if a is None or b is None:
        return a is b
    if isinstance(a, dict) and isinstance(b, dict):
        return _close(a.get("lower"), b.get("lower")) and _close(a.get("upper"), b.get("upper"))
    return math.isclose(float(a), float(b), rel_tol=1e-8, abs_tol=1e-4)


def test_compose_batch_subprocess_share_monetary_blocks(isolated_c01_runtime, tmp_path):
    store = isolated_c01_runtime["job_store"]
    created = store.create(payload={"filename": "gold.csv"})
    spec = gold_spec()
    ctx = compose_valuation_job(
        job_id=created["job_id"],
        file_bytes=gold_csv_bytes(),
        filename="gold.csv",
        request_spec=spec,
        subject_raw=gold_subject(),
        project_id="p-c01",
        peers=resolve_peers(),
        job_store=store,
    )
    snap = ctx["snapshot"]
    frozen = ctx["frozen_project"]
    assert frozen is not None
    persisted_normative = store.get_artifact(created["job_id"], "normative_assessment.json")
    persisted_report_context = store.get_artifact(created["job_id"], "report_context.json")
    assert json.loads(persisted_normative) == (snap["provenance"]["normative_assessment"])
    assert json.loads(persisted_report_context) == ctx["report_context"]
    value = snap["value"]
    assert value["point"] is not None
    assert value.get("arbitration_interval") in (None, value.get("arbitration_interval"))
    if value.get("arbitration_interval") and value.get("point"):
        p = float(value["point"])
        arb = value["arbitration_interval"]
        invented = abs(float(arb["lower"]) - p * 0.85) < 1e-6 and abs(float(arb["upper"]) - p * 1.15) < 1e-6
        # Without a C05 rule the engine must not invent ±15%.
        assert not invented or (spec.get("qualification_profile") or {}).get("interval_rule")

    subjects = [{"subject_id": "s1", "raw": gold_subject()}]
    batch = evaluate_batch(frozen, subjects, spec)
    bval = batch["items"][0]["value"]
    assert _close(bval["point"], value["point"])
    assert _close(bval.get("mean_ci80"), value.get("mean_ci80"))
    assert _close(bval.get("prediction_interval"), value.get("prediction_interval"))
    assert _close(bval.get("arbitration_interval"), value.get("arbitration_interval"))

    frozen_path = tmp_path / "frozen.json"
    subjects_path = tmp_path / "subjects.json"
    out_path = tmp_path / "sub.json"
    frozen_path.write_text(json.dumps(frozen, default=str), encoding="utf-8")
    subjects_path.write_text(json.dumps(subjects), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-c", PROC, str(Path("/home/tjsasakifln/code/modela-pro-com-c01")), str(frozen_path), str(subjects_path), str(out_path)],
        check=True,
        capture_output=True,
        text=True,
        cwd="/home/tjsasakifln/code/modela-pro-com-c01",
        env={**dict(**{k: v for k, v in __import__("os").environ.items() if k != "PYTHONPATH"}), "PYTHONPATH": ""},
    )
    assert proc.returncode == 0
    sub = json.loads(out_path.read_text(encoding="utf-8"))
    sval = sub["items"][0]
    assert _close(sval["point"], value["point"])
    assert _close(sval.get("mean_ci80"), value.get("mean_ci80"))

    qc = (snap.get("provenance") or {}).get("qualification_context") or {}
    assert qc.get("schema_version") == "MP-QUAL/1"
    assert qc.get("result_fingerprint")
    rules = qc.get("rule_results") or []
    # This parity fixture deliberately has no qualification profile.  Numeric
    # results remain reproducible, but no normative profile rules may be
    # invented for the unqualified calculation.
    assert rules == []
    assert qc.get("case_release_status") == "analysis_only"
    assert all(r.get("status") != "passed" or not r.get("unverified") for r in rules)
    assert "unverified" not in {r.get("status") for r in rules if r.get("status") == "passed"}

    mutated = copy.deepcopy(frozen)
    coeffs = (mutated.get("model_state") or {}).get("coefficients") or mutated.get("coefficients") or {}
    if isinstance(coeffs, dict) and coeffs:
        key = next(iter(coeffs))
        coeffs = dict(coeffs)
        coeffs[key] = float(coeffs[key]) + 1.0
        if "model_state" in mutated and isinstance(mutated["model_state"], dict):
            mutated["model_state"] = dict(mutated["model_state"])
            mutated["model_state"]["coefficients"] = coeffs
    batch_mut = evaluate_batch(mutated, subjects, spec)
    mpoint = batch_mut["items"][0]["value"]["point"]
    assert mpoint is None or not _close(mpoint, value["point"])

    fp = fingerprint_result(
        value=value,
        model=snap.get("model") or {},
        sample=snap.get("sample") or {},
        request_spec=spec,
        input_sha256=snap.get("input_sha256") or "",
        code_sha=snap.get("code_sha") or "",
    )
    events = [{"event": "review", "result_fingerprint": fp, "valid": True}]
    other = fingerprint_result(
        value={**value, "point": (value["point"] or 0) + 1},
        model=snap.get("model") or {},
        sample=snap.get("sample") or {},
        request_spec=spec,
        input_sha256=snap.get("input_sha256") or "",
        code_sha=snap.get("code_sha") or "",
    )
    invalidated = invalidate_reviews_on_material_change(fp, other, events)
    assert invalidated[0]["valid"] is False
    assert events[0]["valid"] is True
    assert qc.get("case_release_status") in {
        "analysis_only",
        "review_required",
        "ready_for_professional_signoff",
        "signed_integrity_verified",
    }
