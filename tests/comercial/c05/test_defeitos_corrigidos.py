"""Regressões dos defeitos que a revisão adversarial desta campanha encontrou.

Cada teste fixa um defeito real que existiu no código desta frente. Nenhum é
hipotético: todos foram observados antes da correção.
"""

from __future__ import annotations

import pytest

from modules import normative_rules as rules
from modules.nbr14653_validation import assess_normative
from modules.qualification_profile import assess_qualification, evaluate_claim
from modules.qualification_profile.claims import (
    CLAIM_INSTITUTION_ACCEPTED,
    CLAIM_PROFILE_COMPATIBLE,
    CLAIM_BLOCKED,
    CLAIM_PERMITTED,
    reuse_acceptance_check,
)


# --- Defeito 1: threshold_provenance devolvia cópia rasa -------------------

def test_threshold_provenance_does_not_expose_the_registry_for_mutation():
    """Cópia rasa deixava o dict `values` compartilhado: um chamador que o
    mutasse reescrevia o registro normativo para o resto do processo."""
    before = dict(rules.THRESHOLD_PROVENANCE["ITEM6_LIMITS"]["values"])
    record = rules.threshold_provenance("ITEM6_LIMITS")
    record["values"]["grau_iii"] = 0.99
    record["clause"] = "adulterado"
    assert rules.THRESHOLD_PROVENANCE["ITEM6_LIMITS"]["values"] == before
    assert rules.THRESHOLD_PROVENANCE["ITEM6_LIMITS"]["values"]["grau_iii"] == 0.01
    assert rules.THRESHOLD_PROVENANCE["ITEM6_LIMITS"]["clause"] == "Tabela 1 item 6"


def test_nested_alternative_reading_is_also_isolated():
    record = rules.threshold_provenance("MEASURE_UPPER_FACTOR")
    record["alternative_reading"]["factor"] = 42.0
    assert rules.THRESHOLD_PROVENANCE["MEASURE_UPPER_FACTOR"][
        "alternative_reading"]["factor"] == 1.0


# --- Defeito 2: limiares duplicados fora do registro ----------------------

def test_no_second_hardcoded_copy_of_the_a3_1_ceiling():
    """O teto de 10% do Anexo A.3.1 tinha uma segunda cópia como default de
    parâmetro, livre para divergir da fonte registrada."""
    registry = rules.THRESHOLD_PROVENANCE["SIGNIFICANCE_AUX"]["values"]["max_alpha"]
    assert rules.max_auxiliary_alpha() == registry == 0.10
    # statistical_warnings passa a ler o teto do registro em vez de um literal.
    import inspect
    sig = inspect.signature(rules.statistical_warnings)
    assert sig.parameters["significance_aux"].default is None


def test_attention_threshold_is_read_from_the_registry():
    """0,80 do Anexo A.2.1.5.2 tinha cópia literal dentro de PRESSUPOSTOS."""
    registry = rules.THRESHOLD_PROVENANCE["CORRELATION_ATTENTION"]["values"]["threshold"]
    spec = rules.PRESSUPOSTOS_BY_ID["anexoA.2.g.multicolinearidade"]
    assert spec["attention_threshold"] == registry == 0.80


def test_vif_has_no_normative_provenance_because_the_standard_defines_none():
    """VIF não é limiar normativo: não pode ganhar entrada de proveniência."""
    assert "VIF" not in rules.THRESHOLD_PROVENANCE
    assert "VIF_CONVENTION" not in rules.THRESHOLD_PROVENANCE
    detail = rules.THRESHOLD_PROVENANCE["CORRELATION_ATTENTION"]["detail"].lower()
    assert "não define corte de vif" in detail


# --- Defeito 3: grau fracionário truncado ---------------------------------

@pytest.mark.parametrize("requested", [3.5, 2.999999, 7, 0, -1, "III", None_ := object(), True, False])
def test_a_non_integral_or_out_of_range_grade_request_is_an_error(requested):
    """int(3.5) == 3 fazia 3,5 ser reportado como 'met'. bool é subclasse de
    int, então True passava como Grau I."""
    from modules.qualification_profile.assessment import _grade_requirement_status
    from modules.qualification_profile.schema import (
        CALC_OK, GRADE_ERROR, GRADE_MET, GRADE_NOT_REQUESTED,
    )
    status = _grade_requirement_status(requested, 3, calculation_status=CALC_OK)
    if requested is None:
        assert status == GRADE_NOT_REQUESTED
    else:
        assert status == GRADE_ERROR, f"{requested!r} não deveria ser aceito"
    assert status != GRADE_MET


