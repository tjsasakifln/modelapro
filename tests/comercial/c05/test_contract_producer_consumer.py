"""MP-QUAL/1 contract: one real producer, one real consumer, and the refusals.

Every expected value below was computed BY HAND from the licensed editions:

  ABNT NBR 14653-2:2011
    Tabela 1 item 2  n >= 6(k+1) III | 4(k+1) II | 3(k+1) I
    Tabela 1 item 4  Grau III = extrapolacao NAO admitida
    Tabela 1 item 5  pior p <= 10% III | <= 20% II | <= 30% I
    Tabela 1 item 6  p <= 1% III | <= 2% II | <= 5% I
    9.2.1.6 b)       Grau I = 1 ponto, Grau II = 2, Grau III = 3
    Tabela 2         16/10/6 pontos; itens 2,4,5,6 no grau pretendido e 1,3 um grau abaixo
    Tabela 5         amplitude do IC de 80% <= 30% III | <= 40% II | <= 50% I
    Anexo A.2 a)     n >= 3(k+1); n <= 30 => n_i >= 3
    Anexo A.3.1      alfa maximo dos testes auxiliares = 10%

The producer case is built so that, by hand:
    k = 3 -> item 2 exige n >= 6*(3+1) = 24; n = 30 >= 24  -> Grau III (3 pontos)
    nenhum eixo fora do intervalo amostral                 -> Grau III (3 pontos)
    pior p dos regressores = 0,08 <= 0,10                  -> Grau III (3 pontos)
    p do teste F = 0,001 <= 0,01                           -> Grau III (3 pontos)
    itens documentais 1 e 3 declarados no Grau III com proveniencia -> 3 + 3
    soma = 3+3+3+3+3+3 = 18 >= 16, itens 2,4,5,6 no Grau III, itens 1,3 >= Grau II
                                                           -> Tabela 2: Grau III
    amplitude do IC de 80% = 22,0% <= 30%                  -> Tabela 5: Grau III
"""

from __future__ import annotations

import builtins
import copy
import inspect
import re

import pytest

from modules.nbr14653_validation import assess_normative
from modules.qualification_profile import (
    CASE_ANALYSIS_ONLY,
    CASE_FLOW,
    CASE_READY_FOR_SIGNOFF,
    CASE_REVIEW_REQUIRED,
    CASE_SIGNED_INTEGRITY_VERIFIED,
    NON_SATISFYING_STATUSES,
    RULE_STATUSES,
    SCHEMA_VERSION,
    ProfileError,
    assess_qualification,
    known_profile_ids,
    make_rule_result,
    resolve_profile,
    satisfies,
    source_set_sha256,
)
from modules.qualification_profile import catalog as catalog_mod
from modules.qualification_profile import schema as schema_mod

PROFILE_ID = "abnt-14653-2-regressao-mercado"
PROFILE_VERSION = "1.0.0"
PROFILE_REF = {"id": PROFILE_ID, "version": PROFILE_VERSION}

#: The minimum fields the campaign contract requires on every RuleResult.
RULE_RESULT_MINIMUM_FIELDS = (
    "rule_id",
    "source_id",
    "edition_or_version",
    "clause",
    "applicability",
    "status",
    "observed",
    "criterion_ref",
    "evidence_refs",
    "explanation",
)

#: The five Anexo A.2/A.8 assumptions the norm leaves to the engineer's
#: examination; each needs a recorded finding WITH justification.
PROFESSIONAL_PRESSUPOSTOS = (
    "anexoA.2.f.variaveis_relevantes",
    "anexoA.2.g.multicolinearidade",
    "anexoA.2.h.residuos_vs_independentes",
    "anexoA.2.i.pontos_influenciantes",
    "anexoA.8.agrupamentos",
)


