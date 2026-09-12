"""C05-A08 — alegações comerciais limitadas pela prova.

Every expected value here is derived from the A08 contract itself (the four
claim kinds, their scopes and their prerequisite/forbidden-substitute lists),
never from running the code and transcribing its output. The governing policy:

  * a claim without its prerequisites is BLOCKED and must NAME what is missing
    (absence of proof is never implicit permission, and never a silent
    downgrade to a weaker-but-still-green claim);
  * a prerequisite that is formally present but backed by a forbidden
    substitute is REJECTED;
  * a permitted claim must carry wording that pins the version/edition/profile
    it is scoped to, because an unversioned claim is not verifiable;
  * an institutional acceptance never travels outside the exact profile and
    version it was granted for.
"""

from __future__ import annotations

import pytest

from modules.qualification_profile.claims import (
    CLAIM_BLOCKED,
    CLAIM_CALCULATION_VERIFIED,
    CLAIM_IMPLEMENTS_REQUIREMENTS,
    CLAIM_INSTITUTION_ACCEPTED,
    CLAIM_KINDS,
    CLAIM_PERMITTED,
    CLAIM_PREREQUISITES,
    CLAIM_PROFILE_COMPATIBLE,
    CLAIM_SCOPE,
    CLAIMS_REGISTRY_VERSION,
    ClaimNotPermitted,
    assert_claim,
    evaluate_claim,
    reuse_acceptance_check,
)

# --------------------------------------------------------------------------
# Hand-written fixtures: the complete prerequisite set and the complete
# subject for each kind, written out by hand from the A08 contract.
# --------------------------------------------------------------------------

FULL_EVIDENCE = {
    CLAIM_CALCULATION_VERIFIED: {
        "independent_numeric_reference_passed": {
            "basis": "planilha de referência publicada por terceiro, recalculada à mão",
            "ref": "REF-NUM-001",
        },
        "software_version_identified": {"basis": "tag git assinada", "ref": "v3.2.1"},
    },
    CLAIM_IMPLEMENTS_REQUIREMENTS: {
        "rules_implemented_and_tested": {"basis": "suíte de testes de limiar", "ref": "T-001"},
        "thresholds_read_against_edition": {
            "basis": "leitura direta da Tabela 1 da edição licenciada",
            "ref": "LEIT-001",
        },
        "edition_identified": {"basis": "exemplar licenciado", "ref": "NBR 14653-2:2011"},
    },
    CLAIM_PROFILE_COMPATIBLE: {
        "profile_obtained_from_legitimate_source": {
            "basis": "normativo publicado pela própria instituição",
            "ref": "SRC-001",
        },
        "profile_state_verified": {"basis": "sha256 do conjunto de fontes", "ref": "SHA-001"},
        "product_emits_profile_requirements": {"basis": "laudo de conformidade item a item", "ref": "EMIT-001"},
    },
    CLAIM_INSTITUTION_ACCEPTED: {
        "real_act_by_institution": {"basis": "ofício de homologação emitido pela instituição", "ref": "ACT-001"},
        "act_type_is_homologacao_or_explicit_acceptance": {
            "basis": "homologação expressa",
            "ref": "ACT-001",
        },
        "act_version_and_scope_recorded": {"basis": "anexo do ofício", "ref": "ACT-001-ANEXO"},
    },
}

FULL_SUBJECT = {
    CLAIM_CALCULATION_VERIFIED: {"reference": "REF-NUM-001", "version": "v3.2.1"},
    CLAIM_IMPLEMENTS_REQUIREMENTS: {
        "requirements": "Tabela 1 itens 2, 4, 5 e 6",
        "edition": "NBR 14653-2:2011",
    },
    CLAIM_PROFILE_COMPATIBLE: {"profile": "perfil-banco-x", "profile_version": "2024-03"},
    CLAIM_INSTITUTION_ACCEPTED: {
        "institution": "Instituição X",
        "act": "Ofício 12/2026",
        "act_version": "v3.2.1",
        "act_scope": "perfil-banco-x",
    },
}

