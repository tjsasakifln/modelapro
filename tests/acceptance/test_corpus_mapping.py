"""C16-A01: mapping F01–F16 is loadable and complete; fixtures are synthetic."""
from __future__ import annotations

from _helpers import INDEPENDENT, load_mapping, oracles


REQUIRED_FINDINGS = [f"F{i:02d}" for i in range(1, 17)]
REQUIRED_CASE_KEYS = {
    "id", "cenario", "achado", "observacao_esperada", "criterio", "proprietario",
}


def test_mapping_covers_f01_through_f16_once():
    mapping = load_mapping()
    assert mapping["synthetic_only"] is True
    assert mapping["contract_version"] == "MP/1"
    findings = [c["achado"] for c in mapping["cases"]]
    assert findings == REQUIRED_FINDINGS
    for case in mapping["cases"]:
        missing = REQUIRED_CASE_KEYS - set(case)
        assert not missing, f"{case.get('id')} missing {missing}"
        assert "cliente" not in case["cenario"].lower()
        assert "oracles.py" in mapping["oracle_policy"] or "invariant" in mapping["oracle_policy"].lower()


def test_f01_fixture_independent_n_is_25_of_30():
    counts = oracles.f01_independent_n()
    assert counts["received"] == 30
    assert counts["observed_target"] == 25
    mean = oracles.f01_observed_mean_preco()
    # Independent: observed areas 55,60,...,195 except 75,100,125,150
    # preco = 1000 * area when present.
    assert mean == 127000.0


def test_locale_oracles_are_independent_literals():
    assert oracles.parse_number("R$ 1.234,56", "pt-BR") == 1234.56
    assert oracles.parse_number("1,234.56", "en-US") == 1234.56
    assert oracles.parse_number("2.000,00", "pt-BR") == 2000.0
    assert oracles.parse_number("2,000.00", "en-US") == 2000.0
    assert oracles.is_ambiguous_number("1.234") is True
    assert oracles.is_ambiguous_number("1,234") is True
    assert oracles.is_ambiguous_number("1.234,56") is False


def test_sqrt_oracle_zero():
    assert oracles.math_sqrt(0.0) == 0.0
    assert oracles.math_sqrt(4.0) == 2.0


def test_extrapolation_oracles_are_distinct():
    assert oracles.faixa_ampliada(90, 50, 100) == "in_sample"
    assert oracles.faixa_ampliada(150, 50, 100) == "extended"
    assert oracles.faixa_ampliada(250, 50, 100) == "outside_extended"
    assert oracles.efeito_monetario(90000, 50000, 100000) == "price_in_sample"
    assert oracles.efeito_monetario(150000, 50000, 100000) == "price_outside_sample"
    # Same subject can be extended-faixa AND outside-price — two outcomes.
    faixa = oracles.faixa_ampliada(150, 50, 100)
    efeito = oracles.efeito_monetario(oracles.linear_price(150), 50000, 100000)
    assert faixa == "extended"
    assert efeito == "price_outside_sample"
    assert faixa != efeito


def test_fixtures_directory_has_no_client_tokens():
    forbidden = ("cpf", "cnpj", "rg:", "cliente real", "telefone")
    for path in INDEPENDENT.rglob("*"):
        if path.suffix.lower() not in {".csv", ".json", ".md", ".py"}:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in text, f"{path} contains {token}"
