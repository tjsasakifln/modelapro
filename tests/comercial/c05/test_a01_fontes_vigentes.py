"""C05-A01 — fontes autorizadas e vigência declarada.

Every expected number in this file was computed by hand from the licensed
editions of ABNT NBR 14653-2:2011 and ABNT NBR 14653-1:2019 (see the campaign
normative facts), never by running the product and copying its output.

What is under test here is the *provenance layer*: a threshold the product
applies must name the edition, the clause and the page it came from; the number
recorded in the provenance must be the same number the code actually applies;
and no source may claim a currency (vigência) that nobody was able to confirm.
"""

from __future__ import annotations

import datetime as _dt
import re

import pytest

from modules import normative_rules as nr


# --- hand-authored expectations ----------------------------------------------

#: Every threshold family the product applies and therefore must document.
#: Hand-authored: driving the loops below off ``THRESHOLD_PROVENANCE.items()``
#: would pass vacuously if a record were dropped.
EXPECTED_THRESHOLD_KEYS = frozenset(
    {
        "ITEM2_FACTORS",            # Tabela 1 item 2
        "MEASURE_LOWER_FACTOR",     # Tabela 1 item 4 (a)
        "MEASURE_UPPER_FACTOR",     # Tabela 1 item 4 (a)
        "VALUE_LIMITS",             # Tabela 1 item 4 (b)
        "ITEM5_LIMITS",             # Tabela 1 item 5
        "ITEM6_LIMITS",             # Tabela 1 item 6
        "TABELA2_PONTOS",           # Tabela 2 / 9.2.1.6
        "PRECISAO_LIMITS",          # Tabela 5 / 9.2.3
        "CAMPO_ARBITRIO",           # 8.2.1.5.1
        "MICRONUMEROSIDADE",        # Anexo A.2 a)
        "SIGNIFICANCE_AUX",         # Anexo A.3.1
        "CORRELATION_ATTENTION",    # Anexo A.2.1.5.2
        "TABELA7_PONTOS_CUSTO",     # Tabela 7 / 9.3
    }
)

#: Clause anchor each record must cite, read by hand off the normative facts.
EXPECTED_CLAUSE_ANCHORS = {
    "ITEM2_FACTORS": "Tabela 1 item 2",
    "MEASURE_LOWER_FACTOR": "Tabela 1 item 4",
    "MEASURE_UPPER_FACTOR": "Tabela 1 item 4",
    "VALUE_LIMITS": "Tabela 1 item 4",
    "ITEM5_LIMITS": "Tabela 1 item 5",
    "ITEM6_LIMITS": "Tabela 1 item 6",
    "TABELA2_PONTOS": "Tabela 2",
    "PRECISAO_LIMITS": "Tabela 5",
    "CAMPO_ARBITRIO": "8.2.1.5.1",
    "MICRONUMEROSIDADE": "Anexo A.2 a)",
    "SIGNIFICANCE_AUX": "Anexo A.3.1",
    "CORRELATION_ATTENTION": "Anexo A.2.1.5.2",
    "TABELA7_PONTOS_CUSTO": "Tabela 7",
}