# --------------------------------------------------------------------------- #
# PRODUCER: a realistic Grau III case through assess_normative ->
#           assess_qualification
# --------------------------------------------------------------------------- #
def _normative_context(**overrides):
    """A Grau III urban-property regression case, by hand (see module docstring)."""
    ctx = dict(
        n=30,
        k=3,
        intercept=True,
        axes=[
            # avaliando dentro de [min, max] em todos os eixos: sem extrapolacao
            {"name": "area_terreno", "kind": "quantitative",
             "avaliando_value": 120.0, "sample_min": 80.0, "sample_max": 200.0, "unit": "m2"},
            {"name": "frente", "kind": "quantitative",
             "avaliando_value": 10.0, "sample_min": 8.0, "sample_max": 15.0, "unit": "m"},
            {"name": "esquina", "kind": "dichotomous",
             "avaliando_value": 0, "sample_values": [0, 1]},
        ],
        subject_raw={"area_terreno": 120.0, "frente": 10.0, "esquina": 0},
        predict_original=lambda raw: 600000.0,
        # pior p = 0,08 <= 0,10 -> item 5 Grau III
        pvalues={"area_terreno": 0.010, "frente": 0.080, "esquina": 0.050},
        f_pvalue=0.001,          # <= 0,01 -> item 6 Grau III
        amplitude_pct=22.0,      # <= 30 -> precisao Grau III
        grau_item1=3,
        item1_provenance={"source": "vistoria", "doc": "vistoria-2026-09-01.pdf"},
        grau_item3=3,
        item3_provenance={"source": "planilha", "doc": "amostra-30-dados.csv"},
        category_counts={"esquina": 12},   # n=30 -> n_i >= 3; 12 >= 3
        central_estimate=600000.0,
        mean_ci80={"lower": 540000.0, "upper": 660000.0},
        prediction_interval={"lower": 480000.0, "upper": 720000.0},
        estimand="valor_de_mercado",
        adopted_estimator="media",
        diagnostics={
            # p > alfa => nao se rejeita H0 => pressuposto satisfeito.
            # alfa = 0,10 e exatamente o teto do Anexo A.3.1.
            "anexoA.2.c.homocedasticidade": {"p_value": 0.42, "alpha": 0.10},
            "anexoA.2.d.normalidade": {"p_value": 0.55, "alpha": 0.10},
            "anexoA.2.e.autocorrelacao": {
                "p_value": 0.31, "alpha": 0.10, "ordering_declared": True,
            },
        },
        professional_findings={
            pid: {"satisfied": True,
                  "justification": "exame registrado e justificado no laudo"}
            for pid in PROFESSIONAL_PRESSUPOSTOS
        },
    )
    ctx.update(overrides)
    return ctx


def _qualification_context(assessment, **overrides):
    ctx = {
        "normative_assessment": assessment,
        "requested_minimum_grade": 3,
        "targets_grau_iii": True,
        "software_version": "1.4.2",
        "profile_evidence": {
            "9.2.1.1.a": "laudo-completo.pdf#capa",
            "9.2.1.1.b": "laudo-completo.pdf#analise-do-modelo",
            "9.2.1.1.c": "laudo-completo.pdf#anexo-enderecos",
            "9.2.1.1.d": "laudo-completo.pdf#tendencia-central",
            "parte1.6.3.vistoria": "vistoria-2026-09-01.pdf",
            "8.2.1.5.2.campo_suficiente": "laudo-completo.pdf#campo-de-arbitrio",
            "10.1.laudo_completo": "laudo-completo.pdf#indice-10-1",
        },
    }
    ctx.update(overrides)
    return ctx


@pytest.fixture(scope="module")
def grau_iii_assessment():
    return assess_normative(_normative_context())


@pytest.fixture(scope="module")
def grau_iii_block(grau_iii_assessment):
    return assess_qualification(
        _qualification_context(grau_iii_assessment), PROFILE_REF
    )


def test_producer_case_is_grau_iii_by_hand(grau_iii_assessment):
    """Tabela 1 + Tabela 2 + Tabela 5 computed by hand on the producer case."""
    fund = grau_iii_assessment["fundamentacao"]
    by_item = {it["item"]: it["grade"] for it in fund["items"]}
    assert by_item == {1: 3, 2: 3, 3: 3, 4: 3, 5: 3, 6: 3}
    assert fund["points"] == 18           # 9.2.1.6 b): 6 itens x 3 pontos
    assert fund["grade"] == 3             # 18 >= 16 (Tabela 2) com obrigatorios no III
    assert grau_iii_assessment["precisao"]["grade"] == 3   # 22,0% <= 30% (Tabela 5)
    assert grau_iii_assessment["micronumerosidade"]["status"] == "ok"


