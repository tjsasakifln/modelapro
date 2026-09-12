"""C02-A01 / C02-A02: encomenda, profile, vistoria, identity — shipped builders."""

from frontend.components.forms import build_request_spec
from frontend.components.professional import (
    art_is_not_conselho_auth,
    assert_no_false_homologation,
    build_document_record,
    build_encomenda,
    build_inspection_record,
    build_professional_identity,
    empty_inspection_record,
    homologation_badge_for,
    known_profile_ids,
    qualification_profile_wire,
    select_qualification_profile,
)
from modules.result_contract import validate_request_spec


def _spec(**kwargs):
    base = dict(
        target_col="preco",
        candidate_cols=["area", "bairro"],
        roles={"preco": "target", "area": "predictor", "bairro": "predictor"},
        target_unit="BRL",
        reference_date="2024-01-15",
        applicant="Solicitante sintético",
        purpose="avaliacao_profissional",
        rights="plena_propriedade",
        recipient_id="solicitante",
        value_basis="valor_de_mercado",
        asset_scope="imovel_urbano",
        qualification_profile=select_qualification_profile("abnt-14653-2-regressao-mercado"),
        minimum_fundamentacao_grade=2,
    )
    base.update(kwargs)
    return build_request_spec(**base)


def test_build_request_spec_emits_additive_qualification_profile_and_encomenda():
    spec = _spec()
    assert spec["schema_version"] == "MP/1"
    assert spec["purpose"] == "avaliacao_profissional"
    assert spec["rights"] == "plena_propriedade"
    assert spec["recipient_id"] == "solicitante"
    assert spec["value_basis"] == "valor_de_mercado"
    assert spec["asset_scope"] == "imovel_urbano"
    assert spec["applicant"] == "Solicitante sintético"
    assert spec["reference_date"] == "2024-01-15"
    assert spec["target_unit"] == "BRL"
    profile = spec["qualification_profile"]
    assert profile["id"] == "abnt-14653-2-regressao-mercado"
    assert profile["version"] == "1.0.0"
    assert len(profile["source_set_sha256"]) == 64
    assert set(profile) == {
        "id",
        "version",
        "source_set_sha256",
        "purpose",
        "value_basis",
        "method",
        "asset_scope",
        "recipient_id",
    }
    assert "search_policy" in spec
    assert spec["search_policy"]["minimum_fundamentacao_grade"] == 2


def test_unknown_profile_is_not_homologated_and_blocks_signoff():
    resolved = select_qualification_profile("banco-inventado-xyz")
    assert resolved["known"] is False
    assert resolved["homologation_status"] == "not_homologated"
    assert resolved["sold_as_homologated"] is False
    assert resolved["homologation_badge"] is None
    assert resolved["blocks_ready_for_professional_signoff"] is True
    assert homologation_badge_for(resolved) is None
    text = f"{resolved['label']} {resolved['block_reason']}"
    assert assert_no_false_homologation(text)


def test_bank_and_insurer_profiles_never_badge_acceptance_from_compatibility():
    bank = select_qualification_profile("bb-meci-avaliacao-imovel-pf")
    insurer = select_qualification_profile("abnt-14653-2-custo-reedicao")
    assert bank["known"] is True
    assert bank["compatibility_status"] == "verified"
    assert bank["homologation_status"] == "not_homologated"
    assert bank["homologation_badge"] is None
    assert bank["sold_as_homologated"] is False
    # The selected, verified profile does not demand an institutional act to
    # calculate. C05 still assesses every actual case before document emission.
    assert bank["blocks_ready_for_professional_signoff"] is False
    assert insurer["method"] == "metodo_quantificacao_de_custo"
    assert insurer["method_supports_purpose"] is True
    assert insurer["blocks_ready_for_professional_signoff"] is True
    assert insurer["homologation_badge"] is None
    assert insurer["required_value_basis"] == "custo_de_reedicao"
    fake_http_200 = {"status": "ok", "http": 200}
    assert homologation_badge_for(bank, institution_acceptance=fake_http_200) is None


def test_encomenda_shows_method_support_immediately():
    professional = build_encomenda(
        purpose="avaliacao_profissional",
        asset_scope="imovel_urbano",
        rights="plena_propriedade",
        reference_date="2024-01-15",
        target_unit="BRL",
        applicant="Solicitante sintético",
        recipient_id="solicitante",
        value_basis="valor_de_mercado",
        profile=select_qualification_profile("abnt-14653-2-regressao-mercado"),
    )
    assert professional["method_supports_purpose"] is True
    seguro = build_encomenda(
        purpose="seguro",
        value_basis="custo_de_reedicao",
        recipient_id="seguradora",
        profile=select_qualification_profile("abnt-14653-2-custo-reedicao"),
    )
    assert seguro["method_supports_purpose"] is True
    assert seguro["homologation_badge"] is None
    assert seguro["value_basis"] == "custo_de_reedicao"


