"""Runner interface, corpus catalog, and CI inventory live under P04-owned paths."""
from __future__ import annotations

from pathlib import Path

from tests.fixtures.pro_workflow.corpus import catalog

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "scripts" / "pro_workflow" / "run.py"
WORKFLOW = ROOT / ".github" / "workflows" / "c15-ci.yml"


def test_catalog_covers_eight_situation_families():
    rows = catalog()
    assert len(rows) == 8
    ids = {row["id"] for row in rows}
    assert ids == {"S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08"}
    families = {row["family"] for row in rows}
    assert "ols_identity_noise_category" in families
    assert "ptbr_csv_excel_missing_target" in families
    assert "discrepant_unit_date_policy" in families
    assert "holdout_reserve_only_category" in families
    assert "influence_justified_exclusion" in families
    assert "boundary_extrapolation" in families
    assert "saved_restored_batch" in families
    assert "report_dossier_210plus" in families


def test_runner_script_is_executable_interface():
    text = RUNNER.read_text(encoding="utf-8")
    assert "--mode" in text
    assert "diagnose-base" in text
    assert "accept-candidate" in text
    assert "PYTHONPATH" in text
    assert "skip" in text.lower() or "xfail" in text.lower()


def test_workflow_checks_incremental_prs():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "mp-20260911/integracao-final" in text
    assert "mp-pro-20260911/p04-referencia-consolidacao" in text
    assert "pull_request_target" not in text
    assert "p04-harness" in text