def test_emitted_block_is_exactly_the_mp_qual_1_shape(grau_iii_block):
    """schema_version, profile identity, fingerprint and the decision fields."""
    block = grau_iii_block
    assert block["schema_version"] == "MP-QUAL/1"
    assert block["schema_version"] == SCHEMA_VERSION

    for key in (
        "schema_version",
        "profile",
        "result_fingerprint",
        "calculation_status",
        "rule_results",
        "grade_requirement_status",
        "case_release_status",
        "review_events",
        "institution_acceptance",
    ):
        assert key in block, f"MP-QUAL/1 exige o campo {key!r}"

    profile = block["profile"]
    assert profile["id"] == PROFILE_ID
    assert profile["version"] == PROFILE_VERSION
    assert profile["resolved"] is True
    assert profile["state"] == "verified"
    # The resolved digest is the one recomputed from the identified source set.
    assert profile["source_set_sha256"] == source_set_sha256(profile["sources"])
    assert re.fullmatch(r"[0-9a-f]{64}", profile["source_set_sha256"])

    assert re.fullmatch(r"[0-9a-f]{64}", block["result_fingerprint"])
    assert block["calculation_status"] == "ok"
    assert block["grade_requirement_status"] == "met"   # grau 3 alcancado, 3 pedido
    assert block["achieved_fundamentacao_grade"] == 3
    assert block["case_release_status"] in CASE_FLOW
    assert isinstance(block["rule_results"], list) and block["rule_results"]
    assert block["review_events"] == []
    # Institutional acceptance is a RECORD, never inferred from a computation.
    assert block["institution_acceptance"]["recorded"] is False
    assert block["institution_acceptance"]["record"] is None


def test_every_rule_result_carries_the_minimum_fields_and_a_known_status(grau_iii_block):
    results = grau_iii_block["rule_results"]
    assert len(results) >= 6, "os seis itens da Tabela 1 precisam aparecer"
    for res in results:
        for field in RULE_RESULT_MINIMUM_FIELDS:
            assert field in res, f"RuleResult {res.get('rule_id')!r} sem campo {field!r}"
        assert res["status"] in RULE_STATUSES
        assert isinstance(res["evidence_refs"], list)
        assert isinstance(res["rule_id"], str) and res["rule_id"]
        assert isinstance(res["source_id"], str) and res["source_id"]
        assert isinstance(res["edition_or_version"], str) and res["edition_or_version"]
        assert isinstance(res["clause"], str) and res["clause"]
        assert res["applicability"] in (
            schema_mod.APPLICABLE,
            schema_mod.NOT_APPLICABLE_BY_PROFILE,
            schema_mod.NOT_APPLICABLE_BY_SOURCE,
        )


def test_tabela1_rule_results_are_anchored_to_the_2011_edition(grau_iii_block):
    by_id = {r["rule_id"]: r for r in grau_iii_block["rule_results"]}
    for item in range(1, 7):
        res = by_id[f"tabela1.item{item}"]
        assert res["source_id"] == "abnt-nbr-14653-2-2011"
        assert res["edition_or_version"] == "ABNT NBR 14653-2:2011"
        assert res["clause"] == f"Tabela 1 item {item}"
        assert res["status"] == "passed"
        assert res["observed"] == 3


def test_decisive_rules_of_the_profile_are_all_emitted(grau_iii_block):
    """Ausencia nao e aprovacao: uma regra decisiva ausente bloquearia o caso."""
    resolved = resolve_profile(PROFILE_REF)
    emitted = {r["rule_id"] for r in grau_iii_block["rule_results"]}
    for rule_id in resolved["decisive_rules"]:
        assert rule_id in emitted, f"regra decisiva {rule_id!r} nao foi avaliada"


