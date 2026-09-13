# -*- coding: utf-8 -*-
"""C05-A06 — base de valor correta e a rota do custo.

Every expected value here was computed BY HAND from the licensed editions:

ABNT NBR 14653-1:2019
  3.1.47    valor de mercado
  3.1.11.5  custo de reprodução (SEM depreciação)
  3.1.11.3  custo de reedição (custo de reprodução MENOS depreciação)
  3.1.11.6  custo de substituição
  3.1.51    valor em risco ("parcela do bem que se deseja segurar ... valor
            máximo segurável") — definido PELA APÓLICE, não pelo avaliador

ABNT NBR 14653-2:2011
  9.3 / Tabela 6  itens 1 (custo direto), 2 (BDI), 3 (depreciação física)
  Tabela 7        pontos mínimos 7 / 5 / 3; obrigatórios:
                    Grau III -> item 1 no Grau III e os demais >= Grau II
                    Grau II  -> itens 1 e 2 >= Grau II
                    Grau I   -> todos >= Grau I

The A06 guard: a regressão do método comparativo direto estima VALOR DE
MERCADO. Convertê-lo em custo (de reprodução/reedição/substituição) ou em
limite de garantia por um coeficiente é vedado — são grandezas distintas
com memórias de cálculo distintas.
"""

import pytest

from modules import normative_rules as rules
from modules.nbr14653_validation import assess_normative
from modules.qualification_profile import (
    CASE_ANALYSIS_ONLY,
    CASE_READY_FOR_SIGNOFF,
    CASE_SIGNED_INTEGRITY_VERIFIED,
    assess_qualification,
    known_profile_ids,
    resolve_profile,
)
from modules.qualification_profile.schema import (
    PROFILE_VERIFIED,
    RULE_PASSED,
)

REGRESSION = "metodo_comparativo_direto_regressao"
COST_METHOD = "metodo_quantificacao_de_custo"
POLICY = "definicao_contratual_apolice"

#: The five bases whose definition clause comes from Parte 1:2019, by hand.
EXPECTED_CLAUSES = {
    "valor_de_mercado": "3.1.47",
    "custo_de_reproducao": "3.1.11.5",
    "custo_de_reedicao": "3.1.11.3",
    "custo_de_substituicao": "3.1.11.6",
    "valor_em_risco": "3.1.51",
}

#: Bases that a market regression must NEVER be allowed to produce.
NON_MARKET_BASES = (
    "custo_de_reproducao",
    "custo_de_reedicao",
    "custo_de_substituicao",
    "valor_em_risco",
    "limite_maximo_de_garantia",
)


# --------------------------------------------------------------------------
# VALUE_BASES — the catalogue of bases and where each definition comes from
# --------------------------------------------------------------------------

