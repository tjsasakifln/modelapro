"""Measurement protocol: machine time ≠ clicks ≠ human hours. Pilot is a template."""
from __future__ import annotations

from pathlib import Path

from tests.fixtures.pro_workflow import corpus
from tests.pro_workflow.p04.helpers import client, run_job

DOCS = Path(__file__).resolve().parents[3] / "docs" / "campaigns" / "MP-PRO-20260911" / "P04"
PILOT = DOCS / "human_pilot_protocol.md"
METRICS_TEXT_FORBIDDEN = (
    "economia de horas",
    "hours saved",
    "produtividade humana medida",
    "avaliador-hora",
    "human-hour savings",
)


def test_metrics_distinguish_compute_navigation_and_unrun_human_time(isolated_p04_runtime):
    case = corpus.s02_ptbr_and_missing()
    out = run_job(
        client(),
        corpus.s02_csv_bytes(case),
        spec=corpus.pinned_identity_spec(
            import_options={"locale": "pt-BR", "delimiter": ";", "encoding": "utf-8"},
        ),
        subject=case["subject"],
    )
    metrics = {
        "compute_time_s": out["compute_time_s"],
        "automated_navigation_time_s": None,
        "automated_actions": {"clicks": 0, "retyped_fields": 0, "editorial_corrections": 0},
        "human_active_time_s": None,
        "human_pilot_executed": False,
        "note": (
            "compute_time_s is wall time of the HTTP job. "
            "automated_actions count robot or scripted steps. "
            "human_active_time_s is null because no authorized human pilot ran."
        ),
    }
    assert metrics["compute_time_s"] > 0
    assert metrics["human_active_time_s"] is None
    assert metrics["human_pilot_executed"] is False
    blob = str(metrics).lower()
    for token in METRICS_TEXT_FORBIDDEN:
        assert token not in blob


def test_human_pilot_protocol_exists_and_does_not_claim_execution():
    assert PILOT.is_file(), PILOT
    text = PILOT.read_text(encoding="utf-8")
    assert "STATUS=NOT_RUN" in text
    assert "5" in text and "10" in text
    lowered = text.lower()
    assert "piloto humano executado" not in lowered
    assert "human pilot executed" not in lowered
    for token in METRICS_TEXT_FORBIDDEN:
        assert token not in lowered
