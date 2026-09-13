"""C05-A02 — cobertura completa do escopo anunciado.

Toda regra registrada (verificada ou não) precisa ter um DESTINO explícito, e
nenhuma regra pode ser simultaneamente "verificada" e "não verificada". Ausência
de destino é buraco de cobertura, não aprovação.

Os valores esperados aqui vêm do texto normativo e do contrato do módulo:
 - ABNT NBR 14653-2:2011, 10.1 a)-m): treze itens de conteúdo mínimo do laudo
   completo — portanto exatamente 13 entradas com chaves 'a'..'m'.
 - 9.2.1.1 a)-d): quatro obrigações adicionais para o Grau III.
 - 9.1.2: não atingido o grau mínimo I, indicar e justificar os itens não
   atendidos — portanto a obrigação registrada precisa ancorar em 9.1.2.
 - Anexo A.2 a) (micronumerosidade), Anexo A.3.1 (teto de alpha de 10% nos
   demais testes), Anexo A.2 c)/d)/e) (pressupostos), 9.3/Tabela 6/Tabela 7
   (método da quantificação de custo) e as bases de valor da Parte 1:2019
   passaram a ser calculáveis nesta campanha: precisam estar em RULE_MATRIX
   como 'verified' e NÃO podem continuar em UNVERIFIED_RULES.
"""

import pytest

from modules import normative_rules as nr


# ---------------------------------------------------------------------------
# inventário: nenhum buraco de cobertura
# ---------------------------------------------------------------------------

def test_inventory_audit_is_complete_and_has_no_rule_without_destination():
    audit = nr.inventory_audit()
    assert audit["missing_destination"] == []
    assert audit["complete"] is True


def test_inventory_total_equals_both_registries():
    audit = nr.inventory_audit()
    assert audit["total"] == len(nr.RULE_MATRIX) + len(nr.UNVERIFIED_RULES)


def test_destinations_tuple_is_exactly_the_four_announced_routes():
    assert set(nr.DESTINATIONS) == {
        "automatic",
        "professional_evidenced",
        "out_of_announced_offer",
        "external_blocked",
    }
    assert len(nr.DESTINATIONS) == 4


# ---------------------------------------------------------------------------
# destino explícito e válido em cada registro
# ---------------------------------------------------------------------------

def test_every_rule_matrix_entry_resolves_to_a_known_destination():
    for rule in nr.RULE_MATRIX:
        destination = rule.get("destination", "automatic")
        assert destination in nr.DESTINATIONS, f"{rule['id']} -> {destination!r}"


def test_every_unverified_rule_declares_a_known_destination_explicitly():
    for rule in nr.UNVERIFIED_RULES:
        # Sem default: uma regra não verificada tem de dizer COMO é cumprida.
        assert "destination" in rule, f"{rule['id']} sem destination"
        assert rule["destination"] in nr.DESTINATIONS, f"{rule['id']} -> {rule['destination']!r}"


def test_no_unverified_rule_is_routed_to_automatic():
    # "automatic" significa calculado por este módulo; então pertenceria a
    # RULE_MATRIX, não ao registro de não verificadas.
    for rule in nr.UNVERIFIED_RULES:
        assert rule["destination"] != "automatic", rule["id"]


# ---------------------------------------------------------------------------
# rules_by_destination: particiona sem perda e recusa destino desconhecido
# ---------------------------------------------------------------------------

def test_rules_by_destination_raises_on_unknown_destination():
    with pytest.raises(ValueError):
        nr.rules_by_destination("conveniencia")


@pytest.mark.parametrize("bogus", ["", "AUTOMATIC", "manual", "automático", None])
def test_rules_by_destination_raises_on_every_non_destination(bogus):
    with pytest.raises(ValueError):
        nr.rules_by_destination(bogus)


def test_rules_by_destination_partitions_both_registries_without_loss():
    total = len(nr.RULE_MATRIX) + len(nr.UNVERIFIED_RULES)
    per_destination = {d: nr.rules_by_destination(d) for d in nr.DESTINATIONS}
    assert sum(len(v) for v in per_destination.values()) == total