class TestValueBasesCatalogue:

    def test_catalogue_declares_the_six_bases_of_a06(self):
        for basis in ("valor_de_mercado", "custo_de_reproducao", "custo_de_reedicao",
                      "custo_de_substituicao", "valor_em_risco",
                      "limite_maximo_de_garantia"):
            assert basis in rules.VALUE_BASES, f"base de valor ausente: {basis}"

    @pytest.mark.parametrize("basis,clause", sorted(EXPECTED_CLAUSES.items()))
    def test_definition_clause_points_at_the_right_parte1_2019_clause(self, basis, clause):
        entry = rules.VALUE_BASES[basis]
        declared = entry["definition_clause"]
        assert clause in declared, (
            f"{basis}: definition_clause={declared!r} não aponta para a cláusula "
            f"{clause} da ABNT NBR 14653-1:2019"
        )
        assert "14653-1:2019" in declared, (
            f"{basis}: a definição é da Parte 1 edição 2019, mas o código registra "
            f"{declared!r}"
        )

    def test_limite_maximo_de_garantia_is_not_an_abnt_type_of_value(self):
        """LMG é cláusula do contrato de seguro, não um tipo de valor da 14653-1."""
        entry = rules.VALUE_BASES["limite_maximo_de_garantia"]
        assert "14653-1" not in entry["definition_clause"], (
            "LMG não é definido pela ABNT NBR 14653-1; atribuir-lhe uma cláusula "
            "da norma disfarçaria uma condição contratual de base normativa."
        )
        assert any(
            word in entry["definition_clause"].lower()
            for word in ("contratual", "regulat")
        )

    def test_only_valor_de_mercado_is_derivable_from_market_regression(self):
        assert rules.VALUE_BASES["valor_de_mercado"]["derivable_from_market_regression"] is True
        for basis in NON_MARKET_BASES:
            assert rules.VALUE_BASES[basis]["derivable_from_market_regression"] is False, (
                f"{basis} marcado como derivável da regressão de mercado: isso "
                "autorizaria converter preço em custo/garantia por coeficiente."
            )

    def test_reproducao_excludes_depreciation_and_reedicao_includes_it(self):
        """3.1.11.5 vs 3.1.11.3: bases distintas, NÃO intercambiáveis."""
        reproducao = rules.VALUE_BASES["custo_de_reproducao"]["definition"].lower()
        reedicao = rules.VALUE_BASES["custo_de_reedicao"]["definition"].lower()

        # 3.1.11.5: "sem considerar eventual depreciação"
        assert "deprecia" in reproducao
        assert "sem" in reproducao, (
            "custo de reprodução (3.1.11.5) NÃO considera depreciação; a definição "
            "precisa dizê-lo, senão fica indistinguível do custo de reedição."
        )
        # 3.1.11.3: custo de reprodução DESCONTADA a depreciação
        assert "deprecia" in reedicao
        assert "reprodu" in reedicao, (
            "custo de reedição (3.1.11.3) é definido a partir do custo de reprodução."
        )
        assert any(word in reedicao for word in ("descontada", "menos", "descontado")), (
            "custo de reedição desconta a depreciação; sem isso as duas bases se "
            "confundem."
        )
        assert reproducao != reedicao

        # As memórias de cálculo exigidas diferem exatamente pela depreciação.
        assert "depreciacao_fisica" not in rules.VALUE_BASES["custo_de_reproducao"]["required_memory"]
        assert "depreciacao_fisica" in rules.VALUE_BASES["custo_de_reedicao"]["required_memory"]

    def test_substituicao_is_reedicao_of_an_asset_of_similar_utility(self):
        definition = rules.VALUE_BASES["custo_de_substituicao"]["definition"].lower()
        assert "reedi" in definition
        assert "utilidade" in definition

    def test_valor_em_risco_and_lmg_are_produced_by_the_policy_not_the_appraiser(self):
        for basis in ("valor_em_risco", "limite_maximo_de_garantia"):
            produced_by = rules.VALUE_BASES[basis]["produced_by"]
            assert produced_by == [POLICY], (
                f"{basis}: produced_by={produced_by!r}. 3.1.51 e o LMG são fixados "
                "pela apólice/contrato; o avaliador não os produz por regressão."
            )
            assert REGRESSION not in produced_by
            assert COST_METHOD not in produced_by

    def test_valor_em_risco_definition_follows_3_1_51(self):
        definition = rules.VALUE_BASES["valor_em_risco"]["definition"].lower()
        assert "segurar" in definition
        assert "segurável" in definition or "seguravel" in definition

    def test_cost_bases_are_produced_only_by_the_cost_quantification_method(self):
        for basis in ("custo_de_reproducao", "custo_de_reedicao", "custo_de_substituicao"):
            assert rules.VALUE_BASES[basis]["produced_by"] == [COST_METHOD]

    def test_valor_de_mercado_is_produced_only_by_the_regression_method(self):
        assert rules.VALUE_BASES["valor_de_mercado"]["produced_by"] == [REGRESSION]


# --------------------------------------------------------------------------
# value_basis_guard — the core A06 refusal
# --------------------------------------------------------------------------

