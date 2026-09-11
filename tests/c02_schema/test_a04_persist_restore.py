"""C02-A04: JSON persist/restore of schema+encoder reproduces SubjectDesign.X."""

from __future__ import annotations

import json

import pandas as pd

from modules.preprocessing import fit_dataset, transform_subject
from modules.variable_schema import dumps_encoder_artifacts, loads_encoder_artifacts

from .fixtures import a01_rows, mp1_bundle, mp1_request_spec


def test_a04_json_roundtrip_reproduces_subject_x():
    prepared = fit_dataset(mp1_bundle(a01_rows()), mp1_request_spec())
    subject_raw = {"bairro": "Norte", "area": "1.234,56"}

    first = transform_subject(subject_raw, prepared.feature_schema, prepared.encoder_state)

    payload = dumps_encoder_artifacts(prepared.feature_schema, prepared.encoder_state)
    json.loads(payload)  # stdlib mapping path; no DataFrame
    assert "DataFrame" not in payload
    restored_schema, restored_state = loads_encoder_artifacts(payload)

    second = transform_subject(subject_raw, restored_schema, restored_state)

    assert list(second.X.columns) == list(first.X.columns)
    assert list(second.X.columns) == list(prepared.X.columns)
    pd.testing.assert_frame_equal(first.X, second.X, check_exact=True)
    assert first.supported is True
    assert second.supported is True
    assert second.X.iloc[0]["area"] == 1234.56