def test_rules_by_destination_partition_ids_cover_every_rule_exactly_once():
    collected = []
    for destination in nr.DESTINATIONS:
        collected.extend(r["id"] for r in nr.rules_by_destination(destination))
    expected = [r["id"] for r in nr.RULE_MATRIX] + [r["id"] for r in nr.UNVERIFIED_RULES]
    assert sorted(collected) == sorted(expected)
    assert len(collected) == len(set(collected)), "regra em mais de um destino"


def test_inventory_counts_match_the_hand_counted_registries():
    """Contagem feita à mão sobre o código-fonte dos dois registros.

    RULE_MATRIX = 12 entradas originais (tabela1.item1, item2, item3,
    item4.measure, item4.value, anexoA.5_7.qualitative, item5, item6,
    tabela2.enquadramento, tabela5.precisao, campo_arbitrio,
    admissiveis.central), todas sem destino explícito e portanto automáticas,
    + 8 entradas da campanha: 5 automáticas (micronumerosidade, A.3.1,
    A.2 c/d/e, Tabela 6/7 custo, bases de valor) e 3 profissionais
    (9.1.2 não classificado, 10.1 laudo completo, 6.3 vistoria) = 20.

    UNVERIFIED_RULES = 13: 8 profissionais (9.2.1.1 extras, A.2 f, A.2 g,
    A.2 h, A.2 i/A.2.1.6 outliers, A.8 agrupamentos, 8.2.1.5.2/8.2.1.5.3,
    A.10.1.2 arbitrado), 3 fora da oferta (9.2.1.6.1 amostra homogênea,
    Tabelas 3-4 fatores, involutivo/evolutivo) e 2 bloqueadas externamente
    (rota de cálculo do custo, vigência das edições ABNT).

    Total 33; automático 17; profissional 3 + 8 = 11; fora da oferta 3;
    bloqueado externamente 2.
    """
    audit = nr.inventory_audit()
    assert len(nr.RULE_MATRIX) == 20
    assert len(nr.UNVERIFIED_RULES) == 13
    assert audit["total"] == 33
    assert audit["counts"] == {
        "automatic": 17,
        "professional_evidenced": 11,
        "out_of_announced_offer": 3,
        "external_blocked": 2,
    }


def test_inventory_counts_match_rules_by_destination():
    audit = nr.inventory_audit()
    for destination in nr.DESTINATIONS:
        assert audit["counts"][destination] == len(nr.rules_by_destination(destination))


# ---------------------------------------------------------------------------
# cada não verificada tem motivo e via de cumprimento
# ---------------------------------------------------------------------------

def test_every_unverified_rule_carries_a_non_empty_reason_and_requires():
    for rule in nr.UNVERIFIED_RULES:
        assert "reason" in rule, f"{rule['id']} sem reason"
        assert isinstance(rule["reason"], str)
        assert rule["reason"].strip(), f"{rule['id']} com reason vazio"
        assert "requires" in rule, f"{rule['id']} sem requires"
        assert isinstance(rule["requires"], str)
        assert rule["requires"].strip(), f"{rule['id']} com requires vazio"


def test_every_unverified_rule_anchors_a_clause():
    for rule in nr.UNVERIFIED_RULES:
        assert rule.get("clause", "").strip(), f"{rule['id']} sem clause"


def test_out_of_announced_offer_reasons_reference_the_announced_offer():
    entries = nr.rules_by_destination("out_of_announced_offer")
    assert entries, "nenhum recorte de oferta declarado"
    for rule in entries:
        reason = rule["reason"].lower()
        # O recorte tem de ser da OFERTA anunciada, não mera conveniência.
        assert "oferta" in reason, f"{rule['id']}: motivo não cita a oferta"