class TestValueBasisGuard:

    @pytest.mark.parametrize("basis", NON_MARKET_BASES)
    def test_regression_cannot_produce_any_cost_or_insurance_basis(self, basis):
        out = rules.value_basis_guard(basis, REGRESSION)
        assert out["status"] == "refused", (
            f"{basis} aceito sob {REGRESSION}: a regressão de mercado estima valor "
            "de mercado (3.1.47) e converter esse preço em custo ou em limite de "
            "garantia por coeficiente é vedado."
        )
        assert out["basis"] == basis
        assert out["method"] == REGRESSION

    def test_accepts_custo_de_reedicao_under_the_cost_quantification_method(self):
        out = rules.value_basis_guard("custo_de_reedicao", COST_METHOD)
        assert out["status"] == "ok"
        assert "3.1.11.3" in out["definition_clause"]

    def test_accepts_valor_de_mercado_under_the_regression_method(self):
        out = rules.value_basis_guard("valor_de_mercado", REGRESSION)
        assert out["status"] == "ok"
        assert "3.1.47" in out["definition_clause"]

    def test_cost_method_cannot_produce_valor_de_mercado_either(self):
        """The guard is symmetric: the cost route does not output market value."""
        out = rules.value_basis_guard("valor_de_mercado", COST_METHOD)
        assert out["status"] == "refused"

    def test_unknown_basis_is_unsupported_never_approved(self):
        out = rules.value_basis_guard("valor_de_liquidacao_forcada_inventado", REGRESSION)
        assert out["status"] == "unsupported", (
            "base desconhecida deve ser 'unsupported': ausência de regra não é "
            "aprovação."
        )
        assert out["status"] != "ok"
        assert "required_method" not in out

    def test_absent_basis_is_unsupported_not_approval(self):
        for missing in (None, ""):
            out = rules.value_basis_guard(missing, REGRESSION)
            assert out["status"] == "unsupported", (
                "base de valor ausente tem de ser 'unsupported'; silêncio não "
                "autoriza método nenhum."
            )
            assert "required_method" not in out

    def test_refusal_payload_names_the_required_method_and_memory(self):
        out = rules.value_basis_guard("custo_de_reedicao", REGRESSION)
        assert out["status"] == "refused"
        # Required method: only the cost quantification route produces 3.1.11.3.
        assert out["required_method"] == [COST_METHOD]
        # Required memory of calculation, item by item of Tabela 6.
        assert set(out["required_memory"]) == {"custo_direto", "bdi", "depreciacao_fisica"}
        assert "3.1.11.3" in out["definition_clause"]
        assert COST_METHOD in out["detail"]

    def test_refused_insurance_basis_names_the_policy_as_the_required_source(self):
        out = rules.value_basis_guard("valor_em_risco", REGRESSION)
        assert out["status"] == "refused"
        assert out["required_method"] == [POLICY]
        assert "3.1.51" in out["definition_clause"]

    def test_refused_lmg_has_no_appraisal_memory_to_offer(self):
        out = rules.value_basis_guard("limite_maximo_de_garantia", REGRESSION)
        assert out["status"] == "refused"
        assert out["required_method"] == [POLICY]
        assert out["required_memory"] == [], (
            "o LMG não tem memória de cálculo de avaliação: é montante contratual."
        )

    def test_reproducao_refusal_requires_only_custo_direto_and_bdi(self):
        out = rules.value_basis_guard("custo_de_reproducao", REGRESSION)
        assert out["status"] == "refused"
        assert out["required_memory"] == ["custo_direto", "bdi"], (
            "3.1.11.5 não desconta depreciação, logo não exige memória de depreciação."
        )


# --------------------------------------------------------------------------
# Tabela 6 — the three documentary items of the cost route
# --------------------------------------------------------------------------

