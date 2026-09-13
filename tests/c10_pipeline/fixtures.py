"""Shared MP/1 fixtures for C10 tests. Synthetic data, identified as such."""

from copy import deepcopy

from modules.result_contract import SCHEMA_VERSION, empty_value_block


def complete_request_spec(**overrides):
    spec = {
        "schema_version": SCHEMA_VERSION,
        "target_col": "preco",
        "candidate_cols": ["area", "bairro"],
        "roles": {
            "preco": "target",
            "area": "predictor",
            "bairro": "predictor",
            "id": "identifier",
        },
        "units": {"preco": "", "area": "m2"},
        "import_options": {"locale": "auto", "delimiter": ",", "encoding": "utf-8"},
        "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
        "outlier_policy": {"mode": "report_only", "reviewed_exclusions": []},
        "search_policy": {
            "mode": "exhaustive",
            "budget": 32,
            "objective": "aic",
            "seed": 7,
            "target_degree": 2,
        },
        "evaluation_policy": {
            "method": "none",
            "partitions": None,
            "groups": None,
            "seed": 7,
        },
        "reference_date": "2024-06-01",
        "inspection_date": "2024-06-15",
        "target_unit": "",
        "applicant": "Sintetico C10",
        "purpose": "teste de contrato",
    }
    spec.update(overrides)
    return spec


def complete_snapshot(**overrides):
    value = empty_value_block()
    value["point"] = 150000.0
    value["mean_ci80"] = {"lower": 140000.0, "upper": 160000.0}
    value["arbitration_interval"] = {"lower": 127500.0, "upper": 172500.0}
    snap = {
        "schema_version": SCHEMA_VERSION,
        "job_id": "job-c10-synthetic",
        "project_id": None,
        "input_sha256": "a" * 64,
        "code_sha": "b" * 40,
        "reference_date": "2024-06-01",
        "generated_at": "2024-06-15T12:00:00+00:00",
        "target": {
            "column": "preco",
            "unit": "",
            "estimand": "subject_prediction",
        },
        "value": value,
        "sample": {
            "received": 4,
            "observed_target": 4,
            "prepared": 4,
            "used": 4,
            "excluded": 0,
            "used_row_ids": ["r1", "r2", "r3", "r4"],
            "excluded_row_ids": [],
        },
        "validation": {
            "fundamentacao": {"grade": 2, "points": 8, "items": []},
            "precisao": {"status": "classified", "grade": 2, "amplitude_pct": 12.5},
            "statistical": {},
            "documentary": {"status": "declared", "verified": False},
            "issuance": {
                "status": "draft",
                "reasons": ["no_automatic_report_approval"],
            },
        },
        "issues": [],
        "model": {
            "candidate_id": "cand-1",
            "model_sha256": "c" * 64,
            "delivered_matches_used": True,
        },
        "search": {"audit": {"generated": 3, "evaluated": 3, "rejected": 0}},
        "alternatives": [],
        "next_actions": [],
        "provenance": {"composed_by": "c10.tests", "synthetic": True},
    }
    snap.update(overrides)
    return deepcopy(snap)


def market_csv_bytes(tag: str = "A") -> bytes:
    """Tiny synthetic market extract. `tag` changes bytes without changing schema."""
    return (
        "id,bairro,area,preco\n"
        f"1,centro,80,100000\n"
        f"2,sul,90,110000\n"
        f"3,centro,100,125000\n"
        f"4,norte,70,95000\n"
        f"#synthetic={tag}\n"
    ).encode("utf-8")


def subject_raw(bairro: str = "centro", area: float = 85.0) -> dict:
    return {"bairro": bairro, "area": area}