#: The subject value that carries the version/edition/profile the claim is
#: scoped to — the token whose presence in the wording makes it verifiable.
SCOPING_SUBJECT_KEYS = {
    CLAIM_CALCULATION_VERIFIED: ["version"],
    CLAIM_IMPLEMENTS_REQUIREMENTS: ["edition"],
    CLAIM_PROFILE_COMPATIBLE: ["profile", "profile_version"],
    CLAIM_INSTITUTION_ACCEPTED: ["institution", "act_version", "act_scope"],
}


# --------------------------------------------------------------------------
# The registry itself: versioned, four kinds, distinct scopes
# --------------------------------------------------------------------------


def test_registry_is_versioned():
    assert isinstance(CLAIMS_REGISTRY_VERSION, str)
    assert CLAIMS_REGISTRY_VERSION.strip() != ""


def test_exactly_the_four_claim_kinds_exist():
    assert set(CLAIM_KINDS) == {
        CLAIM_CALCULATION_VERIFIED,
        CLAIM_IMPLEMENTS_REQUIREMENTS,
        CLAIM_PROFILE_COMPATIBLE,
        CLAIM_INSTITUTION_ACCEPTED,
    }
    assert len(CLAIM_KINDS) == 4


def test_each_claim_kind_has_its_own_distinct_scope():
    scopes = [CLAIM_SCOPE[kind] for kind in CLAIM_KINDS]
    assert len(set(scopes)) == 4, f"escopos conflatados: {scopes}"
    for kind in CLAIM_KINDS:
        assert CLAIM_SCOPE[kind].strip() != ""
    # A case-level/institutional fact must not be scoped as a bare product fact.
    assert CLAIM_SCOPE[CLAIM_CALCULATION_VERIFIED] != CLAIM_SCOPE[CLAIM_INSTITUTION_ACCEPTED]
    assert CLAIM_SCOPE[CLAIM_PROFILE_COMPATIBLE] != CLAIM_SCOPE[CLAIM_INSTITUTION_ACCEPTED]


def test_prerequisites_cover_every_kind_with_non_empty_lists():
    assert set(CLAIM_PREREQUISITES) == set(CLAIM_KINDS)
    for kind in CLAIM_KINDS:
        spec = CLAIM_PREREQUISITES[kind]
        assert spec["requires"], f"{kind} sem pré-requisitos"
        assert spec["forbidden_substitutes"], f"{kind} sem substitutos vedados"
        assert spec["wording_template"].strip() != ""


def test_unknown_claim_kind_raises_value_error():
    with pytest.raises(ValueError):
        evaluate_claim("aprovado_pelo_orgao")
    with pytest.raises(ValueError):
        evaluate_claim("")
    # assert_claim delegates the kind check, so it is a ValueError there too —
    # never a ClaimNotPermitted, which would imply the kind was recognised.
    with pytest.raises(ValueError):
        assert_claim("certificado_pela_abnt", evidence={}, subject={})


# --------------------------------------------------------------------------
# Absence is not approval
# --------------------------------------------------------------------------


@pytest.mark.parametrize("kind", CLAIM_KINDS)
def test_claim_without_any_evidence_is_blocked_and_names_every_missing_prerequisite(kind):
    result = evaluate_claim(kind, evidence=None, subject=FULL_SUBJECT[kind])
    expected_missing = list(CLAIM_PREREQUISITES[kind]["requires"])

    assert result["state"] == CLAIM_BLOCKED
    assert result["permitted_wording"] is None
    assert result["missing"] == expected_missing
    assert result["kind"] == kind
    assert result["scope"] == CLAIM_SCOPE[kind]
    assert result["registry_version"] == CLAIMS_REGISTRY_VERSION
    # It must SAY what is missing, not merely be falsy.
    for req in expected_missing:
        assert req in result["detail"]