class TestTabela6Items:

    def test_tabela6_has_exactly_three_items(self):
        assert len(rules.TABELA6_ITEMS) == 3
        assert [it["item"] for it in rules.TABELA6_ITEMS] == [1, 2, 3]

    def test_every_item_carries_a_criterion_for_graus_iii_ii_and_i(self):
        for entry in rules.TABELA6_ITEMS:
            criteria = entry["criteria"]
            assert set(criteria) == {3, 2, 1}, (
                f"item {entry['item']} da Tabela 6 sem os três graus: {sorted(criteria)}"
            )
            for grade, text in criteria.items():
                assert isinstance(text, str) and text.strip(), (
                    f"item {entry['item']} grau {grade} sem critério textual"
                )

    def test_item1_is_custo_direto_with_orcamento_sintetico_at_grau_iii(self):
        item1 = next(e for e in rules.TABELA6_ITEMS if e["item"] == 1)
        assert "custo direto" in item1["description"].lower()
        assert "orçamento" in item1["criteria"][3].lower()
        assert "sintético" in item1["criteria"][3].lower()
        # Graus II e I usam o CUB; a diferença é a semelhança com o projeto padrão.
        assert "semelhante" in item1["criteria"][2].lower()
        assert "diferente" in item1["criteria"][1].lower()
        assert "ajuste" in item1["criteria"][1].lower()

    def test_item2_is_bdi_calculado_justificado_arbitrado(self):
        item2 = next(e for e in rules.TABELA6_ITEMS if e["item"] == 2)
        assert item2["description"].upper() == "BDI"
        assert item2["criteria"][3].lower().startswith("calculado")
        assert item2["criteria"][2].lower().startswith("justificado")
        assert item2["criteria"][1].lower().startswith("arbitrado")

    def test_item3_is_depreciacao_fisica_with_arbitrada_only_at_grau_i(self):
        item3 = next(e for e in rules.TABELA6_ITEMS if e["item"] == 3)
        assert "deprecia" in item3["description"].lower()
        assert "recupera" in item3["criteria"][3].lower()
        for word in ("idade", "vida útil", "conserva"):
            assert word in item3["criteria"][2].lower()
        assert "arbitrada" in item3["criteria"][1].lower()

    def test_all_three_items_are_documentary_none_comes_from_the_market_sample(self):
        for entry in rules.TABELA6_ITEMS:
            assert entry["evidence_kind"] == "documental"


# --------------------------------------------------------------------------
# Tabela 7 — enquadramento of the cost quantification method
# --------------------------------------------------------------------------

