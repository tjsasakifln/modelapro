"""CONTRACT-SIM: fixtures vs the frozen MP/1 RequestSpec shape.

These tests do NOT call production APIs and MUST NOT be counted as E2E
integration evidence. They only lock the corpus to the contract text so
C17 can compose later.
"""
from __future__ import annotations

from _helpers import load_request_specs

KIND = "contract-sim"

REQUIRED_KEYS = {
    "schema_version", "target_col", "candidate_cols", "roles", "units",
    "import_options", "missing_policy", "outlier_policy", "search_policy",
    "evaluation_policy", "reference_date", "inspection_date", "target_unit",
    "applicant", "purpose",
}


def test_contract_sim_minimal_auto_shape():
    specs = load_request_specs()
    spec = specs["minimal_auto"]
    missing = REQUIRED_KEYS - set(spec)
    assert not missing
    assert spec["schema_version"] == "MP/1"
    assert spec["candidate_cols"] is None  # explicit auto-by-role
    assert spec["missing_policy"]["target"] == "never_impute"
    assert spec["outlier_policy"]["mode"] == "report_only"
    assert spec["reference_date"] is None
    assert spec["target_unit"] == ""


def test_contract_sim_empty_selection_is_empty_list_not_null():
    spec = load_request_specs()["empty_selection"]
    assert spec["candidate_cols"] == []
    assert spec["candidate_cols"] is not None


def test_contract_sim_locales_are_explicit():
    specs = load_request_specs()
    assert specs["pt_br"]["import_options"]["locale"] == "pt-BR"
    assert specs["en_us"]["import_options"]["locale"] == "en-US"
    assert specs["pt_br"]["candidate_cols"] != []
