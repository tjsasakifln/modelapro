"""MP-COM/C05-A04 — pressupostos (Anexo A.2 c)–i), A.3.1, A.8) e dependência de dados
(Anexo A.2 a) micronumerosidade).

Every expected value here is derived by hand from the licensed editions:

ABNT NBR 14653-2:2011, Anexo A.2 a):
    n >= 3(k+1);  n <= 30 -> n_i >= 3;  30 < n <= 100 -> n_i >= 10% n;  n > 100 -> n_i >= 10.
    A count cannot be fractional, so the 10% branch is a minimum rounded UP.
ABNT NBR 14653-2:2011, Anexo A.2 c) d) e): erros homocedásticos, normais e não
    autocorrelacionados. A.2.1.4 EXIGE pré-ordenamento antes do exame de autocorrelação.
ABNT NBR 14653-2:2011, Anexo A.2 f) g) h) i) e A.8: exames e juízos do engenheiro de
    avaliações. A.2 g) VEDA o uso do modelo em caso de incoerência; A.2 i) condiciona a
    RETIRADA de pontos influenciantes à apresentação de justificativas.
ABNT NBR 14653-2:2011, Anexo A.3.1: o nível de significância máximo admitido nos demais
    testes estatísticos (os não citados na Tabela 1) não deve ser superior a 10%.

None of the above is a Tabela 1 item, so none of it awards points or moves the
fundamentação grade: it can only expose a violation or stay pending.
"""

import pytest

from modules import normative_rules as rules
from modules.nbr14653_validation import assess_normative


# ---------------------------------------------------------------------------
# Anexo A.2 a): minimum_ni — exact branch points and the rounding direction
# ---------------------------------------------------------------------------

def test_minimum_ni_branch_n_30_is_three():
    # n <= 30 -> n_i >= 3. 30 is inside the first branch.
    assert rules.minimum_ni(30) == 3


def test_minimum_ni_branch_n_31_is_four_ten_percent_rounded_up():
    # 30 < n <= 100 -> 10% n = 3.1; a fractional datum cannot satisfy a count,
    # so the minimum is 4, never 3.
    assert rules.minimum_ni(31) == 4


def test_minimum_ni_ten_percent_branch_rounds_up_at_n_50():
    # 10% of 50 = 5.0 exactly.
    assert rules.minimum_ni(50) == 5


def test_minimum_ni_ten_percent_branch_rounds_up_at_n_95():
    # 10% of 95 = 9.5 -> 10.
    assert rules.minimum_ni(95) == 10


def test_minimum_ni_branch_n_100_is_ten():
    # 10% of 100 = 10; still the middle branch, same value as the upper branch.
    assert rules.minimum_ni(100) == 10


def test_minimum_ni_branch_n_101_is_ten_flat():
    # n > 100 -> fixed 10 (NOT 10% = 10.1 -> 11).
    assert rules.minimum_ni(101) == 10
    assert rules.minimum_ni(400) == 10


def test_minimum_ni_is_none_for_unusable_count():
    # Absence is not approval: no n, no rule.
    assert rules.minimum_ni(None) is None
    assert rules.minimum_ni("muitos") is None
    assert rules.minimum_ni(-1) is None


# ---------------------------------------------------------------------------
# Anexo A.2 a): classify_micronumerosidade
# ---------------------------------------------------------------------------

def test_micronumerosidade_global_n_below_three_k_plus_one_is_violated():
    # k = 3 -> n >= 3(3+1) = 12. n = 11 is micronumeroso.
    out = rules.classify_micronumerosidade(11, 3, {"esquina": 5})
    assert out["n_minimum"] == 12
    assert out["status"] == rules.MICRO_VIOLATED
    assert any(v["kind"] == "global_n" for v in out["violations"])


def test_micronumerosidade_global_n_exactly_three_k_plus_one_is_not_violated():
    # n = 12 with k = 3 meets n >= 3(k+1) exactly; n_i = 4 >= 3 (n <= 30).
    out = rules.classify_micronumerosidade(12, 3, {"esquina": 4})
    assert out["n_minimum"] == 12
    assert out["ni_minimum"] == 3
    assert out["status"] == rules.MICRO_OK
    assert out["violations"] == []