class TestTabela7CustoFundamentacao:

    def test_minimum_points_are_7_5_and_3(self):
        assert rules.TABELA7_PONTOS_III == 7
        assert rules.TABELA7_PONTOS_II == 5
        assert rules.TABELA7_PONTOS_I == 3

    def test_grau_iii_with_7_points_and_item1_at_iii(self):
        # 3 + 2 + 2 = 7 pontos; item 1 no Grau III; itens 2 e 3 no Grau II.
        out = rules.classify_custo_fundamentacao({1: 3, 2: 2, 3: 2})
        assert out["points"] == 7
        assert out["grade"] == 3
        assert out["pending_items"] == []
        assert out["evidence_status"] == rules.EVIDENCE_CALCULATED

    def test_maximum_score_is_grau_iii(self):
        out = rules.classify_custo_fundamentacao({1: 3, 2: 3, 3: 3})
        assert out["points"] == 9
        assert out["grade"] == 3

    def test_grau_ii_with_exactly_5_points(self):
        # 2 + 2 + 1 = 5 pontos; itens 1 e 2 no Grau II -> Grau II.
        out = rules.classify_custo_fundamentacao({1: 2, 2: 2, 3: 1})
        assert out["points"] == 5
        assert out["grade"] == 2

    def test_grau_i_with_exactly_3_points(self):
        out = rules.classify_custo_fundamentacao({1: 1, 2: 1, 3: 1})
        assert out["points"] == 3
        assert out["grade"] == 1

    def test_five_points_with_item1_below_ii_is_grau_i_not_grau_ii(self):
        # 1 + 2 + 2 = 5 pontos, mas a Tabela 7 exige o item 1 no mínimo no
        # Grau II para o Grau II. Pontos não compram o item obrigatório.
        out = rules.classify_custo_fundamentacao({1: 1, 2: 2, 3: 2})
        assert out["points"] == 5
        assert out["grade"] != 2
        assert out["grade"] == 1

    def test_five_points_with_item2_below_ii_is_grau_i_not_grau_ii(self):
        # 2 + 1 + 2 = 5 pontos; o item 2 (BDI) abaixo do Grau II barra o Grau II.
        out = rules.classify_custo_fundamentacao({1: 2, 2: 1, 3: 2})
        assert out["points"] == 5
        assert out["grade"] == 1

    def test_seven_points_with_item3_below_ii_is_not_grau_iii(self):
        # 3 + 3 + 1 = 7 pontos, mas o item 3 no Grau I quebra o obrigatório
        # "os demais no mínimo no Grau II" do Grau III. Cai para Grau II
        # (5 pontos com itens 1 e 2 >= II).
        out = rules.classify_custo_fundamentacao({1: 3, 2: 3, 3: 1})
        assert out["points"] == 7
        assert out["grade"] != 3
        assert out["grade"] == 2

    def test_seven_points_with_item1_below_iii_is_not_grau_iii(self):
        # 2 + 3 + 2 = 7 pontos; o Grau III exige o item 1 NO Grau III.
        out = rules.classify_custo_fundamentacao({1: 2, 2: 3, 3: 2})
        assert out["points"] == 7
        assert out["grade"] != 3
        assert out["grade"] == 2

    @pytest.mark.parametrize("scores", [
        {1: None, 2: 2, 3: 2},
        {1: 3, 2: None, 3: 2},
        {1: 3, 2: 2, 3: None},
        {1: None, 2: None, 3: None},
        {},
    ])
    def test_any_pending_item_blocks_the_enquadramento(self, scores):
        out = rules.classify_custo_fundamentacao(scores)
        assert out["grade"] is None, (
            "item da Tabela 6 ausente não pode render grau: ausência não é aprovação."
        )
        expected_pending = [i for i in (1, 2, 3) if scores.get(i) is None]
        assert out["pending_items"] == expected_pending
        assert out["evidence_status"] == rules.EVIDENCE_PENDING

    def test_pending_item_does_not_fall_back_to_a_lower_grade(self):
        # 3 + 3 = 6 pontos conhecidos, o que bastaria para o Grau II se o item
        # pendente fosse tratado como Grau I. Não deve haver esse fallback.
        out = rules.classify_custo_fundamentacao({1: 3, 2: 3, 3: None})
        assert out["grade"] is None
        assert out["pending_items"] == [3]
        assert out["points"] == 6

    def test_result_cites_tabela7_of_the_2011_edition(self):
        out = rules.classify_custo_fundamentacao({1: 3, 2: 2, 3: 2})
        source = out["source"]
        assert "Tabela 7" in source["clause"]
        assert source["edition"] == rules.EDITION_PART2
        assert "14653-2" in source["edition"]
        assert "2011" in source["edition"]


# --------------------------------------------------------------------------
# assess_qualification — a blocked profile does not release
# --------------------------------------------------------------------------

def _calculable_normative_context():
    """A technically sound regression: nothing here is meant to be degenerate."""
    return assess_normative({
        "n": 24,
        "k": 3,
        "intercept": True,
        "pvalues": {"area": 0.001, "frente": 0.02, "padrao": 0.05},
        "f_pvalue": 0.0001,
        "amplitude_pct": 22.0,
        "grau_item1": 3,
        "item1_provenance": "vistoria_interna_documentada",
        "grau_item3": 3,
        "item3_provenance": "documento_primario_conferido",
    })


def _fully_supplied_context(profile, fingerprint=None):
    ctx = {
        "normative_assessment": _calculable_normative_context(),
        "profile_evidence": {
            req["id"]: {"ref": f"evidencia::{req['id']}"}
            for req in profile.get("requirements") or []
        },
        "targets_grau_iii": True,
        "software_version": "test-a06",
    }
    if fingerprint is not None:
        ctx["review_events"] = [{
            "professional_id": "CREA-0000000000",
            "motive": "revisão técnica completa",
            "version": "1",
            "fingerprint": fingerprint,
        }]
        ctx["signature"] = {"integrity_verified": True, "fingerprint": fingerprint}
    return ctx


