"""C12-A03: on-disk reconstruction within tolerance; legacy gaps do not echo memory."""

from __future__ import annotations

import json
import math
import pickle
import subprocess
import sys
from pathlib import Path

from modules.evidence_bundle import build_evidence_bundle, reproduce_from_bundle

from .helpers import make_complete_evaluation, make_legacy_formula_only, make_log_target_evaluation

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "c12_reproduce" / "reproduce.py"


def _run_cli(bundle: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), "--bundle", str(bundle)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
    )


def test_reproduce_from_disk_recovers_point_and_supported_intervals(tmp_path):
    ev = make_complete_evaluation()
    out = tmp_path / "bundle"
    build_evidence_bundle(
        ev["snapshot"], ev["input_bundle"], ev["prepared_dataset"], ev["artifacts"], out
    )
    # Independent of the in-memory objects: only the directory is passed.
    result = reproduce_from_bundle(out)
    assert result["ok"] is True
    assert result["point"] is not None
    assert result["comparison"]["point_within_tolerance"] is True
    assert result["comparison"]["mean_ci80_within_tolerance"] is True
    assert result["comparison"]["prediction_interval_within_tolerance"] is True
    assert result["mean_ci80"]["lower"] < result["point"] < result["mean_ci80"]["upper"]
    assert "pickle" not in json.dumps(result).lower() or "refuses" in json.dumps(result.get("method") or "")


def test_cli_is_deterministic_across_two_runs(tmp_path):
    ev = make_complete_evaluation()
    out = tmp_path / "bundle"
    build_evidence_bundle(
        ev["snapshot"], ev["input_bundle"], ev["prepared_dataset"], ev["artifacts"], out
    )
    first = _run_cli(out)
    second = _run_cli(out)
    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
    a = json.loads(first.stdout)
    b = json.loads(second.stdout)
    assert a["point"] == b["point"]
    assert a["mean_ci80"] == b["mean_ci80"]
    assert a["prediction_interval"] == b["prediction_interval"]
    assert a["comparison"] == b["comparison"]
    assert a["versions"]["compatible"] is True


def test_legacy_formula_without_coefficients_fails_without_memorized_value(tmp_path):
    ev = make_legacy_formula_only()
    out = tmp_path / "bundle"
    manifest = build_evidence_bundle(
        ev["snapshot"], ev["input_bundle"], ev["prepared_dataset"], ev["artifacts"], out
    )
    assert manifest["reproduction"]["promised"] is False
    result = reproduce_from_bundle(out)
    assert result["ok"] is False
    assert result["point"] is None
    assert result["point"] != ev["memorized_point"]
    joined = " ".join(result["limitations"])
    assert "coefficients" in joined or "faltante" in joined
    assert ev["memorized_point"] not in (result["point"],)

    proc = _run_cli(out)
    assert proc.returncode == 3
    payload = json.loads(proc.stdout)
    assert payload["point"] is None
    assert payload["ok"] is False


def test_log_target_original_scale_interval_is_centered_on_original_unit_point(tmp_path):
    """C12-A03: y=ln + interval_scale=original must not band around ln(price)."""
    ev = make_log_target_evaluation()
    out = tmp_path / "bundle"
    build_evidence_bundle(
        ev["snapshot"], ev["input_bundle"], ev["prepared_dataset"], ev["artifacts"], out
    )
    result = reproduce_from_bundle(out)
    assert result["point"] is not None
    assert result["mean_ci80"] is not None
    lo = result["mean_ci80"]["lower"]
    hi = result["mean_ci80"]["upper"]
    mid = 0.5 * (lo + hi)
    # Centered on the reconstructed original-unit point, not on Xb = ln(price).
    assert abs(mid - result["point"]) <= 1e-6 + 1e-8 * abs(result["point"])
    assert lo < result["point"] < hi
    log_scale_predictor = math.log(result["point"])
    assert abs(mid - result["point"]) < abs(mid - log_scale_predictor)
    assert result["comparison"]["point_within_tolerance"] is True
    assert result["comparison"]["mean_ci80_within_tolerance"] is True
    assert result["ok"] is True

    proc = _run_cli(out)
    payload = json.loads(proc.stdout)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    cli_mid = 0.5 * (payload["mean_ci80"]["lower"] + payload["mean_ci80"]["upper"])
    assert abs(cli_mid - payload["point"]) <= 1e-6 + 1e-8 * abs(payload["point"])
    assert payload["mean_ci80"]["lower"] < payload["point"] < payload["mean_ci80"]["upper"]


def test_declared_supported_intervals_missing_material_fails_ok(tmp_path):
    """C12-A03: promised/supported intervals without material must not exit 0."""
    ev = make_complete_evaluation()
    ev["artifacts"]["residual_context"] = {
        "interval_method": "ols_mean_and_prediction",
        "interval_scale": "original",
    }
    out = tmp_path / "bundle"
    build_evidence_bundle(
        ev["snapshot"], ev["input_bundle"], ev["prepared_dataset"], ev["artifacts"], out
    )
    result = reproduce_from_bundle(out)
    assert result["mean_ci80"] is None
    assert result["ok"] is False
    joined = " ".join(result["limitations"]).lower()
    assert "interval" in joined
    proc = _run_cli(out)
    assert proc.returncode != 0
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert payload.get("mean_ci80") is None


def test_pickle_artifact_is_not_loaded_or_used_as_reproduction(tmp_path):
    ev = make_complete_evaluation()
    payload = pickle.dumps({"coefficients": {"const": 0.0, "area": 0.0}, "trap": True})
    ev["artifacts"]["files"] = {
        "legacy_model.pkl": {"bytes": payload, "filename": "legacy_model.pkl"}
    }
    out = tmp_path / "bundle"
    build_evidence_bundle(
        ev["snapshot"], ev["input_bundle"], ev["prepared_dataset"], ev["artifacts"], out
    )
    stored = list((out / "artifacts").glob("*"))
    assert stored
    # Extension rewritten so the package does not contain an executable pickle path.
    assert not any(p.suffix == ".pkl" for p in stored)
    result = reproduce_from_bundle(out)
    assert result["ok"] is True
    assert result["point"] == ev["point"]
    # Reconstruction used declared coefficients, not the pickled zeros.
    assert result["point"] != 0.0
