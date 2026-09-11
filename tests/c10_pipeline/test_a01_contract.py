"""C10-A01: RequestSpec / ResultSnapshot validation and strict JSON freeze."""

import json
import math

import pandas as pd
import pytest

from modules.result_contract import (
    SCHEMA_VERSION,
    RequestSpecError,
    ResultSnapshotError,
    dumps_strict,
    freeze_result_snapshot,
    make_issue,
    validate_request_spec,
)
from modules.results import (
    ValidationResult,
    adapt_validation_result,
    value_block_from_legacy_validation,
)
from tests.c10_pipeline.fixtures import complete_request_spec, complete_snapshot


def test_valid_request_spec_roundtrip():
    spec = validate_request_spec(complete_request_spec())
    assert spec["schema_version"] == SCHEMA_VERSION
    assert spec["candidate_cols"] == ["area", "bairro"]
    assert spec["roles"]["preco"] == "target"
    assert spec["missing_policy"]["target"] == "never_impute"
    assert spec["reference_date"] == "2024-06-01"
    # Empty unit stays pending; BRL was not assumed.
    assert spec["target_unit"] == ""
    dumped = dumps_strict({k: v for k, v in spec.items() if not str(k).startswith("_")})
    json.loads(dumped)


def test_candidate_cols_null_is_explicit_auto_by_role():
    spec = validate_request_spec(complete_request_spec(candidate_cols=None))
    assert spec["candidate_cols"] is None


def test_candidate_cols_empty_list_is_error():
    with pytest.raises(RequestSpecError) as exc:
        validate_request_spec(complete_request_spec(candidate_cols=[]))
    codes = {i["code"] for i in exc.value.issues}
    assert "CANDIDATE_COLS_EMPTY" in codes


def test_missing_declared_policies_rejected():
    payload = complete_request_spec()
    del payload["missing_policy"]
    with pytest.raises(RequestSpecError) as exc:
        validate_request_spec(payload)
    assert any(i["code"] == "MISSING_FIELD" for i in exc.value.issues)

    payload = complete_request_spec()
    payload["search_policy"] = {"mode": "x"}
    with pytest.raises(RequestSpecError) as exc:
        validate_request_spec(payload)
    assert any(i["code"] == "SEARCH_POLICY_REQUIRED" for i in exc.value.issues)


def test_target_imputation_forbidden():
    payload = complete_request_spec()
    payload["missing_policy"] = {"target": "mean", "predictors": "complete_case"}
    with pytest.raises(RequestSpecError) as exc:
        validate_request_spec(payload)
    assert any(i["code"] == "TARGET_IMPUTATION_FORBIDDEN" for i in exc.value.issues)


def test_invalid_date_and_degree_rejected():
    with pytest.raises(RequestSpecError) as exc:
        validate_request_spec(complete_request_spec(reference_date="01/06/2024"))
    assert any(i["code"] == "INVALID_DATE" for i in exc.value.issues)

    payload = complete_request_spec()
    payload["search_policy"] = {
        **payload["search_policy"],
        "target_degree": 9,
    }
    with pytest.raises(RequestSpecError) as exc:
        validate_request_spec(payload)
    assert any(i["code"] == "DEGREE_OUT_OF_RANGE" for i in exc.value.issues)


def test_roles_must_declare_target_before_cleaning():
    payload = complete_request_spec()
    payload["roles"] = {"area": "predictor"}
    with pytest.raises(RequestSpecError) as exc:
        validate_request_spec(payload)
    assert any(i["code"] == "TARGET_ROLE_MISSING" for i in exc.value.issues)


def test_documented_outlier_default_applied():
    payload = complete_request_spec()
    del payload["outlier_policy"]
    spec = validate_request_spec(payload)
    assert spec["outlier_policy"]["mode"] == "report_only"
    assert any(i["code"] == "DEFAULT_APPLIED" for i in spec["_applied_defaults"])


def test_freeze_valid_snapshot_is_strict_json():
    frozen = freeze_result_snapshot(complete_snapshot())
    assert frozen["schema_version"] == SCHEMA_VERSION
    text = dumps_strict(frozen)
    assert "NaN" not in text
    assert "Infinity" not in text
    parsed = json.loads(text)
    assert parsed["value"]["point"] == 150000.0
    # Artifacts must not be folded into the frozen snapshot.
    assert "report_pdf_base64" not in parsed
    assert "artifact_states" not in parsed


def test_non_finite_point_becomes_null_plus_issue_not_zero():
    snap = complete_snapshot()
    snap["value"]["point"] = float("nan")
    frozen = freeze_result_snapshot(snap)
    assert frozen["value"]["point"] is None
    assert frozen["value"]["point"] != 0
    assert any(i["code"] == "NON_FINITE_NUMBER" for i in frozen["issues"])
    dumps_strict(frozen)


def test_pandas_object_becomes_null_plus_issue():
    snap = complete_snapshot()
    snap["model"]["frame"] = pd.DataFrame({"a": [1, 2]})
    frozen = freeze_result_snapshot(snap)
    assert frozen["model"]["frame"] is None
    assert any(i["code"] == "NON_JSON_VALUE" for i in frozen["issues"])
    dumps_strict(frozen)


def test_point_is_not_rebuilt_from_arbitration_interval():
    snap = complete_snapshot()
    snap["value"]["point"] = None
    snap["value"]["arbitration_interval"] = {"lower": 80.0, "upper": 120.0}
    frozen = freeze_result_snapshot(snap)
    assert frozen["value"]["point"] is None
    assert frozen["value"]["arbitration_interval"]["lower"] == 80.0
    # Midpoint of the arbitration band would be 100; freeze must not invent it.
    assert frozen["value"]["point"] != 100


def test_infinity_in_interval_nulls_interval_not_success_flag():
    snap = complete_snapshot()
    snap["value"]["mean_ci80"] = {"lower": 1.0, "upper": math.inf}
    frozen = freeze_result_snapshot(snap)
    assert frozen["value"]["mean_ci80"] is None
    assert any(i["code"] == "NON_FINITE_NUMBER" for i in frozen["issues"])
    assert frozen["validation"]["issuance"]["status"] == "draft"
    dumps_strict(frozen)


def test_missing_required_snapshot_keys_rejected():
    snap = complete_snapshot()
    del snap["job_id"]
    with pytest.raises(ResultSnapshotError):
        freeze_result_snapshot(snap)


def test_legacy_validation_adapter_does_not_approve_laudo():
    vr = ValidationResult(
        success=True,
        is_valid=True,
        grau_fundamentacao=3,
        grau_fundamentacao_pontos=16,
        grau_precisao=2,
        valores_admissiveis_inferior=90.0,
        valores_admissiveis_superior=110.0,
    )
    mapped = adapt_validation_result(vr)
    assert mapped["issuance"]["status"] in {"draft", "review_required"}
    assert mapped["issuance"]["status"] != "ready_for_professional_review" or "no_automatic_report_approval" in mapped["issuance"]["reasons"]
    assert "no_automatic_report_approval" in mapped["issuance"]["reasons"]
    assert mapped["documentary"]["verified"] is False
    block = value_block_from_legacy_validation(vr, point=None)
    assert block["point"] is None
    assert block["admissible_interval"]["lower"] == 90.0


def test_make_issue_shape():
    issue = make_issue("X", "msg", affected_ids=["r1"], evidence={"k": 1})
    assert issue["severity"] == "error"
    assert issue["affected_ids"] == ["r1"]
    dumps_strict(issue)