@pytest.mark.parametrize("kind", CLAIM_KINDS)
def test_blocked_claim_is_never_downgraded_to_another_kind(kind):
    """A blocked claim stays this kind, blocked. No fallback to a weaker claim."""
    result = evaluate_claim(kind, evidence={}, subject=FULL_SUBJECT[kind])
    assert result["kind"] == kind
    assert result["state"] == CLAIM_BLOCKED
    assert result["state"] != CLAIM_PERMITTED
    assert result["permitted_wording"] is None
    assert result["scope"] == CLAIM_SCOPE[kind]


@pytest.mark.parametrize("kind", CLAIM_KINDS)
def test_one_missing_prerequisite_out_of_all_still_blocks(kind):
    requires = list(CLAIM_PREREQUISITES[kind]["requires"])
    for dropped in requires:
        evidence = {k: v for k, v in FULL_EVIDENCE[kind].items() if k != dropped}
        result = evaluate_claim(kind, evidence=evidence, subject=FULL_SUBJECT[kind])
        assert result["state"] == CLAIM_BLOCKED, f"{kind} permitida sem {dropped}"
        assert result["missing"] == [dropped]
        assert result["permitted_wording"] is None


@pytest.mark.parametrize("kind", CLAIM_KINDS)
def test_falsy_evidence_reference_does_not_count_as_evidence(kind):
    """An empty string / None placed in the evidence slot is still absence."""
    for placeholder in (None, "", {}, 0, False):
        evidence = dict(FULL_EVIDENCE[kind])
        first = CLAIM_PREREQUISITES[kind]["requires"][0]
        evidence[first] = placeholder
        result = evaluate_claim(kind, evidence=evidence, subject=FULL_SUBJECT[kind])
        assert result["state"] == CLAIM_BLOCKED, f"{kind}: {placeholder!r} aceito como prova"
        assert first in result["missing"]


# --------------------------------------------------------------------------
# Forbidden substitutes: present but rejected
# --------------------------------------------------------------------------


def _forbidden(kind, needle):
    """The registry's own wording for a forbidden substitute matching needle."""
    hits = [f for f in CLAIM_PREREQUISITES[kind]["forbidden_substitutes"] if needle in f]
    assert hits, f"{needle!r} não consta em forbidden_substitutes de {kind}"
    return hits[0]


@pytest.mark.parametrize(
    "needle",
    [
        "credenciamento profissional",
        "supplier registry / cadastro de fornecedor",
        "a digital signature or an authorship record",
    ],
)
def test_institution_accepted_rejects_forbidden_basis_even_with_all_keys_present(needle):
    kind = CLAIM_INSTITUTION_ACCEPTED
    forbidden = _forbidden(kind, needle)
    target = "real_act_by_institution"

    evidence = dict(FULL_EVIDENCE[kind])
    evidence[target] = {"basis": f"documento apresentado: {forbidden}", "ref": "DOC-9"}

    result = evaluate_claim(kind, evidence=evidence, subject=FULL_SUBJECT[kind])

    # Every prerequisite KEY is present — nothing is missing — and yet the
    # claim is blocked, because the basis offered is not the required act.
    assert result["missing"] == []
    assert result["state"] == CLAIM_BLOCKED
    assert result["permitted_wording"] is None
    assert any(
        r["requirement"] == target and r["forbidden"] == forbidden for r in result["rejected"]
    ), result["rejected"]


def test_calculation_verified_rejects_an_oracle_generated_by_the_code_under_test():
    kind = CLAIM_CALCULATION_VERIFIED
    forbidden = _forbidden(kind, "an oracle generated by the very code under test")
    target = "independent_numeric_reference_passed"

    evidence = dict(FULL_EVIDENCE[kind])
    evidence[target] = {"basis": forbidden, "ref": "SELF-ORACLE"}

    result = evaluate_claim(kind, evidence=evidence, subject=FULL_SUBJECT[kind])

    assert result["missing"] == []
    assert result["state"] == CLAIM_BLOCKED
    assert result["permitted_wording"] is None
    assert [(r["requirement"], r["forbidden"]) for r in result["rejected"]] == [(target, forbidden)]