def test_out_of_announced_offer_never_claims_the_requirement_is_inapplicable():
    for rule in nr.rules_by_destination("out_of_announced_offer"):
        blocks = rule.get("blocks", "")
        assert isinstance(blocks, str) and blocks.strip(), f"{rule['id']} sem blocks"


# ---------------------------------------------------------------------------
# uma regra não pode ser verificada e não verificada ao mesmo tempo
# ---------------------------------------------------------------------------

def test_no_rule_id_is_in_both_registries():
    matrix_ids = {r["id"] for r in nr.RULE_MATRIX}
    unverified_ids = {r["id"] for r in nr.UNVERIFIED_RULES}
    assert matrix_ids & unverified_ids == set()


def test_rule_ids_are_unique_inside_each_registry():
    matrix_ids = [r["id"] for r in nr.RULE_MATRIX]
    assert len(matrix_ids) == len(set(matrix_ids))
    unverified_ids = [r["id"] for r in nr.UNVERIFIED_RULES]
    assert len(unverified_ids) == len(set(unverified_ids))


def test_no_unverified_rule_appears_among_verified_rule_ids():
    verified = set(nr.verified_rule_ids())
    for rule_id in nr.unverified_rule_ids():
        assert rule_id not in verified, f"{rule_id} marcado como verificado e não verificado"


def test_unverified_rule_ids_matches_the_unverified_registry():
    assert nr.unverified_rule_ids() == [r["id"] for r in nr.UNVERIFIED_RULES]


def test_every_rule_matrix_entry_is_verified_so_the_two_sets_are_equal():
    matrix_ids = {r["id"] for r in nr.RULE_MATRIX}
    # RULE_MATRIX é o registro do que é verificado: igualdade, não inclusão.
    assert set(nr.verified_rule_ids()) == matrix_ids


# ---------------------------------------------------------------------------
# as regras que passaram a ser automáticas nesta campanha
# ---------------------------------------------------------------------------

NOW_AUTOMATIC = [
    # Anexo A.2 a): n >= 3(k+1) e n_i por característica.
    "anexoA.2.micronumerosidade",
    # Anexo A.3.1: teto normativo de 10% para alpha nos demais testes.
    "anexoA.3.1.significancia_auxiliar",
    # Anexo A.2 c) homocedasticidade, d) normalidade, e) autocorrelação.
    "anexoA.2.cde.pressupostos",
    # 9.3 / Tabela 6 / Tabela 7: enquadramento do método da quantificação de custo.
    "tabela6_7.custo.enquadramento",
    # Parte 1:2019: bases de valor e o método que as produz.
    "parte1.bases_de_valor",
]


@pytest.mark.parametrize("rule_id", NOW_AUTOMATIC)
def test_now_automatic_rule_is_verified_in_rule_matrix(rule_id):
    by_id = {r["id"]: r for r in nr.RULE_MATRIX}
    assert rule_id in by_id, f"{rule_id} ausente de RULE_MATRIX"
    rule = by_id[rule_id]
    assert rule["verification_status"] == "verified"
    assert rule.get("destination", "automatic") == "automatic"
    assert rule.get("clause", "").strip()
    assert rule.get("calculation", "").strip()


@pytest.mark.parametrize("rule_id", NOW_AUTOMATIC)
def test_now_automatic_rule_is_no_longer_unverified(rule_id):
    assert rule_id not in nr.unverified_rule_ids()


@pytest.mark.parametrize("rule_id", NOW_AUTOMATIC)
def test_now_automatic_rule_is_callable_and_not_a_stub(rule_id):
    # A entrada só é honesta se a rota de cálculo existir de fato.
    entrypoints = {
        "anexoA.2.micronumerosidade": ("classify_micronumerosidade", "minimum_ni"),
        "anexoA.3.1.significancia_auxiliar": ("max_auxiliary_alpha",),
        "anexoA.2.cde.pressupostos": ("evaluate_pressuposto",),
        "tabela6_7.custo.enquadramento": ("classify_custo_fundamentacao",),
        "parte1.bases_de_valor": ("value_basis_guard",),
    }
    for name in entrypoints[rule_id]:
        assert callable(getattr(nr, name)), f"{rule_id}: {name} não é chamável"