@pytest.mark.parametrize("requested,achieved,expected", [(2, 3, "met"), (3, 2, "not_met"), (3, 3, "met")])
def test_integral_requests_still_work(requested, achieved, expected):
    from modules.qualification_profile.assessment import _grade_requirement_status
    from modules.qualification_profile.schema import CALC_OK
    assert _grade_requirement_status(requested, achieved, calculation_status=CALC_OK) == expected


# --- Defeito 4: varredura de substitutos casava subcadeia -----------------

def test_a_legitimate_institutional_act_is_not_rejected_by_substring_noise():
    """"mit" batia dentro de "emitido" e "iti" dentro de "instituição", de modo
    que o próprio ato que autoriza a alegação era recusado."""
    result = evaluate_claim(
        CLAIM_INSTITUTION_ACCEPTED,
        profile_state="verified",
        evidence={
            "real_act_by_institution": {"basis": "ofício de homologação emitido pela instituição"},
            "act_type_is_homologacao_or_explicit_acceptance": {"basis": "homologação expressa"},
            "act_version_and_scope_recorded": {"basis": "ofício nº 12/2026, escopo definido"},
        },
        subject={"institution": "Instituição X", "act": "ofício 12/2026",
                 "act_version": "1", "act_scope": "laudo de imóvel urbano"},
    )
    assert result["state"] == CLAIM_PERMITTED, result["detail"]
    assert result["rejected"] == []


@pytest.mark.parametrize("basis,forbidden_hint", [
    ("credenciamento profissional no CREA", "credenciamento"),
    ("cadastro de fornecedor SICAF", "fornecedor"),
    ("assinatura digital ICP-Brasil", "assinatura"),
    ("participação em licitação, edital 12/2026", "licita"),
])
def test_forbidden_substitutes_are_still_caught_by_word_boundary(basis, forbidden_hint):
    result = evaluate_claim(
        CLAIM_INSTITUTION_ACCEPTED,
        profile_state="verified",
        evidence={
            "real_act_by_institution": {"basis": basis},
            "act_type_is_homologacao_or_explicit_acceptance": {"basis": "x"},
            "act_version_and_scope_recorded": {"basis": "y"},
        },
        subject={"institution": "I", "act": "a", "act_version": "1", "act_scope": "s"},
    )
    assert result["state"] == CLAIM_BLOCKED
    assert result["rejected"], f"{basis!r} deveria ter sido recusado"


def test_a_forbidden_substitute_cannot_hide_in_a_non_basis_field():
    result = evaluate_claim(
        CLAIM_INSTITUTION_ACCEPTED,
        profile_state="verified",
        evidence={
            "real_act_by_institution": {"ref": "credenciamento CAIXA 2026"},
            "act_type_is_homologacao_or_explicit_acceptance": {"basis": "x"},
            "act_version_and_scope_recorded": {"basis": "y"},
        },
        subject={"institution": "I", "act": "a", "act_version": "1", "act_scope": "s"},
    )
    assert result["state"] == CLAIM_BLOCKED
    assert any(r["field"] != "basis" for r in result["rejected"])


# --- Defeito 5: sujeito presente mas vazio -------------------------------

@pytest.mark.parametrize("bad", [{"institution": None}, {"act_scope": ""},
                                 {"act_version": "   "}, {"act": "?"}])
def test_an_empty_subject_field_blocks_the_claim(bad):
    """Um sujeito com campo vazio formatava "None" na alegação e era permitido."""
    subject = {"institution": "I", "act": "a", "act_version": "1", "act_scope": "s"}
    subject.update(bad)
    result = evaluate_claim(
        CLAIM_INSTITUTION_ACCEPTED,
        profile_state="verified",
        evidence={
            "real_act_by_institution": {"basis": "ofício de aceitação expressa"},
            "act_type_is_homologacao_or_explicit_acceptance": {"basis": "aceitação expressa"},
            "act_version_and_scope_recorded": {"basis": "registrado"},
        },
        subject=subject,
    )
    assert result["state"] == CLAIM_BLOCKED
    assert result["permitted_wording"] is None
    assert any(m.startswith("subject.") for m in result["missing"])


# --- Defeito 6: reaproveitamento sem escopo de destino -------------------

def test_reuse_is_refused_when_the_target_scope_is_not_named():
    claim = {"kind": CLAIM_INSTITUTION_ACCEPTED,
             "granted_scope": {"profile": "p-a", "version": "1.0.0"}}
    assert reuse_acceptance_check(claim)["reusable"] is False
    assert reuse_acceptance_check(claim, target_profile="p-a")["reusable"] is False
    assert reuse_acceptance_check(claim, target_version="1.0.0")["reusable"] is False
    assert reuse_acceptance_check(claim, target_profile="p-a", target_version="1.0.0")["reusable"] is True
    assert reuse_acceptance_check(claim, target_profile="p-b", target_version="1.0.0")["reusable"] is False
    assert reuse_acceptance_check(claim, target_profile="p-a", target_version="2.0.0")["reusable"] is False