def test_calculation_verified_rejects_the_products_own_tests_as_the_reference():
    kind = CLAIM_CALCULATION_VERIFIED
    forbidden = _forbidden(kind, "passing the product's own tests only")
    evidence = dict(FULL_EVIDENCE[kind])
    evidence["independent_numeric_reference_passed"] = {"basis": forbidden}
    result = evaluate_claim(kind, evidence=evidence, subject=FULL_SUBJECT[kind])
    assert result["state"] == CLAIM_BLOCKED
    assert result["rejected"]


def test_permissive_library_licence_can_never_satisfy_institution_accepted():
    kind = CLAIM_INSTITUTION_ACCEPTED
    forbidden = _forbidden(kind, "permissive licence")
    assert forbidden in CLAIM_PREREQUISITES[kind]["forbidden_substitutes"]

    for target in CLAIM_PREREQUISITES[kind]["requires"]:
        evidence = dict(FULL_EVIDENCE[kind])
        evidence[target] = {"basis": forbidden, "ref": "LICENSE"}
        result = evaluate_claim(kind, evidence=evidence, subject=FULL_SUBJECT[kind])
        assert result["state"] == CLAIM_BLOCKED, f"licença permissiva aceita em {target}"
        assert result["missing"] == []
        assert any(r["requirement"] == target for r in result["rejected"])


def test_professionals_own_certification_can_never_satisfy_institution_accepted():
    kind = CLAIM_INSTITUTION_ACCEPTED
    forbidden = _forbidden(kind, "a professional's own certification")
    assert forbidden in CLAIM_PREREQUISITES[kind]["forbidden_substitutes"]

    for target in CLAIM_PREREQUISITES[kind]["requires"]:
        evidence = dict(FULL_EVIDENCE[kind])
        evidence[target] = {"basis": forbidden, "ref": "CERT-CREA"}
        result = evaluate_claim(kind, evidence=evidence, subject=FULL_SUBJECT[kind])
        assert result["state"] == CLAIM_BLOCKED, f"certificação do profissional aceita em {target}"
        assert result["missing"] == []
        assert any(r["requirement"] == target for r in result["rejected"])


def test_profile_compatible_rejects_inference_from_a_supplier_registry_or_one_laudo():
    kind = CLAIM_PROFILE_COMPATIBLE
    for needle in ("inferring the profile from a supplier registry",
                   "inferring the profile from one accepted laudo"):
        forbidden = _forbidden(kind, needle)
        evidence = dict(FULL_EVIDENCE[kind])
        evidence["profile_obtained_from_legitimate_source"] = {"basis": forbidden}
        result = evaluate_claim(kind, evidence=evidence, subject=FULL_SUBJECT[kind])
        assert result["state"] == CLAIM_BLOCKED
        assert result["missing"] == []
        assert result["rejected"]


def test_implements_requirements_rejects_readme_labels_and_model_memory():
    kind = CLAIM_IMPLEMENTS_REQUIREMENTS
    for needle in ("clause labels copied from a README or a secondary source",
                   "model memory of the threshold"):
        forbidden = _forbidden(kind, needle)
        evidence = dict(FULL_EVIDENCE[kind])
        evidence["thresholds_read_against_edition"] = {"basis": forbidden}
        result = evaluate_claim(kind, evidence=evidence, subject=FULL_SUBJECT[kind])
        assert result["state"] == CLAIM_BLOCKED
        assert result["missing"] == []
        assert result["rejected"]


# --------------------------------------------------------------------------
# Permitted claims: scoped wording
# --------------------------------------------------------------------------