class TestCostProfileCalculationBoundary:

    PROFILE_ID = "abnt-14653-2-custo-reedicao"

    def _profile(self):
        return resolve_profile({"id": self.PROFILE_ID})

    def test_cost_profile_is_verified_for_the_identified_editions_only(self):
        assert self.PROFILE_ID in known_profile_ids()
        resolved = self._profile()
        assert resolved["state"] == PROFILE_VERIFIED
        assert resolved["version"] == "0.2.0"
        assert {source["currency_status"] for source in resolved["sources"]} == {
            "edition_on_hand_verified_currency_unconfirmed"
        }

    def test_generic_declared_evidence_cannot_replace_cost_result(self):
        profile = self._profile()
        first = assess_qualification(_fully_supplied_context(profile), {"id": self.PROFILE_ID})
        fingerprint = first["result_fingerprint"]
        assert fingerprint, "sem result_fingerprint não há como registrar revisão"

        # Second pass: review and signature recorded against THAT fingerprint,
        # every declared requirement evidenced. Everything else is supplied.
        second = assess_qualification(
            _fully_supplied_context(profile, fingerprint=fingerprint),
            {"id": self.PROFILE_ID},
        )
        assert second["result_fingerprint"] == fingerprint

        assert second["profile"]["state"] == PROFILE_VERIFIED
        assert second["case_release_status"] != CASE_READY_FOR_SIGNOFF, (
            "evidência lateral sem resultado MP-COST/1 não pode liberar assinatura."
        )
        assert second["case_release_status"] != CASE_SIGNED_INTEGRITY_VERIFIED
        assert second["case_release_status"] == CASE_ANALYSIS_ONLY

        codes = {b["code"] for b in second["release_blockers"]}
        assert "decisive_rule_absent" in codes

    def test_cost_profile_declares_custo_de_reedicao_and_the_cost_method(self):
        profile = self._profile()
        assert profile["value_basis"] == "custo_de_reedicao"
        assert profile["method"] == COST_METHOD

    def test_cost_profile_value_basis_rule_passes_because_basis_matches_method(self):
        """The basis/method pair is coherent; it is the EVIDENCE that is blocked."""
        result = assess_qualification(
            {"normative_assessment": _calculable_normative_context()},
            {"id": self.PROFILE_ID},
        )
        rule = next(r for r in result["rule_results"]
                    if r["rule_id"] == "parte1.bases_de_valor")
        assert rule["status"] == RULE_PASSED
        assert "3.1.11.3" in rule["clause"]

    def test_cost_route_calculation_requirement_stays_unverified(self):
        profile = self._profile()
        result = assess_qualification(
            _fully_supplied_context(profile), {"id": self.PROFILE_ID}
        )
        rule = next(r for r in result["rule_results"]
                    if r["rule_id"] == "metodos.custo.calculo")
        assert rule["status"] != RULE_PASSED, (
            "a rota de cálculo do custo não está implementada; evidência anexada "
            "ao lado não a torna verificada."
        )


class TestMarketProfileValueBasis:

    PROFILE_ID = "abnt-14653-2-regressao-mercado"

    def test_market_profile_declares_valor_de_mercado_under_the_regression(self):
        resolved = resolve_profile({"id": self.PROFILE_ID})
        assert resolved["value_basis"] == "valor_de_mercado"
        assert resolved["method"] == REGRESSION

    def test_market_profile_value_basis_rule_result_passes(self):
        result = assess_qualification(
            {"normative_assessment": _calculable_normative_context()},
            {"id": self.PROFILE_ID},
        )
        assert result["profile"]["value_basis"] == "valor_de_mercado"
        rule = next(r for r in result["rule_results"]
                    if r["rule_id"] == "parte1.bases_de_valor")
        assert rule["status"] == RULE_PASSED
        assert "3.1.47" in rule["clause"]
        assert rule["observed"] == {"value_basis": "valor_de_mercado",
                                    "method": REGRESSION}

    def test_market_profile_would_be_refused_if_it_claimed_a_cost_basis(self):
        """The guard, not the profile file, is what forbids the conversion."""
        out = rules.value_basis_guard("custo_de_reedicao", REGRESSION)
        assert out["status"] == "refused"
        assert out["required_method"] == [COST_METHOD]
