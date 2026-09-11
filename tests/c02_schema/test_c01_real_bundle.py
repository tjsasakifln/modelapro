"""C01-real InputBundle path. Distinct from synthetic MP/1 fixtures.

Skipped until C01 publishes ingest_market on this tree. Not evidence of
end-to-end integration.
"""

from __future__ import annotations

import pandas as pd
import pytest

from modules.preprocessing import fit_dataset

from .fixtures import mp1_request_spec


def test_c01_ingest_market_bundle_when_published():
    try:
        from modules.data_loader import ingest_market
    except ImportError:
        pytest.skip("C01 ingest_market not published on this tree")
    if ingest_market is None:
        pytest.skip("C01 ingest_market not published on this tree")

    csv = (
        "bairro,area,valor,id_imovel\n"
        "Centro,80,100000,A1\n"
        "Centro,90,110000,A2\n"
        "Norte,100,120000,A3\n"
        "Sul,110,130000,A4\n"
        "Sul,120,140000,A5\n"
    ).encode("utf-8")
    spec = mp1_request_spec()
    bundle = ingest_market(csv, "synthetic.csv", spec)
    assert bundle["schema_version"] == "MP/1"
    prepared = fit_dataset(bundle, spec)
    assert isinstance(prepared.X, pd.DataFrame)
    assert "bairro" in prepared.feature_schema["groups"]
    assert prepared.sample_ledger["used"] >= 1