@pytest.mark.parametrize("kind", CLAIM_KINDS)
def test_full_evidence_and_complete_subject_is_permitted_with_scoped_wording(kind):
    result = evaluate_claim(kind, evidence=FULL_EVIDENCE[kind], subject=FULL_SUBJECT[kind])

    assert result["state"] == CLAIM_PERMITTED
    assert result["missing"] == []
    assert result["rejected"] == []
    assert result["kind"] == kind
    assert result["scope"] == CLAIM_SCOPE[kind]
    assert result["registry_version"] == CLAIMS_REGISTRY_VERSION

    wording = result["permitted_wording"]
    assert isinstance(wording, str) and wording.strip() != ""
    # The wording must pin the version / edition / profile it is scoped to.
    for key in SCOPING_SUBJECT_KEYS[kind]:
        assert str(FULL_SUBJECT[kind][key]) in wording, (key, wording)

    # Every prerequisite's evidence reference is carried on the permitted claim.
    assert len(result["evidence_refs"]) == len(CLAIM_PREREQUISITES[kind]["requires"])


def test_profile_compatible_wording_does_not_claim_acceptance():
    result = evaluate_claim(
        CLAIM_PROFILE_COMPATIBLE,
        evidence=FULL_EVIDENCE[CLAIM_PROFILE_COMPATIBLE],
        subject=FULL_SUBJECT[CLAIM_PROFILE_COMPATIBLE],
    )
    assert result["state"] == CLAIM_PERMITTED
    wording = result["permitted_wording"].lower()
    assert "não é aceitação" in wording or "nao e aceitacao" in wording


# --------------------------------------------------------------------------
# Incomplete subject: an unversioned claim is not verifiable
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,missing_key",
    [
        (CLAIM_CALCULATION_VERIFIED, "version"),
        (CLAIM_CALCULATION_VERIFIED, "reference"),
        (CLAIM_IMPLEMENTS_REQUIREMENTS, "edition"),
        (CLAIM_IMPLEMENTS_REQUIREMENTS, "requirements"),
        (CLAIM_PROFILE_COMPATIBLE, "profile"),
        (CLAIM_PROFILE_COMPATIBLE, "profile_version"),
        (CLAIM_INSTITUTION_ACCEPTED, "act"),
        (CLAIM_INSTITUTION_ACCEPTED, "act_version"),
        (CLAIM_INSTITUTION_ACCEPTED, "act_scope"),
        (CLAIM_INSTITUTION_ACCEPTED, "institution"),
    ],
)
def test_incomplete_subject_blocks_even_with_all_prerequisites(kind, missing_key):
    subject = {k: v for k, v in FULL_SUBJECT[kind].items() if k != missing_key}
    result = evaluate_claim(kind, evidence=FULL_EVIDENCE[kind], subject=subject)

    assert result["state"] == CLAIM_BLOCKED, f"{kind} permitida sem subject.{missing_key}"
    assert result["permitted_wording"] is None
    assert result["missing"] == [f"subject.{missing_key}"]
    assert missing_key in result["detail"]
    assert result["registry_version"] == CLAIMS_REGISTRY_VERSION


@pytest.mark.parametrize("kind", CLAIM_KINDS)
def test_no_subject_at_all_blocks(kind):
    result = evaluate_claim(kind, evidence=FULL_EVIDENCE[kind], subject=None)
    assert result["state"] == CLAIM_BLOCKED
    assert result["permitted_wording"] is None
    assert result["missing"] and result["missing"][0].startswith("subject.")


# --------------------------------------------------------------------------
# assert_claim
# --------------------------------------------------------------------------


@pytest.mark.parametrize("kind", CLAIM_KINDS)
def test_assert_claim_raises_for_a_blocked_claim(kind):
    with pytest.raises(ClaimNotPermitted):
        assert_claim(kind, evidence={}, subject=FULL_SUBJECT[kind])
    with pytest.raises(ClaimNotPermitted):
        assert_claim(kind, evidence=FULL_EVIDENCE[kind], subject={})


@pytest.mark.parametrize("kind", CLAIM_KINDS)
def test_assert_claim_returns_payload_for_a_permitted_claim(kind):
    payload = assert_claim(kind, evidence=FULL_EVIDENCE[kind], subject=FULL_SUBJECT[kind])
    assert payload["state"] == CLAIM_PERMITTED
    assert payload["kind"] == kind
    assert payload["scope"] == CLAIM_SCOPE[kind]
    assert payload["permitted_wording"]