def test_micronumerosidade_characteristic_below_ni_is_violated_and_named():
    # n = 40 -> 30 < n <= 100 -> n_i >= ceil(10% * 40) = 4.
    # "frente_para_praia" has 3 < 4 and must be named; "esquina" with 4 passes.
    out = rules.classify_micronumerosidade(
        40, 2, {"esquina": 4, "frente_para_praia": 3}
    )
    assert out["ni_minimum"] == 4
    assert out["status"] == rules.MICRO_VIOLATED
    named = [
        v["characteristic"]
        for v in out["violations"]
        if v["kind"] == "characteristic_ni"
    ]
    assert named == ["frente_para_praia"]
    assert "esquina" in out["checked_characteristics"]


def test_micronumerosidade_pending_when_counts_absent_even_with_global_n_ok():
    # n = 30, k = 2 -> n >= 9 satisfied. The per-characteristic leg of A.2 a)
    # was NOT informed, and absence of the counts is not conformity.
    out = rules.classify_micronumerosidade(30, 2, None)
    assert out["status"] == rules.MICRO_PENDING
    assert out["status"] != rules.MICRO_OK
    assert out["per_characteristic_evaluated"] is False
    assert out["checked_characteristics"] == []


def test_micronumerosidade_per_characteristic_evaluated_true_only_with_counts():
    ok = rules.classify_micronumerosidade(30, 2, {"esquina": 3})
    assert ok["per_characteristic_evaluated"] is True
    assert ok["status"] == rules.MICRO_OK


def test_micronumerosidade_pending_when_n_or_k_absent():
    for n, k in ((None, 2), (18, None)):
        out = rules.classify_micronumerosidade(n, k, {"esquina": 5})
        assert out["status"] == rules.MICRO_PENDING
        assert out["n_minimum"] is None
        # Contract gap (non-normative): this early-return branch omits the key
        # entirely. The invariant that matters is that it is never truthy —
        # nothing was evaluated, so nothing may read as evaluated.
        assert out.get("per_characteristic_evaluated") is not True


def test_micronumerosidade_invalid_count_is_violation_not_pass():
    out = rules.classify_micronumerosidade(18, 2, {"esquina": None})
    assert out["status"] == rules.MICRO_VIOLATED
    kinds = {v["kind"] for v in out["violations"]}
    assert "characteristic_count_invalid" in kinds


# ---------------------------------------------------------------------------
# Anexo A.3.1: the alpha ceiling
# ---------------------------------------------------------------------------

def test_max_auxiliary_alpha_is_the_ten_percent_ceiling_of_A_3_1():
    assert rules.max_auxiliary_alpha() == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# Anexo A.2 c)/d)/e): direction of the test — small p is BAD news
# ---------------------------------------------------------------------------

AUTOMATABLE = [
    "anexoA.2.c.homocedasticidade",
    "anexoA.2.d.normalidade",
]

NON_AUTOMATABLE = [
    "anexoA.2.f.variaveis_relevantes",
    "anexoA.2.g.multicolinearidade",
    "anexoA.2.h.residuos_vs_independentes",
    "anexoA.2.i.pontos_influenciantes",
    "anexoA.8.agrupamentos",
]


@pytest.mark.parametrize("pid", AUTOMATABLE)
def test_pressuposto_small_p_rejects_h0_and_violates_the_assumption(pid):
    # H0 is the assumption itself (variância constante / normalidade).
    # p <= alpha rejects H0, so the pressuposto is VIOLATED.
    out = rules.evaluate_pressuposto(pid, p_value=0.01, alpha=0.10)
    assert out["status"] == rules.PRESSUPOSTO_VIOLATED
    assert out["status"] != rules.PRESSUPOSTO_SATISFIED


@pytest.mark.parametrize("pid", AUTOMATABLE)
def test_pressuposto_large_p_does_not_reject_h0_and_satisfies_the_assumption(pid):
    out = rules.evaluate_pressuposto(pid, p_value=0.42, alpha=0.10)
    assert out["status"] == rules.PRESSUPOSTO_SATISFIED


def test_pressuposto_boundary_p_equal_alpha_is_violated():
    # p == alpha rejects H0 at that level: the boundary belongs to the violation.
    out = rules.evaluate_pressuposto(
        "anexoA.2.c.homocedasticidade", p_value=0.10, alpha=0.10
    )
    assert out["status"] == rules.PRESSUPOSTO_VIOLATED


def test_pressuposto_boundary_p_just_above_alpha_is_satisfied():
    out = rules.evaluate_pressuposto(
        "anexoA.2.c.homocedasticidade", p_value=0.100001, alpha=0.10
    )
    assert out["status"] == rules.PRESSUPOSTO_SATISFIED