def test_inspection_empty_is_not_attested_and_third_party_stays_received():
    empty = empty_inspection_record()
    assert empty["attested_inspection"] is False
    assert empty["attested_regularity"] is False
    assert empty["auto_attested"] is False
    assert empty["procedencia"] == "not_recorded"
    recorded = build_inspection_record(
        responsible="Avaliador sintético",
        date="2024-01-10",
        verified_characteristics="área conferida",
        cadastral_divergences="matrícula diverge da área medida",
        physical_divergences="",
        special_assumptions="ocupação regular declarada pelo solicitante",
        limitations="fachada posterior não vistoriada",
        procedencia="professional_act",
    )
    assert recorded["recorded"] is True
    assert recorded["auto_attested"] is False
    assert recorded["defaults_fabricated"] is False
    third = build_inspection_record(
        responsible="",
        procedencia="received_information",
        third_party_source="relato do síndico (sintético)",
    )
    assert third["third_party_act"] is True
    assert third["procedencia_label"].startswith("Informação recebida")
    assert third["attested_regularity"] is False


def test_art_format_is_not_conselho_authentication_and_defaults_are_empty():
    blank = build_professional_identity()
    assert blank["art_rrt"] == ""
    assert blank["auto_filled"] is False
    assert blank["conselho_authenticated"] is False
    assert blank["attested_by_software"] is False
    filled = build_professional_identity(
        name="Profissional sintético",
        registration="12345",
        council="CREA",
        art_rrt="ART-2024-0001",
    )
    assert filled["art_rrt_format_valid"] is True
    assert filled["conselho_authenticated"] is False
    assert art_is_not_conselho_auth(filled)
    doc = build_document_record(
        title="Matrícula",
        source="cartório (sintético)",
        procedencia="received_information",
    )
    assert doc["received_information"] is True
    assert doc["auto_attested"] is False


def test_wire_profile_does_not_embed_rules_or_homologation_seal():
    resolved = select_qualification_profile("bb-meci-avaliacao-imovel-pf")
    wire = qualification_profile_wire(resolved)
    assert "homologation_status" not in wire
    assert "checklist_ids" not in wire
    assert wire["recipient_id"] == "banco-do-brasil"
    assert "bb-meci-avaliacao-imovel-pf" in known_profile_ids()


def test_recipient_neutral_profile_does_not_emit_an_empty_recipient_id():
    """Regression for the real browser POST /jobs, which used to return 400."""
    selected = select_qualification_profile(
        "abnt-14653-2-regressao-mercado", recipient_id=""
    )
    wire = qualification_profile_wire(selected)

    assert selected["resolved"] is True
    assert selected["mismatch_with_catalog"] is False
    assert wire["recipient_id"] is None
    validated = validate_request_spec(_spec(qualification_profile=selected))
    assert validated["qualification_profile"]["recipient_id"] is None


def test_request_spec_carries_evidenced_profile_requirements_and_professional_findings():
    """The UI transports C05 inputs without manufacturing a generic valid flag."""
    profile_evidence = {
        "parte1.6.3.vistoria": "SYNTHETIC_TEST_vistoria.pdf#sha256=abc",
    }
    professional_findings = {
        "anexoA.2.f.variaveis_relevantes": {
            "satisfied": True,
            "justification": "SYNTHETIC_TEST: exame registrado no laudo de teste",
        },
    }

    validated = validate_request_spec(
        _spec(
            profile_evidence=profile_evidence,
            professional_findings=professional_findings,
        )
    )

    assert validated["profile_evidence"] == profile_evidence
    assert validated["professional_findings"] == professional_findings
    assert "valid" not in validated["professional_findings"][
        "anexoA.2.f.variaveis_relevantes"
    ]


def test_request_spec_carries_only_an_explicit_value_policy():
    value_policy = {
        "adopted": {"method": "point"},
        "source": "SYNTHETIC_TEST: política expressamente selecionada",
    }

    declared = validate_request_spec(_spec(value_policy=value_policy))
    omitted = validate_request_spec(_spec())

    assert declared["value_policy"] == value_policy
    assert "value_policy" not in omitted


def test_synthetic_case_marker_is_explicit_and_never_the_default():
    marked = validate_request_spec(_spec(synthetic_test_only=True))
    ordinary = validate_request_spec(_spec())

    assert marked["synthetic_test_only"] is True
    assert "synthetic_test_only" not in ordinary
