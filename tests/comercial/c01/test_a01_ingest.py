"""C01-A01: ingest integrity. Drives ingest_market / fit_dataset, not a reimplemented parser."""

from __future__ import annotations

import pandas as pd
import pytest

from modules.data_loader import ingest_market
from modules.preprocessing import fit_dataset
from tests.c01_input.conftest import make_request_spec


def _codes(bundle) -> set:
    return {item["code"] for item in bundle.issues}


def test_missing_price_stays_missing_and_raw_frame_intact():
    csv = "id,preco,area\nA,,50\nB,800000,80\n".encode("utf-8")
    spec = make_request_spec("preco", roles={"id": "identifier"})
    bundle = ingest_market(csv, "missing.csv", spec)
    assert pd.isna(bundle.parsed_frame.iloc[0]["preco"])
    raw_first = bundle.raw_frame.iloc[0]["preco"]
    assert raw_first == "" or pd.isna(raw_first)
    assert 700000 not in list(bundle.parsed_frame["preco"])
    pending = [e for e in bundle.row_ledger if not e["observed_target"]]
    assert len(pending) == 1
    assert pending[0]["disposition"] == "pending_target"
    assert pending[0]["row_id"] == bundle.parsed_frame.iloc[0]["row_id"]
    assert bundle.row_ledger[0]["stage"] in {"received", "interpreted"}


def test_ambiguous_dot_in_auto_locale_is_not_1234():
    csv = "preco,area\n1.234,50\n".encode("utf-8")
    bundle = ingest_market(csv, "amb.csv", make_request_spec("preco", locale="auto"))
    value = bundle.parsed_frame.iloc[0]["preco"]
    assert value != 1234 and value != 1234.0
    assert "ambiguous_number" in _codes(bundle)


def test_duplicate_identifier_keeps_both_row_ids():
    csv = "id,preco,area\nX,100,10\nX,200,20\n".encode("utf-8")
    spec = make_request_spec("preco", roles={"id": "identifier"})
    bundle = ingest_market(csv, "dup.csv", spec)
    assert "duplicate_identifier" in _codes(bundle)
    ids = [e["row_id"] for e in bundle.row_ledger]
    assert len(ids) == 2
    assert ids[0] != ids[1]
    assert len(bundle.raw_frame) == 2


def test_offer_and_transaction_are_not_collapsed():
    csv = (
        "id,natureza,preco,area\n"
        "1,oferta,100000,50\n"
        "2,transacao,110000,52\n"
    ).encode("utf-8")
    spec = make_request_spec(
        "preco",
        roles={"id": "identifier", "natureza": "source"},
    )
    bundle = ingest_market(csv, "kinds.csv", spec)
    kinds = {e["observation_kind"] for e in bundle.row_ledger}
    assert "offer" in kinds
    assert "transaction" in kinds
    assert "offer_and_transaction_present" in _codes(bundle)
    assert len(bundle.row_ledger) == 2


def test_ambiguous_area_basis_is_refused():
    csv = "preco,area_privativa,area_total\n100000,50,70\n".encode("utf-8")
    bundle = ingest_market(csv, "areas.csv", make_request_spec("preco"))
    assert "ambiguous_area_basis" in _codes(bundle)
    assert any(i["severity"] == "error" for i in bundle.issues if i["code"] == "ambiguous_area_basis")


def test_ledger_distinguishes_received_observed_prepared_used():
    csv = "id,preco,area,bairro\nA,100000,50,Centro\nB,,60,Sul\nC,120000,70,Centro\n".encode("utf-8")
    spec = make_request_spec(
        "preco",
        candidate_cols=["area", "bairro"],
        roles={"id": "identifier", "area": "predictor", "bairro": "predictor"},
    )
    bundle = ingest_market(csv, "ledger.csv", spec)
    prepared = fit_dataset(bundle, spec, None)
    ledger = prepared["sample_ledger"]
    assert ledger["received"] == 3
    assert ledger["observed_target"] == 2
    assert ledger["used"] == 2
    assert ledger["excluded"] >= 1
    assert bundle.raw_frame.shape[0] == 3
    lineage = (prepared["feature_schema"] or {}).get("feature_lineage") or []
    assert lineage
    sources = {item["source_columns"][0] for item in lineage}
    assert "area" in sources or any("area" in item["feature"] for item in lineage)
