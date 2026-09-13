"""Contratos de teste rotulados (simuladores de pares). Não são evidência de integração real."""

PREVIEW_BAIRRO_FORMATTED = {
    "schema_version": "MP/1",
    "input_sha256": "test-preview-bairro",
    "column_map": {
        "preco": {
            "original_name": "preço",
            "kind": "numeric",
            "unit": None,
            "role_suggestion": "target",
            "sample_raw": ["450.000,00"],
            "sample_interpreted": [450000.0],
        },
        "bairro": {
            "original_name": "bairro",
            "kind": "categorical",
            "unit": None,
            "role_suggestion": "predictor",
            "categories": ["Centro", "Norte"],
            "reference_category": "Centro",
            "sample_raw": ["Centro", "Norte"],
            "sample_interpreted": ["Centro", "Norte"],
        },
        "area": {
            "original_name": "área",
            "kind": "numeric",
            "unit": "m2",
            "sample_raw": ["1.234,56"],
            "sample_interpreted": [1234.56],
        },
        "informante": {
            "original_name": "informante",
            "kind": "text",
            "sample_raw": ["Fulano de Tal"],
            "sample_interpreted": ["Fulano de Tal"],
        },
    },
    "feature_schema": {
        "version": 1,
        "columns": {
            "preco": {
                "original_name": "preço",
                "role": "target",
                "kind": "numeric",
                "unit": None,
                "group_id": None,
                "categories": None,
                "reference_category": None,
            },
            "bairro": {
                "original_name": "bairro",
                "role": "predictor",
                "kind": "categorical",
                "unit": None,
                "group_id": "bairro",
                "categories": ["Centro", "Norte"],
                "reference_category": "Centro",
            },
            "area": {
                "original_name": "área",
                "role": "predictor",
                "kind": "numeric",
                "unit": "m2",
                "group_id": None,
                "categories": None,
                "reference_category": None,
            },
            "informante": {
                "original_name": "informante",
                "role": "identifier",
                "kind": "text",
                "unit": None,
                "group_id": None,
                "categories": None,
                "reference_category": None,
            },
        },
        "groups": {
            "bairro": {
                "columns": ["bairro_Centro", "bairro_Norte"],
                "base_variable": "bairro",
            }
        },
        "target": {"column": "preco", "unit": ""},
    },
    "issues": [
        {
            "code": "unit_unknown",
            "severity": "warning",
            "origin": "preview",
            "message": "Unidade do preço não declarada na planilha.",
            "affected_ids": ["preco"],
            "evidence": {},
        }
    ],
}


def _base_snapshot(**overrides):
    snap = {
        "schema_version": "MP/1",
        "job_id": "job-test",
        "project_id": None,
        "input_sha256": "abc",
        "code_sha": "def",
        "reference_date": None,
        "generated_at": "2024-03-02T12:00:00Z",
        "target": {"column": "preco", "unit": None, "estimand": None},
        "value": {
            "point": None,
            "mean_ci80": None,
            "prediction_interval": None,
            "arbitration_interval": None,
            "admissible_interval": None,
        },
        "sample": {
            "received": 10,
            "observed_target": 9,
            "prepared": 8,
            "used": 8,
            "excluded": 2,
            "used_row_ids": ["r1", "r2"],
            "excluded_row_ids": ["r9", "r10"],
        },
        "validation": {
            "fundamentacao": {"grade": None, "points": None, "items": []},
            "precisao": {"status": "not_computed", "grade": None, "amplitude_pct": None},
            "statistical": {},
            "documentary": {},
            "issuance": {"status": "draft", "reasons": ["Cálculo incompleto."]},
            "is_valid": True,
        },
        "issues": [
            {
                "code": "value_not_computed",
                "severity": "warning",
                "origin": "c10",
                "message": "Ponto do valor não calculado.",
                "affected_ids": [],
                "evidence": {},
            }
        ],
        "model": {"coefficients": {"área": 1.2}, "diagnostics": {"n": 8}},
        "search": {"evaluated": 3},
        "alternatives": [{"candidate_id": "alt-1"}],
        "next_actions": [
            {
                "code": "supply_subject",
                "priority": "high",
                "reason": "Sem avaliando não há precisão.",
                "next_step": "Informar o avaliando e recalcular.",
                "evidence_refs": ["sample.used"],
                "limitations": "A recomendação não substitui revisão profissional.",
            }
        ],
        "provenance": {},
    }
    snap.update(overrides)
    return snap


SNAPSHOT_NOT_COMPUTED = _base_snapshot()

SNAPSHOT_CLASSIFIED = _base_snapshot(
    reference_date="2024-01-15",
    target={"column": "preco", "unit": "BRL", "estimand": "valor de mercado"},
    value={
        "point": 250000.5,
        "mean_ci80": {"lower": 240000.0, "upper": 260000.0},
        "prediction_interval": {"lower": 200000.0, "upper": 300000.0},
        "arbitration_interval": None,
        "admissible_interval": {"lower": 220000.0, "upper": 280000.0},
    },
    validation={
        "fundamentacao": {"grade": 2, "points": 10, "items": [{"id": "t1i1"}]},
        "precisao": {"status": "classified", "grade": 2, "amplitude_pct": 16.0},
        "statistical": {"r2": 0.81},
        "documentary": {},
        "issuance": {"status": "ready_for_professional_review", "reasons": []},
        "is_valid": True,
    },
    issues=[
        {
            "code": "sample_note",
            "severity": "info",
            "origin": "c10",
            "message": "Dois registros excluídos com justificativa.",
            "affected_ids": ["r9"],
            "evidence": {},
        }
    ],
)

SNAPSHOT_UNCLASSIFIED = _base_snapshot(
    target={"column": "preco", "unit": "BRL", "estimand": "valor de mercado"},
    value={
        "point": 180000.0,
        "mean_ci80": {"lower": 100000.0, "upper": 260000.0},
        "prediction_interval": None,
        "arbitration_interval": None,
        "admissible_interval": None,
    },
    validation={
        "fundamentacao": {"grade": 1, "points": 6, "items": []},
        "precisao": {"status": "unclassified", "grade": None, "amplitude_pct": 80.0},
        "statistical": {},
        "documentary": {},
        "issuance": {"status": "review_required", "reasons": ["Amplitude fora da tabela."]},
        "is_valid": False,
    },
)

SNAPSHOT_ERROR = _base_snapshot(
    value={"point": None, "mean_ci80": None, "prediction_interval": None, "arbitration_interval": None, "admissible_interval": None},
    validation={
        "fundamentacao": {"grade": None, "points": None, "items": []},
        "precisao": {"status": "error", "grade": None, "amplitude_pct": None},
        "statistical": {},
        "documentary": {},
        "issuance": {"status": "draft", "reasons": ["Falha no cálculo da precisão."]},
        "is_valid": False,
    },
    issues=[
        {
            "code": "precision_error",
            "severity": "error",
            "origin": "c03",
            "message": "Não foi possível calcular a precisão.",
            "affected_ids": [],
            "evidence": {},
        }
    ],
)


def long_table_snapshot(n_rows: int = 200):
    snap = _base_snapshot()
    snap["sample"]["used_row_ids"] = [f"r{i}" for i in range(n_rows)]
    snap["sample"]["used"] = n_rows
    snap["issues"] = [
        {
            "code": "long_table_warning",
            "severity": "warning",
            "origin": "c09",
            "message": "Amostra longa: conferir exclusões.",
            "affected_ids": [],
            "evidence": {},
        }
    ]
    return snap