def test_two_pass_protocol_review_then_signature(grau_iii_assessment):
    """Pass 1 yields the fingerprint; the review/signature are recorded against
    THAT fingerprint; pass 2/3 then release."""
    base = _qualification_context(grau_iii_assessment)
    first = assess_qualification(base, PROFILE_REF)
    fingerprint = first["result_fingerprint"]
    # Nothing reviewed yet -> review_required, never ready.
    assert first["release_blockers"] == []
    assert first["case_release_status"] == CASE_REVIEW_REQUIRED

    with_review = _qualification_context(
        grau_iii_assessment,
        review_events=[{
            "professional_id": "CREA-SP-123456",
            "motive": "revisao tecnica do modelo e do enquadramento",
            "version": "1.4.2",
            "fingerprint": fingerprint,
        }],
    )
    second = assess_qualification(with_review, PROFILE_REF)
    assert second["result_fingerprint"] == fingerprint, (
        "registrar uma revisao nao pode alterar o fingerprint do resultado"
    )
    assert second["case_release_status"] == CASE_READY_FOR_SIGNOFF

    signed = dict(with_review)
    signed["signature"] = {"integrity_verified": True, "fingerprint": fingerprint}
    third = assess_qualification(signed, PROFILE_REF)
    assert third["case_release_status"] == CASE_SIGNED_INTEGRITY_VERIFIED

    # A signature taken over a different fingerprint is stale, not a release.
    stale = dict(with_review)
    stale["signature"] = {"integrity_verified": True, "fingerprint": "0" * 64}
    assert assess_qualification(stale, PROFILE_REF)["case_release_status"] == (
        CASE_REVIEW_REQUIRED
    )


def test_absence_of_the_f_test_is_not_approval(grau_iii_assessment):
    """Sem p do teste F, o item 6 fica sem grau e o caso nao e liberado."""
    assessment = assess_normative(_normative_context(f_pvalue=None))
    by_item = {it["item"]: it for it in assessment["fundamentacao"]["items"]}
    assert by_item[6]["grade"] is None
    assert by_item[6]["evidence_status"] == "pending"
    # A pending item must NOT fall back to any alternative classification.
    assert assessment["fundamentacao"]["grade"] is None

    block = assess_qualification(_qualification_context(assessment), PROFILE_REF)
    by_id = {r["rule_id"]: r for r in block["rule_results"]}
    assert by_id["tabela1.item6"]["status"] == "unverified"
    assert satisfies(by_id["tabela1.item6"]) is False
    assert block["grade_requirement_status"] == "pending"
    assert block["case_release_status"] == CASE_ANALYSIS_ONLY
    codes = {b["code"] for b in block["release_blockers"]}
    assert "grade_pending" in codes
    assert "decisive_rule_not_satisfied" in codes
    assert block["achieved_fundamentacao_grade"] is None


# --------------------------------------------------------------------------- #
# CONSUMER: C03 presents the qualified result and never recalculates a grade
# --------------------------------------------------------------------------- #
def present_qualified_result(block):
    """A C03-style consumer. It reads ONLY the MP-QUAL/1 block.

    It must never import a normative classifier, never recompute a grade and
    never derive release from anything but ``case_release_status``.
    """
    releasable = block["case_release_status"] in (
        "ready_for_professional_signoff",
        "signed_integrity_verified",
    )
    return {
        "profile_label": "{0} v{1}".format(
            block["profile"]["id"], block["profile"]["version"]
        ),
        "source_set_sha256": block["profile"]["source_set_sha256"],
        "grade": block.get("achieved_fundamentacao_grade"),
        "grade_requirement_status": block["grade_requirement_status"],
        "release_status": block["case_release_status"],
        "releasable": releasable,
        "blocking_reasons": [
            {"code": b["code"], "rule_id": b.get("rule_id"), "detail": b.get("detail")}
            for b in block.get("release_blockers") or []
        ],
        "pending_manual_rules": list(block.get("pending_manual_rules") or []),
        "unsatisfied_rules": [
            r["rule_id"] for r in block["rule_results"] if not satisfies(r)
        ],
        "institution_acceptance_recorded": (
            block["institution_acceptance"]["recorded"]
        ),
    }


def test_consumer_renders_grade_and_release_from_the_block_alone(grau_iii_assessment):
    fingerprint = assess_qualification(
        _qualification_context(grau_iii_assessment), PROFILE_REF
    )["result_fingerprint"]
    block = assess_qualification(
        _qualification_context(
            grau_iii_assessment,
            review_events=[{
                "professional_id": "CREA-SP-123456",
                "motive": "revisao tecnica",
                "version": "1.4.2",
                "fingerprint": fingerprint,
            }],
        ),
        PROFILE_REF,
    )
    view = present_qualified_result(block)
    assert view["grade"] == 3
    assert view["grade_requirement_status"] == "met"
    assert view["release_status"] == CASE_READY_FOR_SIGNOFF
    assert view["releasable"] is True
    assert view["blocking_reasons"] == []
    assert view["unsatisfied_rules"] == []
    assert view["institution_acceptance_recorded"] is False
    assert view["profile_label"] == "{0} v{1}".format(PROFILE_ID, PROFILE_VERSION)