EXPECTED_SOURCE_EDITIONS = frozenset(
    {"ABNT NBR 14653-2:2011", "ABNT NBR 14653-1:2019"}
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _iter_strings(node):
    """Yield every string reachable inside a nested mapping/sequence."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from _iter_strings(value)
    elif isinstance(node, (list, tuple, set, frozenset)):
        for value in node:
            yield from _iter_strings(value)


# --- 1. every applied threshold is documented --------------------------------


def test_threshold_provenance_documents_exactly_the_applied_thresholds():
    assert set(nr.THRESHOLD_PROVENANCE) == set(EXPECTED_THRESHOLD_KEYS)
    assert set(EXPECTED_CLAUSE_ANCHORS) == set(EXPECTED_THRESHOLD_KEYS)


@pytest.mark.parametrize("key", sorted(EXPECTED_THRESHOLD_KEYS))
def test_each_threshold_record_names_edition_clause_and_page(key):
    record = nr.THRESHOLD_PROVENANCE[key]

    edition = record["edition"]
    assert isinstance(edition, str) and edition.strip()
    # An edition label that is not a consulted source document is an orphan.
    assert edition in nr.SOURCE_DOCUMENTS

    clause = record["clause"]
    assert isinstance(clause, str) and clause.strip()
    # The clause anchor is hand-derivable from the norm, so it is asserted.
    assert EXPECTED_CLAUSE_ANCHORS[key] in clause

    page = record["page"]
    # The page numbers of a licensed PDF cannot be derived from the normative
    # facts, so only the shape is asserted: a real, positive page anchor.
    assert isinstance(page, int) and not isinstance(page, bool)
    assert page > 0

    values = record["values"]
    assert isinstance(values, dict) and values


@pytest.mark.parametrize("key", sorted(EXPECTED_THRESHOLD_KEYS))
def test_threshold_provenance_accessor_returns_the_record(key):
    record = nr.threshold_provenance(key)
    assert record["edition"] == nr.THRESHOLD_PROVENANCE[key]["edition"]
    assert record["clause"] == nr.THRESHOLD_PROVENANCE[key]["clause"]
    assert record["page"] == nr.THRESHOLD_PROVENANCE[key]["page"]


def test_threshold_provenance_raises_for_unregistered_key():
    with pytest.raises(KeyError):
        nr.threshold_provenance("LIMIAR_QUE_NAO_EXISTE")


def test_threshold_provenance_raises_for_empty_key():
    with pytest.raises(KeyError):
        nr.threshold_provenance("")


def test_threshold_provenance_accessor_returns_a_copy():
    record = nr.threshold_provenance("ITEM6_LIMITS")
    record["clause"] = "adulterado"
    assert nr.THRESHOLD_PROVENANCE["ITEM6_LIMITS"]["clause"] == "Tabela 1 item 6"


# --- 2. documented numbers == applied numbers --------------------------------
# Tabela 1 item 5: pior p ≤ 10% / 20% / 30%.  Tabela 1 item 6: p ≤ 1% / 2% / 5%.
# Tabela 2: 16 / 10 / 6 pontos.  Tabela 5: 30% / 40% / 50%.
# 8.2.1.5.1: ±15%.  Tabela 1 item 4 (b): 15% / 20%.  Tabela 7: 7 / 5 / 3.


def test_item5_provenance_matches_hand_values_and_module_constants():
    values = nr.THRESHOLD_PROVENANCE["ITEM5_LIMITS"]["values"]
    assert values["grau_iii"] == pytest.approx(0.10)
    assert values["grau_ii"] == pytest.approx(0.20)
    assert values["grau_i"] == pytest.approx(0.30)
    assert nr.ITEM5_LIM_III == pytest.approx(0.10)
    assert nr.ITEM5_LIM_II == pytest.approx(0.20)
    assert nr.ITEM5_LIM_I == pytest.approx(0.30)


def test_item6_provenance_matches_hand_values_and_module_constants():
    values = nr.THRESHOLD_PROVENANCE["ITEM6_LIMITS"]["values"]
    assert values["grau_iii"] == pytest.approx(0.01)
    assert values["grau_ii"] == pytest.approx(0.02)
    assert values["grau_i"] == pytest.approx(0.05)
    assert nr.ITEM6_LIM_III == pytest.approx(0.01)
    assert nr.ITEM6_LIM_II == pytest.approx(0.02)
    assert nr.ITEM6_LIM_I == pytest.approx(0.05)


def test_tabela2_points_provenance_matches_hand_values_and_constants():
    values = nr.THRESHOLD_PROVENANCE["TABELA2_PONTOS"]["values"]
    assert values["grau_iii"] == 16
    assert values["grau_ii"] == 10
    assert values["grau_i"] == 6
    assert nr.TABELA2_PONTOS_III == 16
    assert nr.TABELA2_PONTOS_II == 10
    assert nr.TABELA2_PONTOS_I == 6


def test_tabela7_points_provenance_matches_hand_values_and_constants():
    values = nr.THRESHOLD_PROVENANCE["TABELA7_PONTOS_CUSTO"]["values"]
    assert values["grau_iii"] == 7
    assert values["grau_ii"] == 5
    assert values["grau_i"] == 3
    assert nr.TABELA7_PONTOS_III == 7
    assert nr.TABELA7_PONTOS_II == 5
    assert nr.TABELA7_PONTOS_I == 3


def test_precisao_provenance_matches_hand_values_and_constants():
    values = nr.THRESHOLD_PROVENANCE["PRECISAO_LIMITS"]["values"]
    assert values["grau_iii"] == pytest.approx(30.0)
    assert values["grau_ii"] == pytest.approx(40.0)
    assert values["grau_i"] == pytest.approx(50.0)
    assert nr.PRECISAO_LIM_III == pytest.approx(30.0)
    assert nr.PRECISAO_LIM_II == pytest.approx(40.0)
    assert nr.PRECISAO_LIM_I == pytest.approx(50.0)


def test_campo_arbitrio_provenance_matches_hand_value_and_constant():
    values = nr.THRESHOLD_PROVENANCE["CAMPO_ARBITRIO"]["values"]
    assert values["amplitude"] == pytest.approx(0.15)
    assert nr.CAMPO_ARBITRIO == pytest.approx(0.15)
    # 8.2.1.5.4: the campo de arbítrio is not the 80% CI; the record must say so.
    assert "80" in nr.THRESHOLD_PROVENANCE["CAMPO_ARBITRIO"]["detail"]


def test_value_limits_provenance_matches_hand_values_and_constants():
    values = nr.THRESHOLD_PROVENANCE["VALUE_LIMITS"]["values"]
    assert values["grau_ii"] == pytest.approx(0.15)
    assert values["grau_i"] == pytest.approx(0.20)
    assert nr.VALUE_LIMIT_GRAU_II == pytest.approx(0.15)
    assert nr.VALUE_LIMIT_GRAU_I == pytest.approx(0.20)


def test_measure_factors_provenance_matches_hand_values_and_constants():
    upper = nr.THRESHOLD_PROVENANCE["MEASURE_UPPER_FACTOR"]["values"]
    lower = nr.THRESHOLD_PROVENANCE["MEASURE_LOWER_FACTOR"]["values"]
    assert upper["factor"] == pytest.approx(2.0)
    assert lower["factor"] == pytest.approx(0.5)
    assert nr.MEASURE_UPPER_FACTOR == pytest.approx(2.0)
    assert nr.MEASURE_LOWER_FACTOR == pytest.approx(0.5)


def test_auxiliary_alpha_ceiling_is_the_ten_percent_of_anexo_a31():
    # Anexo A.3.1: the significance level of the non-Tabela-1 tests must not
    # exceed 10%.  Both the provenance record and the accessor are checked
    # against the hand value, since the accessor reads that same record.
    values = nr.THRESHOLD_PROVENANCE["SIGNIFICANCE_AUX"]["values"]
    assert values["max_alpha"] == pytest.approx(0.10)
    assert nr.max_auxiliary_alpha() == pytest.approx(0.10)
    assert nr.THRESHOLD_PROVENANCE["SIGNIFICANCE_AUX"]["clause"].startswith("Anexo A.3")


def test_correlation_attention_is_080_and_records_that_no_vif_cut_is_normative():
    record = nr.THRESHOLD_PROVENANCE["CORRELATION_ATTENTION"]
    assert record["values"]["threshold"] == pytest.approx(0.80)
    # A.2.1.5.2 asks for special attention above 0,80; the norm defines no VIF
    # cutoff, and the provenance must not imply that it does.
    assert "VIF" in record["detail"]


# --- 3. the three documented thresholds that have no module constant ---------
# Their numbers live inside the classifiers, so the provenance is cross-checked
# against behaviour exactly at the normative boundary.


def test_item2_factors_provenance_matches_the_boundaries_the_code_applies():
    values = nr.THRESHOLD_PROVENANCE["ITEM2_FACTORS"]["values"]
    assert values["grau_iii"] == 6
    assert values["grau_ii"] == 4
    assert values["grau_i"] == 3

    # k = 3 → 3(k+1) = 12, 4(k+1) = 16, 6(k+1) = 24.
    assert nr.classify_item2_quantidade_dados(24, 3)["grade"] == 3
    assert nr.classify_item2_quantidade_dados(23, 3)["grade"] == 2
    assert nr.classify_item2_quantidade_dados(16, 3)["grade"] == 2
    assert nr.classify_item2_quantidade_dados(15, 3)["grade"] == 1
    assert nr.classify_item2_quantidade_dados(12, 3)["grade"] == 1
    # n = 11 < 3(k+1): below the Grau I minimum, so no grade may be awarded.
    below_minimum = nr.classify_item2_quantidade_dados(11, 3)["grade"]
    assert below_minimum not in (1, 2, 3)
    # And the non-attainment must not be laundered into a Tabela 2 grade.
    assert (
        nr.classify_fundamentacao(
            {1: 2, 2: below_minimum, 3: 2, 4: 1, 5: 1, 6: 1}
        )["grade"]
        is None
    )


def test_micronumerosidade_provenance_matches_the_branches_the_code_applies():
    values = nr.THRESHOLD_PROVENANCE["MICRONUMEROSIDADE"]["values"]
    assert values["n_min_factor"] == 3
    assert values["ni_small"] == 3
    assert values["ni_mid_fraction"] == pytest.approx(0.10)
    assert values["ni_large"] == 10
    assert values["n_small_max"] == 30
    assert values["n_mid_max"] == 100

    # Anexo A.2 a), by hand: n ≤ 30 → 3; 30 < n ≤ 100 → 10% n (rounded up, a
    # fractional datum cannot satisfy a count); n > 100 → 10.
    assert nr.minimum_ni(30) == 3
    assert nr.minimum_ni(31) == 4
    assert nr.minimum_ni(50) == 5
    assert nr.minimum_ni(100) == 10
    assert nr.minimum_ni(101) == 10

    # n ≥ 3(k+1): with k = 4 the global minimum is 15.
    assert nr.classify_micronumerosidade(15, 4, {"frente": 15})["n_minimum"] == 15


def test_micronumerosidade_absence_of_counts_is_not_conformity():
    # Absence is not approval: without the per-characteristic counts the
    # pressuposto stays pending and never reports "ok".
    result = nr.classify_micronumerosidade(40, 3, None)
    assert result["status"] == nr.MICRO_PENDING
    assert result["status"] != nr.MICRO_OK


def test_micronumerosidade_without_n_or_k_is_pending_not_a_grade():
    result = nr.classify_micronumerosidade(None, 3, {"frente": 10})
    assert result["status"] == nr.MICRO_PENDING
    assert result["n_minimum"] is None
    assert "grade" not in result


# --- 4. source documents -----------------------------------------------------


@pytest.mark.parametrize("edition", sorted(EXPECTED_SOURCE_EDITIONS))
def test_source_documents_record_sha256_date_edition_and_redistribution(edition):
    doc = nr.SOURCE_DOCUMENTS[edition]

    # The digest identifies the exact file read; only its shape can be asserted
    # here without copying the product's own string as the expectation.
    sha = doc["sha256"]
    assert isinstance(sha, str)
    assert SHA256_RE.match(sha), sha

    consulted_on = doc["consulted_on"]
    assert isinstance(consulted_on, str)
    parsed = _dt.datetime.strptime(consulted_on, "%Y-%m-%d").date()
    assert parsed <= _dt.date.today()

    label = doc["edition_or_version"]
    assert isinstance(label, str) and label.strip()
    # The edition year must appear in the declared edition label.
    assert edition.split(":")[-1] in label

    restriction = doc["redistribution"]
    assert isinstance(restriction, str) and restriction.strip()
    assert "proibida" in restriction.lower()


def test_source_documents_cover_both_parts_and_nothing_else():
    assert set(nr.SOURCE_DOCUMENTS) == set(EXPECTED_SOURCE_EDITIONS)


@pytest.mark.parametrize("edition", sorted(EXPECTED_SOURCE_EDITIONS))
def test_no_source_claims_confirmed_currency(edition):
    status = nr.SOURCE_DOCUMENTS[edition]["currency_status"]
    assert isinstance(status, str) and status.strip()
    lowered = status.lower()
    # The ABNT catalogue could not be consulted, so currency is unconfirmed and
    # no record may assert that the edition is "vigente"/current/confirmed.
    assert "unconfirmed" in lowered
    assert "vigente" not in lowered
    assert "current" not in lowered
    assert "em_vigor" not in lowered


# --- 5. literal vs. interpreted thresholds -----------------------------------


@pytest.mark.parametrize("key", sorted(EXPECTED_THRESHOLD_KEYS))
def test_every_record_declares_literal_and_justifies_any_interpretation(key):
    record = nr.THRESHOLD_PROVENANCE[key]
    literal = record["literal"]
    assert isinstance(literal, bool)
    if literal is False:
        assert record["interpretation_id"].strip()
        justification = record["detail"]
        assert isinstance(justification, str) and justification.strip()
        assert "Justificativa" in justification or "justificativa" in justification
        assert isinstance(record["alternative_reading"], dict)
        assert record["alternative_reading"]


def test_measure_upper_factor_is_declared_as_an_interpretation():
    record = nr.THRESHOLD_PROVENANCE["MEASURE_UPPER_FACTOR"]
    assert record["literal"] is False
    assert record["interpretation_id"] == "item4a.upper_factor"
    alternative = record["alternative_reading"]
    # The competing reading of "superiores a 100% do limite superior" is 1,0×.
    assert alternative["factor"] == pytest.approx(1.0)
    assert nr.MEASURE_UPPER_FACTOR_ALTERNATIVE == pytest.approx(1.0)
    assert record["clause"].startswith("Tabela 1 item 4")


def test_measure_lower_factor_is_literal_with_no_alternative_reading():
    record = nr.THRESHOLD_PROVENANCE["MEASURE_LOWER_FACTOR"]
    assert record["literal"] is True
    assert "alternative_reading" not in record
    assert "interpretation_id" not in record


def test_measure_upper_factor_is_the_only_interpreted_threshold():
    interpreted = sorted(
        key
        for key, record in nr.THRESHOLD_PROVENANCE.items()
        if record["literal"] is False
    )
    assert interpreted == ["MEASURE_UPPER_FACTOR"]


# --- 6. cross-edition dangling reference -------------------------------------


def test_cross_edition_notes_record_the_campo_arbitrio_dangling_reference():
    notes = {note["id"]: note for note in nr.CROSS_EDITION_NOTES}
    note = notes["campo_arbitrio.cross_edition"]
    # Parte 2:2011 8.2.1.5.1 quantifies ±15% but cites Parte 1:2001 3.8, an
    # edition superseded by Parte 1:2019, whose 3.1.9 omits the amplitude.
    assert "8.2.1.5.1" in note["clauses"]
    assert "3.1.9" in note["clauses"] or "3.1.9" in note["detail"]
    assert "2001" in note["detail"]
    assert "15" in note["detail"]
    assert "2011" in note["detail"]


# --- 7. no threshold is sourced from a README --------------------------------


def test_no_provenance_string_mentions_a_readme():
    haystacks = {
        "THRESHOLD_PROVENANCE": nr.THRESHOLD_PROVENANCE,
        "SOURCE_DOCUMENTS": nr.SOURCE_DOCUMENTS,
        "CROSS_EDITION_NOTES": nr.CROSS_EDITION_NOTES,
    }
    for name, haystack in haystacks.items():
        for text in _iter_strings(haystack):
            assert "README" not in text, f"{name}: {text!r}"
            assert "readme" not in text, f"{name}: {text!r}"
