"""Conformidade da saída contra o padrão documental do destinatário.

O que estes testes fixam é a semântica de "seria aceito sem ressalvas": ela tem
de ser difícil de satisfazer por acidente e impossível de satisfazer por
declaração vazia.
"""

from __future__ import annotations

import pytest

from modules.qualification_profile import (
    OutputRequirementError,
    assess_output_conformance,
    assess_qualification,
    product_conformance_baseline,
)
from modules.qualification_profile.output_conformance import (
    KIND_ATTACHMENT,
    KIND_CALCULATED,
    KIND_CHART,
    KIND_HUMAN,
    STATE_EMITTED,
    STATE_HUMAN_INPUT,
    STATE_MISSING,
    STATE_PARTIAL,
)
from modules.qualification_profile.schema import (
    RULE_FAILED,
    RULE_NOT_APPLICABLE,
    RULE_PASSED,
    RULE_PENDING_MANUAL,
    RULE_UNSUPPORTED,
)


def _req(rid, baseline=STATE_EMITTED, kind=KIND_CALCULATED, **kw):
    r = {
        "id": rid,
        "clause": f"clausula {rid}",
        "requirement": f"requisito {rid}",
        "kind": kind,
        "product_baseline": baseline,
    }
    if baseline in (STATE_PARTIAL, STATE_MISSING):
        r.setdefault("gap", f"lacuna de {rid}")
        r.setdefault("owner", "C03")
    r.update(kw)
    return r


def _profile(*reqs, pid="perfil-teste", version="1.0.0"):
    return {"id": pid, "version": version, "output_requirements": list(reqs)}


# --- a barra de "sem ressalvas" ------------------------------------------

def test_all_requirements_emitted_and_declared_is_accepted_without_reservations():
    profile = _profile(_req("r1"), _req("r2"))
    out = assess_output_conformance(profile, {"r1": "pg. 4", "r2": "anexo II"})
    assert out["would_be_accepted_without_reservations"] is True
    assert out["blocking"] == []
    assert out["conforming"] == 2
    assert all(r["status"] == RULE_PASSED for r in out["rule_results"])


def test_an_empty_manifest_is_never_accepted_without_reservations():
    """Ausência no manifesto não é conformidade, mesmo com o produto emitindo."""
    profile = _profile(_req("r1"), _req("r2"))
    out = assess_output_conformance(profile, {})
    assert out["would_be_accepted_without_reservations"] is False
    assert {b["code"] for b in out["blocking"]} == {"output_requirement_not_in_manifest"}
    assert all(r["status"] == RULE_PENDING_MANUAL for r in out["rule_results"])


def test_no_requirements_at_all_is_not_a_pass():
    """Um perfil sem requisitos de saída não licencia 'sem ressalvas' por vacuidade."""
    out = assess_output_conformance(_profile(), {})
    assert out["would_be_accepted_without_reservations"] is False
    assert out["applicable_requirements"] == 0


def test_one_missing_requirement_blocks_the_whole_verdict():
    profile = _profile(_req("r1"), _req("r2", baseline=STATE_MISSING))
    out = assess_output_conformance(profile, {"r1": "pg. 4", "r2": "eu declaro que sim"})
    assert out["would_be_accepted_without_reservations"] is False
    statuses = {r["rule_id"]: r["status"] for r in out["rule_results"]}
    assert statuses["r2"] == RULE_UNSUPPORTED
    assert out["product_gaps"][0]["requirement_id"] == "r2"


def test_declaring_a_missing_item_present_does_not_make_it_present():
    """A evidência de caso não conserta lacuna do produto: se o produto não
    emite, declarar que emitiu não o torna emitido."""
    profile = _profile(_req("r1", baseline=STATE_MISSING))
    out = assess_output_conformance(profile, {"r1": {"ref": "está no laudo, juro"}})
    assert out["would_be_accepted_without_reservations"] is False
    assert out["rule_results"][0]["status"] == RULE_UNSUPPORTED


def test_partial_is_a_failure_not_a_near_miss():
    """PARTIAL é entregar algo próximo do exigido — CSV onde se pede Excel,
    R² onde se pede R. Conta como falha, não como quase-conformidade."""
    profile = _profile(_req("r1", baseline=STATE_PARTIAL,
                            gap="exporta CSV; o padrão exige Excel", owner="C03"))
    out = assess_output_conformance(profile, {"r1": "amostra.csv"})
    assert out["rule_results"][0]["status"] == RULE_FAILED
    assert out["would_be_accepted_without_reservations"] is False
    assert "Excel" in out["blocking"][0]["detail"]


# --- conteúdo humano ------------------------------------------------------

def test_human_content_is_pending_until_recorded_then_conforms():
    profile = _profile(_req("h1", baseline=STATE_HUMAN_INPUT, kind=KIND_HUMAN))
    pending = assess_output_conformance(profile, {})
    assert pending["rule_results"][0]["status"] == RULE_PENDING_MANUAL
    assert pending["awaiting_human"] == ["h1"]
    assert pending["would_be_accepted_without_reservations"] is False

    done = assess_output_conformance(profile, {"h1": {"by": "CREA-SC-1", "ref": "p.1"}})
    assert done["rule_results"][0]["status"] == RULE_PASSED
    assert done["would_be_accepted_without_reservations"] is True


# --- requisito condicional -----------------------------------------------

