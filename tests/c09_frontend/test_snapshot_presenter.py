"""C09-A02: apresentação do ResultSnapshot sem zero substituto nem banner normativo falso."""

import json
import math

from frontend.components.charts import interval_chart_model
from frontend.components.layout import (
    NORMA_BANNER_FORBIDDEN,
    format_optional_number,
    present_snapshot,
    snapshot_contains_forbidden_norma_banner,
)
from tests.c09_frontend.fixtures import (
    SNAPSHOT_CLASSIFIED,
    SNAPSHOT_ERROR,
    SNAPSHOT_NOT_COMPUTED,
    SNAPSHOT_UNCLASSIFIED,
)


def test_null_point_is_not_zero_and_does_not_use_float_format():
    view = present_snapshot(SNAPSHOT_NOT_COMPUTED)
    block = view["value_block"]
    assert block["missing_point"] is True
    assert block["point"] is None
    assert block["substituted_zero"] is False
    assert block["point_display"] == "Valor não calculado"
    assert "0,0000" not in block["point_display"]
    assert "0.0000" not in block["point_display"]
    assert format_optional_number(None) == "não calculado"
    assert format_optional_number(float("nan")) == "não calculado"
    # None never reaches a :.4f conversion.
    try:
        _ = f"{None:.4f}"
        raise AssertionError("None should not be formattable with :.4f")
    except (TypeError, ValueError):
        pass


def test_unit_and_dates_come_from_snapshot_and_stay_pending_when_absent():
    view = present_snapshot(SNAPSHOT_NOT_COMPUTED)
    block = view["value_block"]
    assert block["unit_pending"] is True
    assert block["unit_display"] == "unidade não informada"
    assert block["reference_date"] == "data-base não informada"
    assert block["estimand"] == "estimando não informado"
    classified = present_snapshot(SNAPSHOT_CLASSIFIED)
    assert classified["value_block"]["unit"] == "BRL"
    assert classified["value_block"]["reference_date"] == "2024-01-15"
    assert classified["value_block"]["estimand"] == "valor de mercado"
    assert classified["value_block"]["generated_at"] == "2024-03-02T12:00:00Z"


def test_precisao_statuses_are_distinct():
    labels = {
        "not_computed": present_snapshot(SNAPSHOT_NOT_COMPUTED)["precisao"]["label"],
        "classified": present_snapshot(SNAPSHOT_CLASSIFIED)["precisao"]["label"],
        "unclassified": present_snapshot(SNAPSHOT_UNCLASSIFIED)["precisao"]["label"],
        "error": present_snapshot(SNAPSHOT_ERROR)["precisao"]["label"],
    }
    assert present_snapshot(SNAPSHOT_NOT_COMPUTED)["precisao"]["status"] == "not_computed"
    assert present_snapshot(SNAPSHOT_CLASSIFIED)["precisao"]["status"] == "classified"
    assert present_snapshot(SNAPSHOT_UNCLASSIFIED)["precisao"]["status"] == "unclassified"
    assert present_snapshot(SNAPSHOT_ERROR)["precisao"]["status"] == "error"
    assert len(set(labels.values())) == 4
    assert labels["not_computed"] != labels["unclassified"]
    assert labels["error"] != labels["classified"]


def test_issues_do_not_disappear_and_legacy_boolean_does_not_create_norma_banner():
    for snap in (SNAPSHOT_NOT_COMPUTED, SNAPSHOT_CLASSIFIED, SNAPSHOT_UNCLASSIFIED, SNAPSHOT_ERROR):
        view = present_snapshot(snap)
        assert view["norma_banner"] is None
        assert snapshot_contains_forbidden_norma_banner(view) is False
        assert view["warnings_visible"] is True
        assert view["issues_count"] == len(snap["issues"])
        assert view["issues"] == snap["issues"]
        blob = json.dumps(view["headings"], ensure_ascii=False).lower()
        assert NORMA_BANNER_FORBIDDEN not in blob


def test_intervals_use_portuguese_names_not_internal_keys():
    view = present_snapshot(SNAPSHOT_CLASSIFIED)
    labels = [item["label"] for item in view["intervals"]]
    keys = [item["key"] for item in view["intervals"]]
    assert "Intervalo de confiança da média (80%)" in labels
    assert "Intervalo de predição" in labels
    assert "Intervalo de arbitragem" in labels
    assert "Intervalo admissível" in labels
    assert view["internal_keys_exposed"] is False
    assert "mean_ci80" not in labels
    assert "mean_ci80" in keys
    mean = next(item for item in view["intervals"] if item["key"] == "mean_ci80")
    assert mean["lower"] == 240000.0
    assert "240.000" in mean["lower_display"]


def test_c13_actions_show_evidence_and_limitations():
    view = present_snapshot(SNAPSHOT_NOT_COMPUTED)
    assert view["next_actions"]
    action = view["next_actions"][0]
    assert action["evidence_visible"] is True
    assert action["limitations_visible"] is True
    assert action["evidence_refs"] == ["sample.used"]
    assert "revisão profissional" in action["limitations"].lower()


def test_diagnostics_sample_and_alternatives_remain_reachable():
    view = present_snapshot(SNAPSHOT_CLASSIFIED)
    assert view["diagnostics_available"] is True
    assert view["model"]["coefficients"]
    assert view["sample"]["used"] == 8
    assert view["alternatives"][0]["candidate_id"] == "alt-1"
    assert view["search"]["evaluated"] == 3


def test_interval_chart_omits_axis_when_point_is_null():
    assert interval_chart_model(SNAPSHOT_NOT_COMPUTED) is None
    assert interval_chart_model(SNAPSHOT_ERROR) is None
    model = interval_chart_model(SNAPSHOT_CLASSIFIED)
    assert model is not None
    assert model["point"] == 250000.5
    assert model["language"] == "pt-BR"
    assert any(item["label"] == "Valor pontual" for item in model["series"])
    assert all("mean_ci80" != item["label"] for item in model["series"])


def test_classified_point_display_is_brazilian_and_finite():
    view = present_snapshot(SNAPSHOT_CLASSIFIED)
    display = view["value_block"]["point_display"]
    assert "250.000,50" in display
    assert "BRL" in display
    assert math.isfinite(view["value_block"]["point"])