def test_pressuposto_alpha_defaults_to_the_A_3_1_ceiling():
    # With no alpha given, the applied level must be exactly the 10% ceiling.
    out = rules.evaluate_pressuposto("anexoA.2.d.normalidade", p_value=0.09)
    assert out["alpha"] == pytest.approx(0.10)
    assert out["alpha_ceiling"] == pytest.approx(0.10)
    # 0.09 <= 0.10 -> H0 rejected -> violated.
    assert out["status"] == rules.PRESSUPOSTO_VIOLATED

    out2 = rules.evaluate_pressuposto("anexoA.2.d.normalidade", p_value=0.11)
    assert out2["alpha"] == pytest.approx(0.10)
    assert out2["status"] == rules.PRESSUPOSTO_SATISFIED


def test_pressuposto_honours_an_alpha_stricter_than_the_ceiling():
    """A supplied alpha below the ceiling must actually be applied.

    With alpha = 5%, p = 0.08 does NOT reject H0, so the assumption is
    SATISFIED — a hardcoded 10% level would wrongly call it violated.
    """
    out = rules.evaluate_pressuposto(
        "anexoA.2.c.homocedasticidade", p_value=0.08, alpha=0.05
    )
    assert out["alpha"] == pytest.approx(0.05)
    assert out["status"] == rules.PRESSUPOSTO_SATISFIED


def test_pressuposto_stricter_alpha_still_detects_a_violation():
    out = rules.evaluate_pressuposto(
        "anexoA.2.c.homocedasticidade", p_value=0.04, alpha=0.05
    )
    assert out["alpha"] == pytest.approx(0.05)
    assert out["status"] == rules.PRESSUPOSTO_VIOLATED


def test_pressuposto_alpha_exactly_at_ceiling_is_honoured():
    out = rules.evaluate_pressuposto(
        "anexoA.2.c.homocedasticidade", p_value=0.50, alpha=0.10
    )
    assert out["status"] == rules.PRESSUPOSTO_SATISFIED
    assert out["alpha"] == pytest.approx(0.10)


@pytest.mark.parametrize("loose_alpha", [0.100001, 0.11, 0.20, 0.05 + 0.06])
def test_pressuposto_alpha_above_ceiling_is_refused_not_honoured(loose_alpha):
    # A caller must not be able to loosen the A.3.1 ceiling to manufacture a pass.
    out = rules.evaluate_pressuposto(
        "anexoA.2.c.homocedasticidade", p_value=0.50, alpha=loose_alpha
    )
    assert out["status"] == rules.PRESSUPOSTO_PENDING
    assert out["status"] != rules.PRESSUPOSTO_SATISFIED
    assert out["alpha_ceiling"] == pytest.approx(0.10)


@pytest.mark.parametrize("pid", AUTOMATABLE)
def test_pressuposto_missing_p_value_is_pending_never_satisfied(pid):
    out = rules.evaluate_pressuposto(pid, p_value=None)
    assert out["status"] == rules.PRESSUPOSTO_PENDING
    assert out["status"] not in (
        rules.PRESSUPOSTO_SATISFIED,
        rules.PRESSUPOSTO_VIOLATED,
    )


def test_pressuposto_non_finite_p_value_is_pending():
    out = rules.evaluate_pressuposto(
        "anexoA.2.d.normalidade", p_value=float("nan")
    )
    assert out["status"] == rules.PRESSUPOSTO_PENDING


# --- Anexo A.2 e) / A.2.1.4: pré-ordenamento is a precondition ---------------

def test_autocorrelacao_is_pending_without_declared_ordering():
    # A.2.1.4 exige pré-ordenamento dos elementos amostrais ANTES do exame.
    # A favourable p on the original file order does not satisfy the clause.
    out = rules.evaluate_pressuposto(
        "anexoA.2.e.autocorrelacao", p_value=0.90, ordering_declared=False
    )
    assert out["status"] == rules.PRESSUPOSTO_PENDING
    assert out["status"] != rules.PRESSUPOSTO_SATISFIED


def test_autocorrelacao_is_pending_when_ordering_not_informed_at_all():
    out = rules.evaluate_pressuposto("anexoA.2.e.autocorrelacao", p_value=0.90)
    assert out["status"] == rules.PRESSUPOSTO_PENDING