def test_a_conditional_requirement_is_not_applicable_when_its_condition_is_absent():
    profile = _profile(_req("c1", applies_when="uses_inference"))
    out = assess_output_conformance(profile, {})
    res = out["rule_results"][0]
    assert res["status"] == RULE_NOT_APPLICABLE
    assert res["not_applicable_reason"]
    assert out["not_applicable"] == ["c1"]
    # não aplicável não bloqueia, mas também não conta como conforme
    assert out["conforming"] == 0
    assert out["applicable_requirements"] == 0
    assert out["would_be_accepted_without_reservations"] is False


def test_a_conditional_requirement_applies_when_its_condition_holds():
    profile = _profile(_req("c1", applies_when="uses_inference"))
    out = assess_output_conformance(profile, {"uses_inference": True, "c1": "pg. 9"})
    assert out["rule_results"][0]["status"] == RULE_PASSED
    assert out["would_be_accepted_without_reservations"] is True


# --- o catálogo tem de ser auditável -------------------------------------

@pytest.mark.parametrize("bad,missing", [
    ({"clause": "c", "requirement": "r", "kind": KIND_CALCULATED, "product_baseline": STATE_EMITTED}, "id"),
    ({"id": "x", "requirement": "r", "kind": KIND_CALCULATED, "product_baseline": STATE_EMITTED}, "clause"),
    ({"id": "x", "clause": "c", "kind": KIND_CALCULATED, "product_baseline": STATE_EMITTED}, "requirement"),
    ({"id": "x", "clause": "c", "requirement": "r", "product_baseline": STATE_EMITTED}, "kind"),
    ({"id": "x", "clause": "c", "requirement": "r", "kind": KIND_CALCULATED}, "product_baseline"),
])
def test_a_malformed_output_requirement_is_refused(bad, missing):
    with pytest.raises(OutputRequirementError) as exc:
        assess_output_conformance(_profile(bad), {})
    assert missing in str(exc.value)


def test_an_invalid_kind_or_baseline_is_refused():
    with pytest.raises(OutputRequirementError):
        assess_output_conformance(_profile(_req("x", kind="inventado")), {})
    with pytest.raises(OutputRequirementError):
        assess_output_conformance(_profile(_req("x", baseline="quase")), {})


def test_a_gap_without_description_or_owner_is_refused():
    """Lacuna sem descrição não é auditável; lacuna sem dono não é endereçável."""
    with pytest.raises(OutputRequirementError, match="gap"):
        assess_output_conformance(_profile(
            {"id": "g", "clause": "c", "requirement": "r", "kind": KIND_CHART,
             "product_baseline": STATE_MISSING}), {})
    with pytest.raises(OutputRequirementError, match="owner"):
        assess_output_conformance(_profile(
            {"id": "g", "clause": "c", "requirement": "r", "kind": KIND_CHART,
             "product_baseline": STATE_MISSING, "gap": "não gera"}), {})


# --- baseline do PRODUTO, distinto do caso -------------------------------

def test_product_baseline_is_about_the_software_not_a_case():
    profile = _profile(
        _req("a"), _req("b"),
        _req("c", baseline=STATE_HUMAN_INPUT, kind=KIND_HUMAN),
        _req("d", baseline=STATE_MISSING, kind=KIND_ATTACHMENT,
             gap="não exporta Excel", owner="C03"),
    )
    base = product_conformance_baseline(profile)
    assert base["counts"] == {"emitted": 2, "partial": 0, "missing": 1, "human_input": 1}
    assert base["product_can_meet_standard"] is False
    assert base["requires_human_input"] == ["c"]
    assert base["product_gaps"][0]["owner"] == "C03"
    # depender do profissional NÃO é lacuna do produto
    ok = _profile(_req("a"), _req("c", baseline=STATE_HUMAN_INPUT, kind=KIND_HUMAN))
    assert product_conformance_baseline(ok)["product_can_meet_standard"] is True


# --- integração com assess_qualification ---------------------------------

def test_an_output_gap_blocks_case_release():
    from modules.nbr14653_validation import assess_normative
    assessment = assess_normative({
        "n": 40, "k": 3, "intercept": True, "category_counts": {"a": 6},
        "axes": [{"name": "area", "kind": "quantitative", "avaliando_value": 120,
                  "sample_min": 50, "sample_max": 200}],
        "subject_raw": {"area": 120}, "pvalues": {"area": 0.01},
        "f_pvalue": 0.0001, "amplitude_pct": 22.0,
        "documentary": {"item1": {"grade": 3, "provenance": {"s": "v"}},
                        "item3": {"grade": 3, "provenance": {"s": "p"}}},
    })
    block = assess_qualification(
        {"normative_assessment": assessment}, {"id": "bb-meci-avaliacao-imovel-pf"})
    # o perfil real do BB carrega requisitos de saída; nenhum manifesto foi dado
    assert block["output_conformance"]["would_be_accepted_without_reservations"] is False
    assert block["case_release_status"] == "analysis_only"
    codes = {b["code"] for b in block["release_blockers"]}
    assert any(c.startswith("output_requirement_") for c in codes), codes


def test_the_verdict_is_not_institutional_acceptance():
    """Atender ao padrão publicado não é a instituição ter aceitado."""
    profile = _profile(_req("r1"))
    out = assess_output_conformance(profile, {"r1": "pg. 4"})
    assert out["would_be_accepted_without_reservations"] is True
    assert "não é aceitação pela instituição" in out["note"].lower()
    block = assess_qualification({}, {"id": "bb-meci-avaliacao-imovel-pf"})
    assert block["institution_acceptance"]["recorded"] is False