# --- Defeito 7: a vedação do Anexo A.2 g) era só um aviso ----------------

def _context_with_incoherent_multicollinearity():
    return {
        "n": 40, "k": 3, "intercept": True, "category_counts": {"esquina": 6},
        "axes": [{"name": "area", "kind": "quantitative", "avaliando_value": 120,
                  "sample_min": 50, "sample_max": 200}],
        "subject_raw": {"area": 120},
        "pvalues": {"area": 0.01}, "f_pvalue": 0.0001, "amplitude_pct": 22.0,
        "documentary": {"item1": {"grade": 3, "provenance": {"s": "vistoria"}},
                        "item3": {"grade": 3, "provenance": {"s": "planilha"}}},
        "professional_findings": {
            "anexoA.2.g.multicolinearidade": {
                "satisfied": False,
                "justification": "características do avaliando incoerentes com a estrutura inferida",
            }
        },
    }


def test_anexo_a2_g_violation_is_a_prohibition_not_a_generic_warning():
    """A.2 g) é a única cláusula do bloco que VEDA usar o modelo; era emitida
    com o mesmo código de qualquer pressuposto violado."""
    assessment = assess_normative(_context_with_incoherent_multicollinearity())
    prohibited = assessment["model_use_prohibited"]
    assert [p["rule_id"] for p in prohibited] == ["anexoA.2.g.multicolinearidade"]
    assert "vedada" in (prohibited[0]["prohibition"] or "").lower()
    codes = {i.get("code") for i in assessment["issues"]}
    assert "model_use_prohibited" in codes
    errors = {i.get("code") for i in assessment["issues"] if i.get("severity") == "error"}
    assert "model_use_prohibited" in errors


def test_the_prohibition_blocks_release_and_review_cannot_lift_it():
    assessment = assess_normative(_context_with_incoherent_multicollinearity())
    evidence = {k: {"ref": k} for k in (
        "9.2.1.1.a", "9.2.1.1.b", "9.2.1.1.c", "9.2.1.1.d",
        "parte1.6.3.vistoria", "8.2.1.5.2.campo_suficiente", "10.1.laudo_completo")}
    profile = {"id": "abnt-14653-2-regressao-mercado"}
    first = assess_qualification(
        {"normative_assessment": assessment, "profile_evidence": evidence,
         "targets_grau_iii": True}, profile)
    assert first["case_release_status"] == "analysis_only"
    blocker = [b for b in first["release_blockers"] if b["code"] == "model_use_prohibited"]
    assert blocker, first["release_blockers"]
    assert blocker[0]["rule_id"] == "anexoA.2.g.multicolinearidade"

    # Uma revisão profissional válida e uma assinatura íntegra não superam a
    # vedação: a norma proíbe usar o modelo, não pede um segundo parecer.
    signed = dict(
        normative_assessment=assessment, profile_evidence=evidence, targets_grau_iii=True,
        review_events=[{"professional_id": "CREA-1", "motive": "revisão",
                        "version": "v", "fingerprint": first["result_fingerprint"]}],
        signature={"integrity_verified": True, "fingerprint": first["result_fingerprint"]},
    )
    after = assess_qualification(signed, profile)
    assert after["case_release_status"] == "analysis_only"
    assert any(b["code"] == "model_use_prohibited" for b in after["release_blockers"])


def test_a_coherent_multicollinearity_finding_does_not_prohibit_use():
    ctx = _context_with_incoherent_multicollinearity()
    ctx["professional_findings"]["anexoA.2.g.multicolinearidade"] = {
        "satisfied": True, "justification": "coerência examinada e registrada"}
    assessment = assess_normative(ctx)
    assert assessment["model_use_prohibited"] == []
    assert "model_use_prohibited" not in {i.get("code") for i in assessment["issues"]}


# --- Defeito 8: perfil não verificado não sustenta alegação --------------

@pytest.mark.parametrize("state", ["pending", "discovery", "blocked_external_evidence", "unknown"])
def test_an_unverified_profile_structurally_blocks_its_scoped_claims(state):
    result = evaluate_claim(
        CLAIM_PROFILE_COMPATIBLE,
        profile_state=state,
        evidence={"profile_obtained_from_legitimate_source": {"basis": "fonte oficial"},
                  "profile_state_verified": {"basis": "conferido"},
                  "product_emits_profile_requirements": {"basis": "emitido"}},
        subject={"profile": "p", "profile_version": "1.0.0"},
    )
    assert result["state"] == CLAIM_BLOCKED
    assert "profile_state_verified" in result["missing"]