def test_autocorrelacao_with_declared_ordering_follows_the_p_value_direction():
    satisfied = rules.evaluate_pressuposto(
        "anexoA.2.e.autocorrelacao", p_value=0.90, ordering_declared=True
    )
    assert satisfied["status"] == rules.PRESSUPOSTO_SATISFIED
    violated = rules.evaluate_pressuposto(
        "anexoA.2.e.autocorrelacao", p_value=0.02, ordering_declared=True
    )
    assert violated["status"] == rules.PRESSUPOSTO_VIOLATED


def test_autocorrelacao_ordering_declared_does_not_replace_the_p_value():
    out = rules.evaluate_pressuposto(
        "anexoA.2.e.autocorrelacao", p_value=None, ordering_declared=True
    )
    assert out["status"] == rules.PRESSUPOSTO_PENDING


# --- Anexo A.2 f) g) h) i) e A.8: professional judgement ---------------------

@pytest.mark.parametrize("pid", NON_AUTOMATABLE)
def test_non_automatable_pressuposto_requires_professional_decision(pid):
    out = rules.evaluate_pressuposto(pid)
    assert out["status"] == rules.PRESSUPOSTO_PROFESSIONAL
    assert out["status"] not in (
        rules.PRESSUPOSTO_SATISFIED,
        rules.PRESSUPOSTO_VIOLATED,
    )


@pytest.mark.parametrize("pid", NON_AUTOMATABLE)
def test_non_automatable_pressuposto_ignores_a_p_value(pid):
    # The mere presence of a p-value is not conformity for a clause the norm
    # settles by examination and record, not by a test statistic.
    out = rules.evaluate_pressuposto(pid, p_value=0.99, alpha=0.10)
    assert out["status"] == rules.PRESSUPOSTO_PROFESSIONAL


@pytest.mark.parametrize("pid", NON_AUTOMATABLE)
@pytest.mark.parametrize(
    "finding",
    [
        {"satisfied": True},
        {"satisfied": True, "justification": ""},
        {"satisfied": True, "justification": None},
    ],
)
def test_non_automatable_finding_without_justification_is_not_approval(pid, finding):
    out = rules.evaluate_pressuposto(pid, professional_finding=finding)
    assert out["status"] not in (
        rules.PRESSUPOSTO_SATISFIED,
        rules.PRESSUPOSTO_VIOLATED,
    )
    assert out["status"] in (
        rules.PRESSUPOSTO_PENDING,
        rules.PRESSUPOSTO_PROFESSIONAL,
    )


@pytest.mark.parametrize("pid", NON_AUTOMATABLE)
def test_non_automatable_bare_true_finding_is_not_approval(pid):
    out = rules.evaluate_pressuposto(pid, professional_finding=True)
    assert out["status"] not in (
        rules.PRESSUPOSTO_SATISFIED,
        rules.PRESSUPOSTO_VIOLATED,
    )


@pytest.mark.parametrize("pid", NON_AUTOMATABLE)
def test_non_automatable_finding_with_justification_is_conclusive(pid):
    ok = rules.evaluate_pressuposto(
        pid,
        professional_finding={
            "satisfied": True,
            "justification": "exame registrado no laudo, item 10.1",
        },
    )
    assert ok["status"] == rules.PRESSUPOSTO_SATISFIED

    bad = rules.evaluate_pressuposto(
        pid,
        professional_finding={
            "satisfied": False,
            "justification": "incoerência constatada e registrada",
        },
    )
    assert bad["status"] == rules.PRESSUPOSTO_VIOLATED


def test_evaluate_pressuposto_unknown_id_raises_key_error():
    with pytest.raises(KeyError):
        rules.evaluate_pressuposto("anexoA.2.z.inexistente", p_value=0.5)


# ---------------------------------------------------------------------------
# PRESSUPOSTOS catalogue shape and the two normative flags
# ---------------------------------------------------------------------------

def test_every_pressuposto_carries_clause_requirement_and_reaction():
    assert rules.PRESSUPOSTOS, "o catálogo de pressupostos não pode estar vazio"
    for spec in rules.PRESSUPOSTOS:
        assert spec.get("clause"), spec["id"]
        assert spec.get("requirement"), spec["id"]
        assert spec.get("reaction"), spec["id"]


def test_automatable_pressupostos_declare_hypothesis_and_direction():
    automatable = [s for s in rules.PRESSUPOSTOS if s.get("automatable")]
    # Anexo A.2 c), d) and e) are the three automatable assumptions.
    assert {s["id"] for s in automatable} == {
        "anexoA.2.c.homocedasticidade",
        "anexoA.2.d.normalidade",
        "anexoA.2.e.autocorrelacao",
    }
    for spec in automatable:
        assert spec.get("hypothesis_null"), spec["id"]
        assert spec.get("direction"), spec["id"]