def test_anexo_a31_ceiling_is_ten_percent():
    # Anexo A.3.1: nível de significância máximo dos demais testes = 10%.
    assert nr.max_auxiliary_alpha() == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# external_blocked: vigência das edições e rota de cálculo do custo
# ---------------------------------------------------------------------------

def test_external_blocked_contains_the_abnt_edition_currency_entry():
    entries = {r["id"]: r for r in nr.rules_by_destination("external_blocked")}
    assert "abnt.vigencia_das_edicoes" in entries
    rule = entries["abnt.vigencia_das_edicoes"]
    reason = rule["reason"].lower()
    assert "vigencia" in reason or "vigência" in reason
    assert rule["requires"].strip()
    # O bloqueio é sobre a edição VIGENTE; a conformidade com a edição conferida
    # (14653-2:2011 e 14653-1:2019) permanece.
    assert "vigente" in rule["blocks"].lower()


def test_external_blocked_contains_the_cost_calculation_route_entry():
    entries = {r["id"]: r for r in nr.rules_by_destination("external_blocked")}
    assert "metodos.custo.calculo" in entries
    rule = entries["metodos.custo.calculo"]
    reason = rule["reason"].lower()
    assert "cub" in reason
    assert "custo" in reason
    assert rule["requires"].strip()


def test_cost_rule_and_cost_route_are_distinct_registrations():
    # A REGRA de enquadramento (Tabela 6/7) é automática; a ROTA de cálculo do
    # custo continua externamente bloqueada. São registros distintos.
    assert "tabela6_7.custo.enquadramento" in nr.verified_rule_ids()
    assert "metodos.custo.calculo" in nr.unverified_rule_ids()


def test_every_external_blocked_entry_names_the_missing_source():
    entries = nr.rules_by_destination("external_blocked")
    assert len(entries) >= 2
    for rule in entries:
        assert rule["requires"].strip(), f"{rule['id']} sem fonte faltante"
        assert rule.get("blocks", "").strip(), f"{rule['id']} sem blocks"


# ---------------------------------------------------------------------------
# 10.1 a)-m): treze itens do laudo completo
# ---------------------------------------------------------------------------

def test_laudo_completo_has_exactly_thirteen_items():
    # ABNT NBR 14653-2:2011, 10.1 a) até m) = 13 alíneas.
    assert len(nr.LAUDO_COMPLETO_ITEMS) == 13


def test_laudo_completo_keys_are_exactly_a_through_m_in_order():
    expected_keys = list("abcdefghijklm")
    assert len(expected_keys) == 13
    assert [item["key"] for item in nr.LAUDO_COMPLETO_ITEMS] == expected_keys


def test_laudo_completo_ids_are_unique_and_anchored_to_10_1():
    ids = [item["id"] for item in nr.LAUDO_COMPLETO_ITEMS]
    assert len(ids) == len(set(ids))
    for item in nr.LAUDO_COMPLETO_ITEMS:
        assert item["id"] == f"10.1.{item['key']}"


def test_every_laudo_completo_item_states_a_requirement():
    for item in nr.LAUDO_COMPLETO_ITEMS:
        assert item.get("requirement", "").strip(), item["id"]


def test_laudo_completo_is_registered_in_rule_matrix():
    by_id = {r["id"]: r for r in nr.RULE_MATRIX}
    assert "10.1.laudo_completo" in by_id
    rule = by_id["10.1.laudo_completo"]
    assert rule["clause"] == "10.1 a)-m)"
    # A presença de cada item é documental: destino profissional evidenciado.
    assert rule["destination"] == "professional_evidenced"


# ---------------------------------------------------------------------------
# 9.2.1.1 a)-d): obrigações adicionais do Grau III
# ---------------------------------------------------------------------------