def test_consumer_renders_blocking_reasons_without_deciding_them(grau_iii_assessment):
    assessment = assess_normative(_normative_context(f_pvalue=None))
    block = assess_qualification(_qualification_context(assessment), PROFILE_REF)
    view = present_qualified_result(block)
    assert view["grade"] is None
    assert view["release_status"] == CASE_ANALYSIS_ONLY
    assert view["releasable"] is False
    codes = {r["code"] for r in view["blocking_reasons"]}
    assert "grade_pending" in codes
    assert "tabela1.item6" in view["unsatisfied_rules"]
    # Every blocking reason the consumer shows came from the block, with a text.
    for reason in view["blocking_reasons"]:
        assert reason["detail"]


def test_consumer_never_imports_normative_rules_to_decide_release(grau_iii_block):
    source = inspect.getsource(present_qualified_result)
    assert "normative_rules" not in source
    assert "assess_normative" not in source
    assert "classify_" not in source

    forbidden = ("modules.normative_rules", "modules.nbr14653_validation")
    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name in forbidden:
            raise AssertionError(
                f"o consumidor nao pode importar {name!r} para decidir liberacao"
            )
        return real_import(name, *args, **kwargs)

    builtins.__import__ = guarded
    try:
        view = present_qualified_result(grau_iii_block)
    finally:
        builtins.__import__ = real_import
    assert view["grade"] == 3
    assert view["release_status"] in CASE_FLOW


def test_consumer_sees_a_json_serialisable_block(grau_iii_block):
    import json

    payload = json.dumps(grau_iii_block, ensure_ascii=False, default=str)
    assert '"MP-QUAL/1"' in payload


# --------------------------------------------------------------------------- #
# REFUSAL SEMANTICS of the contract
# --------------------------------------------------------------------------- #
def _kwargs(**over):
    base = dict(
        rule_id="tabela1.item6",
        source_id="abnt-nbr-14653-2-2011",
        edition_or_version="ABNT NBR 14653-2:2011",
        clause="Tabela 1 item 6",
        status="passed",
    )
    base.update(over)
    return base


def test_make_rule_result_refuses_an_unknown_status():
    with pytest.raises(ValueError):
        make_rule_result(**_kwargs(status="ok"))
    with pytest.raises(ValueError):
        make_rule_result(**_kwargs(status="PASSED"))
    with pytest.raises(ValueError):
        make_rule_result(**_kwargs(status=None))


def test_make_rule_result_refuses_not_applicable_without_a_reason():
    with pytest.raises(ValueError):
        make_rule_result(**_kwargs(
            status="not_applicable",
            applicability=schema_mod.NOT_APPLICABLE_BY_PROFILE,
        ))
    with pytest.raises(ValueError):
        make_rule_result(**_kwargs(
            status="not_applicable",
            applicability=schema_mod.NOT_APPLICABLE_BY_SOURCE,
            not_applicable_reason="",
        ))


def test_make_rule_result_refuses_not_applicable_untied_to_profile_or_source():
    with pytest.raises(ValueError):
        make_rule_result(**_kwargs(
            status="not_applicable",
            applicability=schema_mod.APPLICABLE,
            not_applicable_reason="o avaliador entendeu que nao se aplica",
        ))
    with pytest.raises(ValueError):
        make_rule_result(**_kwargs(
            status="not_applicable",
            applicability="not_applicable_because_inconvenient",
            not_applicable_reason="fora do escopo",
        ))
    # Both legitimate applicabilities, with a reason, are accepted.
    for applicability in (
        schema_mod.NOT_APPLICABLE_BY_PROFILE,
        schema_mod.NOT_APPLICABLE_BY_SOURCE,
    ):
        res = make_rule_result(**_kwargs(
            status="not_applicable",
            applicability=applicability,
            not_applicable_reason="condicao do perfil ausente neste caso",
        ))
        assert res["applicability"] == applicability
        assert satisfies(res) is True


