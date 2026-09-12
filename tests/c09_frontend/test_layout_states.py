"""C09-A05: estados não calculado/não classificável/erro, tela estreita e tabela longa."""

from pathlib import Path

from frontend.components.layout import (
    FIXTURE_SCREEN_NOTICE,
    WORK_FLOW_HEADINGS,
    format_optional_number,
    present_snapshot,
)
from tests.c09_frontend.fixtures import (
    SNAPSHOT_ERROR,
    SNAPSHOT_NOT_COMPUTED,
    SNAPSHOT_UNCLASSIFIED,
    long_table_snapshot,
)

ROOT = Path(__file__).resolve().parents[2]


def test_small_width_keeps_value_block_and_warnings():
    view = present_snapshot(SNAPSHOT_UNCLASSIFIED, viewport_width=360)
    assert view["compact"] is True
    assert view["value_block"]["title"] == "Valor da avaliação"
    assert view["value_block"]["point"] == 180000.0
    assert view["warnings_visible"] is True
    assert view["issues"]
    assert view["precisao"]["status"] == "unclassified"
    assert "Valor da avaliação" in view["headings"]


def test_long_table_does_not_drop_warnings():
    snap = long_table_snapshot(200)
    view = present_snapshot(snap, viewport_width=360, max_table_rows=15)
    assert view["sample"]["table_truncated"] is True
    assert len(view["sample"]["used_row_ids_display"]) == 15
    assert view["sample"]["used_row_ids_total"] == 200
    assert view["issues_count"] == 1
    assert view["issues"][0]["message"] == "Amostra longa: conferir exclusões."
    assert view["warnings_visible"] is True


def test_error_and_not_computed_states_stay_distinct_on_small_screen():
    err = present_snapshot(SNAPSHOT_ERROR, viewport_width=320)
    missing = present_snapshot(SNAPSHOT_NOT_COMPUTED, viewport_width=320)
    assert err["precisao"]["status"] == "error"
    assert missing["precisao"]["status"] == "not_computed"
    assert err["value_block"]["missing_point"] is True
    assert missing["value_block"]["missing_point"] is True
    assert err["value_block"]["point_display"] != "0"
    assert format_optional_number(None, decimals=4) == "não calculado"


def test_fixture_notice_is_labeled_not_a_real_conclusion():
    assert "não é conclusão real do caso" in FIXTURE_SCREEN_NOTICE.lower()
    asset = (ROOT / "frontend" / "assets" / "visual_fixture_snapshot.json").read_text(encoding="utf-8")
    assert "não é conclusão real do caso" in asset.lower() or "nao e conclusao real" in asset.lower() or "não é conclusão" in asset


def test_work_flow_headings_are_portuguese_and_value_centered():
    text = " ".join(WORK_FLOW_HEADINGS).lower()
    assert "encomenda" in text
    assert "amostra" in text
    assert "vistoria" in text
    assert "avaliando" in text
    assert "modelagem" in text
    assert "emissão" in text or "emissao" in text
    assert "r²" not in text


def test_shipped_sources_do_not_format_null_or_claim_norma_from_boolean():
    app_src = (ROOT / "frontend" / "app.py").read_text(encoding="utf-8")
    forms_src = (ROOT / "frontend" / "components" / "forms.py").read_text(encoding="utf-8")
    layout_src = (ROOT / "frontend" / "components" / "layout.py").read_text(encoding="utf-8")
    assert ":.4f" not in app_src
    assert "considerará TODAS" not in forms_src
    assert "considerara TODAS" not in forms_src
    assert 'f"{metrics.get(' not in app_src
    assert "Modelo Atende aos Critérios Normativos" not in layout_src
    assert "Modelo Atende aos Critérios Normativos" not in app_src
    assert "POST /jobs" in app_src or "submit_job" in app_src
    assert "get_result" in forms_src
    assert "/preview" in forms_src