def test_grau_iii_additional_requirements_cover_9_2_1_1_a_to_d():
    ids = [entry["id"] for entry in nr.GRAU_III_ADDITIONAL_REQUIREMENTS]
    assert ids == ["9.2.1.1.a", "9.2.1.1.b", "9.2.1.1.c", "9.2.1.1.d"]
    assert len(ids) == 4


def test_every_grau_iii_additional_requirement_declares_text_and_verification():
    for entry in nr.GRAU_III_ADDITIONAL_REQUIREMENTS:
        assert entry.get("requirement", "").strip(), entry["id"]
        assert entry.get("verification", "").strip(), entry["id"]


def test_grau_iii_extras_are_registered_as_professional_evidenced_and_block_grau_iii():
    by_id = {r["id"]: r for r in nr.UNVERIFIED_RULES}
    assert "9.2.1.1.extras" in by_id
    rule = by_id["9.2.1.1.extras"]
    assert rule["destination"] == "professional_evidenced"
    assert rule["clause"] == "9.2.1.1 a)-d)"
    # Sem a evidência, o Grau III fica bloqueado — ausência não é aprovação.
    assert "III" in rule["blocks"]


# ---------------------------------------------------------------------------
# 9.1.2: não classificado é via prevista, com indicação e justificativa
# ---------------------------------------------------------------------------

def test_nao_classificado_obligation_references_clause_9_1_2():
    obligation = nr.NAO_CLASSIFICADO_OBLIGATION
    assert obligation["id"] == "9.1.2"
    assert obligation["clause"] == "9.1.2"


def test_nao_classificado_obligation_demands_indication_and_justification():
    text = nr.NAO_CLASSIFICADO_OBLIGATION["requirement"].lower()
    assert "indicados" in text
    assert "justificados" in text


def test_nao_classificado_rule_is_registered_and_professional_evidenced():
    by_id = {r["id"]: r for r in nr.RULE_MATRIX}
    assert "9.1.2.nao_classificado" in by_id
    rule = by_id["9.1.2.nao_classificado"]
    assert rule["clause"] == "9.1.2"
    assert rule["destination"] == "professional_evidenced"
    assert rule["verification_status"] == "verified"


# ---------------------------------------------------------------------------
# vistoria (Parte 1:2019, 6.3.1): essencial; paradigma é excepcional
# ---------------------------------------------------------------------------

def test_vistoria_requirement_is_registered_and_professional_evidenced():
    assert nr.VISTORIA_REQUIREMENT["clause"].startswith("6.3.1")
    assert nr.VISTORIA_REQUIREMENT["verification"] == "professional_evidenced"
    by_id = {r["id"]: r for r in nr.RULE_MATRIX}
    assert "parte1.6.3.vistoria" in by_id
    assert by_id["parte1.6.3.vistoria"]["destination"] == "professional_evidenced"


# ---------------------------------------------------------------------------
# nenhuma regra decisiva aprovada sem verificação
# ---------------------------------------------------------------------------

def test_every_rule_matrix_entry_declares_a_verification_status():
    for rule in nr.RULE_MATRIX:
        assert rule.get("verification_status"), rule["id"]


def test_no_rule_matrix_entry_is_silently_unverified():
    # RULE_MATRIX é o registro do que É verificado; um 'unverified' aqui seria
    # uma regra aprovada sem verificação.
    for rule in nr.RULE_MATRIX:
        assert rule["verification_status"] != "unverified", rule["id"]


def test_every_rule_matrix_entry_cites_at_least_one_test_id():
    for rule in nr.RULE_MATRIX:
        test_ids = rule.get("test_ids")
        assert isinstance(test_ids, list) and test_ids, rule["id"]


def test_every_rule_matrix_entry_declares_a_known_edition():
    known = {nr.EDITION_PART2, nr.EDITION_PART1_2001, nr.EDITION_PART1_2019}
    for rule in nr.RULE_MATRIX:
        assert rule.get("edition") in known, rule["id"]