def test_satisfies_is_true_only_for_passed_and_a_justified_not_applicable():
    assert satisfies(make_rule_result(**_kwargs(status="passed"))) is True
    assert satisfies(make_rule_result(**_kwargs(
        status="not_applicable",
        applicability=schema_mod.NOT_APPLICABLE_BY_PROFILE,
        not_applicable_reason="perfil nao exige este requisito neste caso",
    ))) is True
    # A not_applicable stripped of its reason is not a pass either.
    assert satisfies({"status": "not_applicable"}) is False
    assert satisfies({"status": "not_applicable", "not_applicable_reason": ""}) is False


def test_satisfies_is_false_for_every_non_satisfying_status():
    assert set(NON_SATISFYING_STATUSES) == (
        set(RULE_STATUSES) - {"passed", "not_applicable"}
    )
    for status in NON_SATISFYING_STATUSES:
        res = make_rule_result(**_kwargs(status=status))
        assert satisfies(res) is False, f"{status!r} nao pode satisfazer um requisito"
    # Explicitly: unverified is NOT passed.
    assert "unverified" in NON_SATISFYING_STATUSES
    assert satisfies(make_rule_result(**_kwargs(status="unverified"))) is False
    assert satisfies(make_rule_result(**_kwargs(status="pending_manual"))) is False


# --------------------------------------------------------------------------- #
# grade_requirement_status: the preserved MP/1 vocabulary
# --------------------------------------------------------------------------- #
def test_grade_requirement_status_not_requested(grau_iii_assessment):
    """O perfil normativo declara minimum_fundamentacao_grade = null."""
    assert resolve_profile(PROFILE_REF)["minimum_fundamentacao_grade"] is None
    ctx = _qualification_context(grau_iii_assessment)
    ctx.pop("requested_minimum_grade")
    block = assess_qualification(ctx, PROFILE_REF)
    assert block["grade_requirement_status"] == "not_requested"
    assert block["requested_minimum_grade"] is None
    # Nada pedido nao apaga o grau alcancado, so nao ha requisito a comparar.
    assert block["achieved_fundamentacao_grade"] == 3


def test_grade_requirement_status_met_for_each_request_the_case_satisfies(
    grau_iii_assessment,
):
    for requested in (1, 2, 3):
        block = assess_qualification(
            _qualification_context(
                grau_iii_assessment, requested_minimum_grade=requested
            ),
            PROFILE_REF,
        )
        assert block["grade_requirement_status"] == "met", requested


def test_grade_requirement_status_not_met():
    """f_pvalue = 0,02 -> item 6 Grau II (2 pontos).

    Por Tabela 2: soma = 3+3+3+3+3+2 = 17 >= 16, mas o item 6 obrigatorio nao
    esta no Grau III -> desce para Grau II (17 >= 10, obrigatorios >= 2,
    complementares >= 1). Grau II < Grau III pedido -> not_met.
    """
    assessment = assess_normative(_normative_context(f_pvalue=0.02))
    by_item = {it["item"]: it["grade"] for it in assessment["fundamentacao"]["items"]}
    assert by_item[6] == 2
    assert assessment["fundamentacao"]["points"] == 17
    assert assessment["fundamentacao"]["grade"] == 2

    block = assess_qualification(_qualification_context(assessment), PROFILE_REF)
    assert block["grade_requirement_status"] == "not_met"
    assert block["case_release_status"] == CASE_ANALYSIS_ONLY
    assert "grade_not_met" in {b["code"] for b in block["release_blockers"]}
    # Grau II ainda e met se so o Grau II for pedido.
    assert assess_qualification(
        _qualification_context(assessment, requested_minimum_grade=2), PROFILE_REF
    )["grade_requirement_status"] == "met"


def test_grade_requirement_status_pending_when_the_grade_is_none(grau_iii_assessment):
    assessment = assess_normative(_normative_context(f_pvalue=None))
    assert assessment["fundamentacao"]["grade"] is None
    block = assess_qualification(_qualification_context(assessment), PROFILE_REF)
    assert block["grade_requirement_status"] == "pending"


