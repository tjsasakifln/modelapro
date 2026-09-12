"""C02-A03 / C02-A04: sample/model review and apto/inapto/pendente — shipped helpers."""

from frontend.components.forms import build_request_spec, preview_to_form_model
from frontend.components.professional import record_justified_exclusion
from frontend.components.layout import present_snapshot, snapshot_contains_forbidden_norma_banner
from frontend.components.professional import (
    classify_limitation,
    feature_map_to_original,
    gate_ready_for_professional_signoff,
    present_aptidao,
    present_independent_validation_coverage,
    present_qualification_context,
    present_valid_not_released,
    preserve_mapping_if_compatible,
    record_justified_exclusion,
    select_qualification_profile,
)
from frontend.components.workflow import apply_invalidation, merge_invalidation, unused_columns_view
from tests.c09_frontend.fixtures import PREVIEW_BAIRRO_FORMATTED, SNAPSHOT_CLASSIFIED


def test_preview_consumption_does_not_invent_parsed_values():
    model = preview_to_form_model(PREVIEW_BAIRRO_FORMATTED)
    assert "area" in model["column_map"]
    unused = unused_columns_view(
        model["column_map"],
        roles={"preco": "target", "informante": "identifier", "area": "predictor", "bairro": "predictor"},
        candidate_cols=["area", "bairro"],
        target_col="preco",
    )
    assert any(
        item["name"] == "informante" or item.get("original_name") == "informante"
        for item in unused
    )
    kept = preserve_mapping_if_compatible(
        stored_token="same",
        current_token="same",
        stored_mapping={"area": "predictor"},
    )
    assert kept["reused"] is True
    dropped = preserve_mapping_if_compatible(
        stored_token="old",
        current_token="new",
        stored_mapping={"area": "predictor"},
    )
    assert dropped["reused"] is False
    assert dropped["mapping"] is None


def test_justified_exclusion_requires_reason_and_reviewer():
    item = record_justified_exclusion(
        row_id="IM-01",
        reason="duplicidade do mesmo bem",
        reviewer="Profissional sintético",
        effect="n efetivo 23",
        fingerprint="fp1",
    )
    assert item["automatic_to_improve_r2"] is False
    assert item["silent"] is False
    spec = build_request_spec(
        target_col="preco",
        candidate_cols=["area"],
        roles={"preco": "target", "area": "predictor"},
        justified_exclusions=[item],
    )
    assert spec["justified_exclusions"][0]["row_id"] == "IM-01"
    assert spec["justified_exclusions"][0]["reason"] == "duplicidade do mesmo bem"
    assert spec["justified_exclusions"][0]["reviewer"] == "Profissional sintético"
    try:
        record_justified_exclusion(row_id="IM-02", reason="", reviewer="X", effect="")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_feature_map_uses_original_characteristic_not_required_dummy_names():
    schema = {
        "columns": {
            "bairro": {"original_name": "bairro", "kind": "categorical"},
            "bairro_Centro": {"original_name": "bairro", "dummy_of": "bairro", "kind": "numeric"},
            "area": {"original_name": "área", "kind": "numeric"},
        }
    }
    rows = feature_map_to_original(
        {"bairro_Centro": 0.12, "area": 850.0},
        schema,
    )
    labels = {row["feature"]: row["original_characteristic"] for row in rows}
    assert labels["bairro_Centro"] == "bairro"
    assert labels["area"] in {"área", "area"}
    assert all(row["dummy_name_required"] is False for row in rows)
    snap = dict(SNAPSHOT_CLASSIFIED)
    snap["model"] = {
        "coefficients": {"bairro_Centro": 0.12, "area": 850.0},
        "feature_schema": schema,
        "formula": "preco ~ area + bairro_Centro",
    }
    presented = present_snapshot(snap)
    mapped_view = {row["feature"]: row["original_characteristic"] for row in presented["coefficient_map"]}
    assert mapped_view["bairro_Centro"] == "bairro"
    assert presented["dummy_name_required"] is False


def test_independent_validation_coverage_does_not_present_train_as_external():
    spec = build_request_spec(
        target_col="preco",
        candidate_cols=["area"],
        roles={"preco": "target", "area": "predictor"},
        evaluation_method="none",
    )
    coverage = present_independent_validation_coverage(SNAPSHOT_CLASSIFIED, spec)
    assert coverage["train_metrics_are_not_external"] is True
    assert coverage["presented_train_as_external"] is False
    assert coverage["requested"] is False