def test_assert_claim_message_explains_the_absence_of_proof():
    kind = CLAIM_INSTITUTION_ACCEPTED
    with pytest.raises(ClaimNotPermitted) as exc:
        assert_claim(kind, evidence={}, subject=FULL_SUBJECT[kind])
    message = str(exc.value)
    for req in CLAIM_PREREQUISITES[kind]["requires"]:
        assert req in message


# --------------------------------------------------------------------------
# Re-use of an institutional acceptance
# --------------------------------------------------------------------------

GRANTED = {
    "kind": CLAIM_INSTITUTION_ACCEPTED,
    "state": CLAIM_PERMITTED,
    "granted_scope": {"profile": "perfil-banco-x", "version": "v3.2.1"},
}


def test_reuse_confirmed_only_inside_the_exact_granted_scope():
    out = reuse_acceptance_check(
        GRANTED, target_profile="perfil-banco-x", target_version="v3.2.1"
    )
    assert out["reusable"] is True
    assert "perfil-banco-x" in out["detail"]
    assert "v3.2.1" in out["detail"]


def test_reuse_refused_for_a_different_profile():
    out = reuse_acceptance_check(
        GRANTED, target_profile="perfil-banco-y", target_version="v3.2.1"
    )
    assert out["reusable"] is False
    # The refusal must name the scope mismatch: both the granted profile and
    # the profile being asked for.
    assert "perfil-banco-x" in out["detail"]
    assert "perfil-banco-y" in out["detail"]
    assert "perfil" in out["detail"].lower()


def test_reuse_refused_for_a_different_version():
    out = reuse_acceptance_check(
        GRANTED, target_profile="perfil-banco-x", target_version="v4.0.0"
    )
    assert out["reusable"] is False
    assert "v3.2.1" in out["detail"]
    assert "v4.0.0" in out["detail"]
    assert "vers" in out["detail"].lower()


def test_reuse_refused_for_a_different_profile_and_version():
    out = reuse_acceptance_check(
        GRANTED, target_profile="perfil-banco-y", target_version="v4.0.0"
    )
    assert out["reusable"] is False
    assert "perfil-banco-y" in out["detail"]
    assert "v4.0.0" in out["detail"]


def test_reuse_refused_when_the_target_scope_is_unspecified():
    """An unspecified target is not "the exact granted scope" — it is a missing
    datum, and absence of data must never read as permission to re-use."""
    both_omitted = reuse_acceptance_check(GRANTED)
    assert both_omitted["reusable"] is False

    version_omitted = reuse_acceptance_check(GRANTED, target_profile="perfil-banco-x")
    assert version_omitted["reusable"] is False

    profile_omitted = reuse_acceptance_check(GRANTED, target_version="v3.2.1")
    assert profile_omitted["reusable"] is False


def test_reuse_refused_when_no_scope_was_ever_granted():
    claim = {"kind": CLAIM_INSTITUTION_ACCEPTED, "state": CLAIM_PERMITTED}
    out = reuse_acceptance_check(claim, target_profile="perfil-banco-x", target_version="v3.2.1")
    assert out["reusable"] is False


@pytest.mark.parametrize(
    "kind", [CLAIM_CALCULATION_VERIFIED, CLAIM_IMPLEMENTS_REQUIREMENTS, CLAIM_PROFILE_COMPATIBLE]
)
def test_only_an_institutional_acceptance_has_a_reusable_scope(kind):
    claim = {"kind": kind, "granted_scope": {"profile": "perfil-banco-x", "version": "v3.2.1"}}
    out = reuse_acceptance_check(claim, target_profile="perfil-banco-x", target_version="v3.2.1")
    assert out["reusable"] is False


def test_reuse_refused_for_a_claim_with_no_kind():
    out = reuse_acceptance_check({}, target_profile="p", target_version="v")
    assert out["reusable"] is False