@pytest.mark.parametrize("nonsense", [0, 4, 7, -1, "III", "", [3], {"grau": 3}])
def test_grade_requirement_status_error_on_a_nonsense_request(
    grau_iii_assessment, nonsense
):
    block = assess_qualification(
        _qualification_context(grau_iii_assessment, requested_minimum_grade=nonsense),
        PROFILE_REF,
    )
    assert block["grade_requirement_status"] == "error", nonsense


def test_grade_requirement_status_error_on_a_fractional_grade_request(
    grau_iii_assessment,
):
    """9.2.1.6 b) knows exactly three graus: I, II and III.

    "Grau 3,5" and "Grau 2,9" are not requests the norm can answer. Truncating
    them to an adjacent integer answers a question that was never asked, and
    in the 3,5 case answers it with ``met``.
    """
    for nonsense in (3.5, 2.9, 1.5):
        block = assess_qualification(
            _qualification_context(
                grau_iii_assessment, requested_minimum_grade=nonsense
            ),
            PROFILE_REF,
        )
        assert block["grade_requirement_status"] == "error", nonsense


def test_grade_requirement_status_error_on_a_failed_calculation(grau_iii_assessment):
    block = assess_qualification(
        _qualification_context(grau_iii_assessment, calculation_failed=True),
        PROFILE_REF,
    )
    assert block["calculation_status"] == "failed"
    assert block["grade_requirement_status"] == "error"
    assert block["case_release_status"] == CASE_ANALYSIS_ONLY
    codes = {b["code"] for b in block["release_blockers"]}
    assert "calculation_failed" in codes
    assert "grade_error" in codes


def test_grade_requirement_status_error_when_the_calculation_is_absent():
    block = assess_qualification({"requested_minimum_grade": 3}, PROFILE_REF)
    assert block["calculation_status"] == "absent"
    assert block["grade_requirement_status"] == "error"
    assert block["case_release_status"] == CASE_ANALYSIS_ONLY


# --------------------------------------------------------------------------- #
# Profiles: an unknown id is an error, and a changed source set never passes
# --------------------------------------------------------------------------- #
def test_unknown_profile_id_yields_a_structured_error_and_never_raises(
    grau_iii_assessment,
):
    unknown = {"id": "perfil-inventado-que-nao-existe", "version": "9.9.9"}
    assert unknown["id"] not in known_profile_ids()

    resolved = resolve_profile(unknown)           # must not raise
    assert resolved["resolved"] is False
    assert resolved["state"] == "unknown"
    assert unknown["id"] in resolved["detail"]

    block = assess_qualification(_qualification_context(grau_iii_assessment), unknown)
    assert block["schema_version"] == SCHEMA_VERSION
    assert block["profile"]["resolved"] is False
    assert block["case_release_status"] == CASE_ANALYSIS_ONLY
    assert "profile_unknown" in {b["code"] for b in block["release_blockers"]}
    # A consumer can still present it: analysis only, with the reason.
    view = present_qualified_result(block)
    assert view["releasable"] is False
    assert "profile_unknown" in {r["code"] for r in view["blocking_reasons"]}


def test_a_malformed_profile_reference_yields_a_structured_error_block(
    grau_iii_assessment,
):
    """Sem id nao ha perfil; o bloco sai em erro estruturado, sem excecao."""
    block = assess_qualification(_qualification_context(grau_iii_assessment), {})
    assert block["schema_version"] == SCHEMA_VERSION
    assert block["error"]["code"] == "profile_error"
    assert block["grade_requirement_status"] == "error"
    assert block["case_release_status"] == CASE_ANALYSIS_ONLY
    assert block["rule_results"] == []
    assert block["result_fingerprint"] is None


def test_a_requested_profile_version_the_catalog_does_not_have_is_not_resolved():
    resolved = resolve_profile({"id": PROFILE_ID, "version": "0.0.1"})
    assert resolved["resolved"] is False
    assert resolved["state"] == "unknown"
    assert resolved["catalog_version"] == PROFILE_VERSION