def test_pressupostos_cover_clauses_A2_c_to_i_and_A8():
    ids = {s["id"] for s in rules.PRESSUPOSTOS}
    assert set(AUTOMATABLE + ["anexoA.2.e.autocorrelacao"] + NON_AUTOMATABLE) <= ids


def test_anexo_A2_g_carries_the_prohibition_flag():
    # A.2 g) is the only clause of this block that VEDA the use of the model.
    spec = rules.PRESSUPOSTOS_BY_ID["anexoA.2.g.multicolinearidade"]
    assert spec.get("blocks_use_when_incoherent") is True
    assert "A.2 g)" in spec["clause"] or "A.2 g" in spec["clause"]
    # A.2.1.5.2 asks for attention above 0,80 — a trigger for examination,
    # not the prohibition itself, and not a VIF cut (the norm defines none).
    assert spec.get("attention_threshold") == pytest.approx(0.80)


def test_anexo_A2_i_conditions_removal_on_justification():
    spec = rules.PRESSUPOSTOS_BY_ID["anexoA.2.i.pontos_influenciantes"]
    assert spec.get("removal_requires_justification") is True


def test_no_other_pressuposto_claims_to_block_the_model():
    blocking = [
        s["id"] for s in rules.PRESSUPOSTOS if s.get("blocks_use_when_incoherent")
    ]
    assert blocking == ["anexoA.2.g.multicolinearidade"]


# ---------------------------------------------------------------------------
# assess_normative: surfacing, and the independence from Tabela 1/2
# ---------------------------------------------------------------------------

def _grau_iii_context(**overrides):
    """A context that, by hand, scores Grau III on Tabela 2.

    k = 2 -> item 2 needs n >= 6(2+1) = 18, so n = 18 is Grau III (3 pontos).
    Item 4: avaliando inside the sample interval -> no extrapolation -> Grau III.
    Item 5: worst p = 0.05 <= 10% -> Grau III. Item 6: F p = 0.005 <= 1% -> Grau III.
    Items 1 and 3 declared Grau III with provenance -> 3 pontos each.
    Pontos = 18 >= 16, itens 2,4,5,6 no Grau III, itens 1,3 >= Grau II -> Grau III.
    """
    ctx = {
        "n": 18,
        "k": 2,
        "intercept": True,
        "axes": [
            {
                "name": "area",
                "kind": rules.KIND_QUANTITATIVE,
                "avaliando_value": 300.0,
                "sample_min": 200.0,
                "sample_max": 500.0,
            },
            {
                "name": "frente",
                "kind": rules.KIND_QUANTITATIVE,
                "avaliando_value": 12.0,
                "sample_min": 10.0,
                "sample_max": 20.0,
            },
        ],
        "pvalues": {"area": 0.05, "frente": 0.01},
        "f_pvalue": 0.005,
        "grau_item1": 3,
        "grau_item3": 3,
        "item1_provenance": {"source": "matrícula 12.345, vistoria 2026-09-01"},
        "item3_provenance": {"source": "pesquisa de mercado, fichas 1-18"},
        "amplitude_pct": 25.0,
    }
    ctx.update(overrides)
    return ctx


def test_assess_normative_surfaces_a_violated_pressuposto_as_error():
    ctx = _grau_iii_context(
        diagnostics={
            # p = 0.001 <= alpha 0.10 -> H0 (variância constante) rejeitada -> violação.
            "anexoA.2.c.homocedasticidade": {"p_value": 0.001},
        }
    )
    out = assess_normative(ctx)
    homo = next(
        p for p in out["pressupostos"] if p["id"] == "anexoA.2.c.homocedasticidade"
    )
    assert homo["status"] == rules.PRESSUPOSTO_VIOLATED
    errors = [
        i
        for i in out["issues"]
        if i["severity"] == "error"
        and "anexoA.2.c.homocedasticidade" in i["affected_ids"]
    ]
    assert errors, "pressuposto violado deve surgir como issue de severidade 'error'"
    assert errors[0]["code"] == "pressuposto_violado"