def test_grade_statuses_stay_distinct_and_valid_not_released_stays_accessible():
    for status in ("pending", "met", "not_met", "not_requested", "error"):
        view = present_aptidao(grade_requirement_status=status, issuance_status="draft")
        assert view["grade_requirement_status"] == status
        assert view["global_green"] is False
        assert view["single_indicator_success"] is False
        assert view["homologation_badge"] is None
    pending = present_aptidao(grade_requirement_status="pending")
    met = present_aptidao(grade_requirement_status="met")
    not_met = present_aptidao(grade_requirement_status="not_met")
    not_requested = present_aptidao(grade_requirement_status="not_requested")
    error = present_aptidao(grade_requirement_status="error")
    headlines = {pending["headline"], met["headline"], not_met["headline"], not_requested["headline"], error["headline"]}
    assert len(headlines) == 5
    assert pending["ui_status"] == "pendente"
    assert not_met["ui_status"] == "inapto"
    assert pending["pending_is_not_met"] is True
    assert not_met["not_met_is_not_pending"] is True
    not_released = present_valid_not_released(
        reason="Grau solicitado ainda pendente na extensão P01.",
        field="provenance.workflow_context.grade_requirement_status",
        action="Manter o pedido de grau e completar evidências; não emitir como aprovado.",
        requested_grade=2,
    )
    assert not_released["accessible"] is True
    assert not_released["released"] is False
    assert not_released["labeled_approved"] is False
    assert not_released["requested_grade_preserved"] == 2


def test_unsupported_does_not_present_approved_value_or_global_green():
    insurer = select_qualification_profile("urban-comparative-insurer-reconstruction")
    view = present_aptidao(
        calculation_status="unsupported",
        profile=insurer,
        limitations=[classify_limitation(unsupported_method=True, message="rota de custo ausente")],
    )
    assert view["ui_status"] == "inapto"
    assert view["may_show_approved_value"] is False
    assert view["global_green"] is False
    assert view["can_prepare_laudo"] is False
    assert view["analysis_accessible"] is False


def test_legitimate_path_can_prepare_laudo_without_homologation_seal():
    professional = select_qualification_profile("urban-comparative-market-professional")
    view = present_aptidao(
        grade_requirement_status="met",
        calculation_status="valid",
        profile=professional,
        issuance_status="ready_for_professional_review",
    )
    assert view["can_prepare_laudo"] is True
    assert view["global_green"] is False
    assert view["homologation_badge"] is None
    presented = present_snapshot(
        SNAPSHOT_CLASSIFIED,
        request_spec=build_request_spec(
            target_col="preco",
            candidate_cols=["area"],
            roles={"preco": "target", "area": "predictor"},
            qualification_profile=professional,
            purpose="avaliacao_profissional",
        ),
    )
    assert snapshot_contains_forbidden_norma_banner(presented) is False
    assert presented["homologation_badge"] is None
    assert presented["aceito_pelo_banco"] is False


def test_limitation_kinds_are_separated():
    kinds = [
        classify_limitation(missing_data=True, message="data-base ausente", field="reference_date", action="Informar data-base"),
        classify_limitation(failed_rule=True, message="grau não atingido", action="Rever amostra"),
        classify_limitation(unsupported_method=True, message="custo não implementado"),
        classify_limitation(human_review=True, message="adotar valor exige C05"),
    ]
    assert [item["kind"] for item in kinds] == [
        "missing_data",
        "failed_rule",
        "unsupported_method",
        "human_review",
    ]


def test_profile_change_invalidates_result_and_review_without_erasing_history():
    session = {
        "c09_snapshot": {"value": {"point": 10}},
        "c02_review_events": [{"fingerprint": "old", "decision": "reviewed"}],
    }
    out = apply_invalidation(session, "profile")
    assert out["p02_result_stale"] is True
    assert out["c02_review_stale"] is True
    assert out["c02_signature_stale"] is True
    assert out["c02_consent_reusable"] is False
    assert out["c02_review_events_history"][0]["decision"] == "reviewed"
    assert session["c02_review_events"][0]["decision"] == "reviewed"
    sample = apply_invalidation(session, "sample")
    assert sample["p02_result_stale"] is True
    file_change = apply_invalidation(session, "file")
    assert file_change["c02_review_stale"] is True
    assert file_change["c02_signature_stale"] is True
    assert file_change["c02_consent_reusable"] is False
    flags, dropped = merge_invalidation(
        {"c09_preview": {"ok": True}, "c02_applicant": "widget-key", **session},
        "file",
    )
    assert "c02_applicant" not in flags
    assert flags["c02_review_stale"] is True
    assert "c09_preview" in dropped


def test_unverified_rule_is_not_passed_and_unknown_profile_blocks_signoff():
    ctx = present_qualification_context(
        {
            "provenance": {
                "qualification_context": {
                    "schema_version": "MP-QUAL/1",
                    "rule_results": [
                        {
                            "rule_id": "r1",
                            "status": "unverified",
                            "applicability": "decisive",
                        }
                    ],
                    "grade_requirement_status": "pending",
                    "case_release_status": "review_required",
                }
            }
        }
    )
    assert ctx["unverified_treated_as_passed"] is False
    unknown = select_qualification_profile("no-such-profile")
    gate = gate_ready_for_professional_signoff(
        profile=unknown,
        qualification_context=ctx,
        essential_evidence_present=False,
    )
    assert gate["blocked"] is True
    assert gate["emitted_illegal_issuance"] is False