def test_source_set_digest_changes_when_a_source_edition_changes():
    sources = [
        {"id": "abnt-nbr-14653-2-2011", "edition_or_version": "2011 (1a edicao)",
         "sha256": "a" * 64},
        {"id": "abnt-nbr-14653-1-2019", "edition_or_version": "2019 (2a edicao)",
         "sha256": "b" * 64},
    ]
    baseline = source_set_sha256(sources)
    # Order must not matter: the digest is over a sorted tuple set.
    assert source_set_sha256(list(reversed(sources))) == baseline
    # Changing the edition, or the document itself, changes the digest.
    other_edition = copy.deepcopy(sources)
    other_edition[0]["edition_or_version"] = "2011 (1a edicao) + Errata 1"
    assert source_set_sha256(other_edition) != baseline
    other_doc = copy.deepcopy(sources)
    other_doc[1]["sha256"] = "c" * 64
    assert source_set_sha256(other_doc) != baseline


def test_declared_source_set_sha256_disagreeing_with_the_digest_raises(monkeypatch):
    """A changed source set must NOT pass silently.

    The mismatch is constructed with a temporary profile dict injected as the
    catalog content (no file is written); the digest verification inside
    resolve_profile is the real code under test.
    """
    real = resolve_profile(PROFILE_REF)
    assert real["source_set_sha256"] == source_set_sha256(real["sources"])

    tampered = copy.deepcopy(real)
    tampered.pop("resolved", None)
    # The sources changed (a different exemplar of Part 2) but the declared
    # digest was left at the old value.
    tampered["source_set_sha256"] = real["source_set_sha256"]
    tampered["sources"][0]["sha256"] = "0" * 64
    assert source_set_sha256(tampered["sources"]) != tampered["source_set_sha256"]

    monkeypatch.setattr(catalog_mod, "load_catalog", lambda: {PROFILE_ID: tampered})
    with pytest.raises(ProfileError) as exc:
        resolve_profile(PROFILE_REF)
    assert "source_set_sha256" in str(exc.value)


# --------------------------------------------------------------------------- #
# CASE_FLOW: four ordered states; submission and acceptance are not states
# --------------------------------------------------------------------------- #
def test_case_flow_is_the_ordered_four_state_pipeline():
    assert CASE_FLOW == (
        "analysis_only",
        "review_required",
        "ready_for_professional_signoff",
        "signed_integrity_verified",
    )
    assert len(CASE_FLOW) == 4
    assert CASE_FLOW.index(CASE_ANALYSIS_ONLY) == 0
    assert CASE_FLOW.index(CASE_REVIEW_REQUIRED) == 1
    assert CASE_FLOW.index(CASE_READY_FOR_SIGNOFF) == 2
    assert CASE_FLOW.index(CASE_SIGNED_INTEGRITY_VERIFIED) == 3


def test_submission_and_acceptance_are_not_members_of_case_flow():
    for non_state in (
        "submitted",
        "submitted_to_institution",
        "institution_accepted",
        "accepted",
        "accepted_by_institution",
        "homologado",
        "approved",
    ):
        assert non_state not in CASE_FLOW
    for state in CASE_FLOW:
        assert "submit" not in state
        assert "accept" not in state


def test_institution_acceptance_is_an_event_record_not_a_release_state(
    grau_iii_assessment,
):
    fingerprint = assess_qualification(
        _qualification_context(grau_iii_assessment), PROFILE_REF
    )["result_fingerprint"]
    review = [{
        "professional_id": "CREA-SP-123456",
        "motive": "revisao tecnica",
        "version": "1.4.2",
        "fingerprint": fingerprint,
    }]
    without = assess_qualification(
        _qualification_context(grau_iii_assessment, review_events=review), PROFILE_REF
    )
    acceptance = {
        "institution": "Banco Exemplo S.A.",
        "act": "verificacao_de_laudo",
        "act_version": "2026-01",
        "act_scope": "laudo unico protocolado em 2026-09-01",
    }
    with_acceptance = assess_qualification(
        _qualification_context(
            grau_iii_assessment,
            review_events=review,
            institution_acceptance=acceptance,
        ),
        PROFILE_REF,
    )
    assert with_acceptance["institution_acceptance"]["recorded"] is True
    assert with_acceptance["institution_acceptance"]["record"] == acceptance
    # Recording a real institutional act does not move the release pipeline.
    assert with_acceptance["case_release_status"] == without["case_release_status"]
    assert with_acceptance["case_release_status"] in CASE_FLOW
    assert with_acceptance["case_release_status"] not in ("accepted", "submitted")