def test_assess_normative_surfaces_a_pending_pressuposto_as_non_error():
    ctx = _grau_iii_context(
        diagnostics={"anexoA.2.d.normalidade": {}}  # no p-value informed
    )
    out = assess_normative(ctx)
    norm = next(
        p for p in out["pressupostos"] if p["id"] == "anexoA.2.d.normalidade"
    )
    assert norm["status"] == rules.PRESSUPOSTO_PENDING
    related = [
        i
        for i in out["issues"]
        if "anexoA.2.d.normalidade" in i["affected_ids"]
    ]
    assert related, "pressuposto pendente deve ser reportado"
    assert all(i["severity"] != "error" for i in related)
    assert related[0]["code"] == "pressuposto_pendente"


def test_assess_normative_pending_pressuposto_never_reported_as_satisfied():
    out = assess_normative(_grau_iii_context())
    # Nothing was informed: no assumption may read as satisfied.
    assert out["pressupostos"]
    assert all(
        p["status"] != rules.PRESSUPOSTO_SATISFIED for p in out["pressupostos"]
    )


def test_assess_normative_micronumerosidade_violation_is_error_issue():
    # n = 18 -> n <= 30 -> n_i >= 3. "esquina" com 2 viola A.2 a).
    out = assess_normative(_grau_iii_context(category_counts={"esquina": 2}))
    assert out["micronumerosidade"]["status"] == rules.MICRO_VIOLATED
    errors = [
        i
        for i in out["issues"]
        if i["code"] == "micronumerosidade" and i["severity"] == "error"
    ]
    assert errors
    assert "esquina" in errors[0]["message"]


def test_assess_normative_micronumerosidade_pending_without_counts_is_non_error():
    out = assess_normative(_grau_iii_context())
    assert out["micronumerosidade"]["status"] == rules.MICRO_PENDING
    pend = [i for i in out["issues"] if i["code"] == "micronumerosidade_pending"]
    assert pend
    assert all(i["severity"] != "error" for i in pend)


def test_micronumerosidade_does_not_change_the_fundamentacao_grade():
    """A.2 a) is a pressuposto, not a Tabela 1 item: it awards no points.

    Two contexts differing ONLY in category_counts must land on the same
    fundamentação grade (Grau III by hand: 18 pontos, itens 2,4,5,6 no Grau III,
    itens 1 e 3 no Grau III) while their issues differ.
    """
    clean = assess_normative(_grau_iii_context(category_counts={"esquina": 6}))
    broken = assess_normative(_grau_iii_context(category_counts={"esquina": 1}))

    assert clean["micronumerosidade"]["status"] == rules.MICRO_OK
    assert broken["micronumerosidade"]["status"] == rules.MICRO_VIOLATED

    assert clean["fundamentacao"]["grade"] == 3
    assert broken["fundamentacao"]["grade"] == 3
    assert clean["fundamentacao"]["grade"] == broken["fundamentacao"]["grade"]
    assert clean["fundamentacao"]["points"] == broken["fundamentacao"]["points"] == 18

    clean_codes = [i["code"] for i in clean["issues"]]
    broken_codes = [i["code"] for i in broken["issues"]]
    assert clean_codes != broken_codes
    assert "micronumerosidade" in broken_codes
    assert "micronumerosidade" not in clean_codes


def test_micronumerosidade_ok_does_not_raise_the_fundamentacao_grade():
    """A.2 a) satisfied awards no points, so it cannot lift the enquadramento.

    By hand with k = 2 and n = 12: Tabela 1 item 2 needs 6(k+1) = 18 for Grau III
    and 4(k+1) = 12 for Grau II, so n = 12 is exactly Grau II (2 pontos).
    Items 1, 3, 4, 5 and 6 stay at Grau III (3 pontos each) -> pontos = 17.
    Tabela 2 blocks Grau III because the obrigatório item 2 is only Grau II, so
    the enquadramento is Grau II. Micronumerosidade at n = 12 (<= 30) with
    n_i = 3 >= 3 and n = 12 >= 3(k+1) = 9 is MICRO_OK — and must stay decorative.
    """
    ctx = _grau_iii_context(n=12, category_counts={"esquina": 3})
    out = assess_normative(ctx)
    assert out["micronumerosidade"]["status"] == rules.MICRO_OK
    assert out["fundamentacao"]["points"] == 17
    assert out["fundamentacao"]["grade"] == 2
    assert out["fundamentacao"]["grade"] != 3

    # The very same model with the per-characteristic leg unreported (pending)
    # lands on the identical grade: the pressuposto moves issues, never points.
    pending = assess_normative(_grau_iii_context(n=12))
    assert pending["micronumerosidade"]["status"] == rules.MICRO_PENDING
    assert pending["fundamentacao"]["grade"] == 2
    assert pending["fundamentacao"]["points"] == 17
