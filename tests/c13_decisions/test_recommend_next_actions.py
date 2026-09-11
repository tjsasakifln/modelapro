"""Aceite C13: recommend_next_actions sobre snapshots MP/1 (completos e parciais).

Os testes chamam a função publicada. O déficit de A01 é derivado no próprio
teste como 6*(k+1)-n; não se relê a implementação para obter o esperado.
"""

from __future__ import annotations

import copy
import inspect
import re
from typing import Any, Dict, List, Mapping

import pytest

from modules.decision_support import recommend_next_actions

ACTION_KEYS = ("code", "priority", "reason", "next_step", "evidence_refs", "limitations")

# Códigos estáveis do contrato C13 — literais do aceite, não lidos do módulo.
CODE_SAMPLE = "improve_sample_support"
CODE_IMPUTED_PRICE = "resolve_imputed_or_ambiguous_price"
CODE_FIT_QUALITY = "improve_fit_quality"
CODE_INFLUENTIAL = "review_influential_point"
CODE_PRECISION_NOT_COMPUTED = "precision_not_computed"
CODE_PRECISION_UNCLASSIFIED = "precision_unclassified"
CODE_DOCUMENT_SOURCE = "document_source"
CODE_ARTIFACT = "recover_failed_artifact"
CODE_UNIT_PARSE = "resolve_unit_or_parse"
CODE_SENSITIVITY = "review_value_sensitivity"
CODE_INCOMPATIBLE_ALT = "incompatible_alternative_comparison"

INVENTED_IMPACT = re.compile(
    r"(ganho|impacto|melhoria|aumentaria|elevaria).{0,24}\d+([.,]\d+)?\s*%",
    re.IGNORECASE,
)
REMOVAL_RECOMMENDATION = re.compile(
    r"(remover|excluir)\s+(automaticamente\s+)?(o\s+)?(ponto|observa[cç][aã]o|dado|registro)",
    re.IGNORECASE,
)
FORBIDDEN_FABRICATION = re.compile(
    r"(dados aleat[oó]rios|recodificar vari[aá]vel|ajustar um pre[cç]o|"
    r"fabricar (grau|r²|r2))",
    re.IGNORECASE,
)


def _base_snapshot(**overrides: Any) -> Dict[str, Any]:
    snap: Dict[str, Any] = {
        "schema_version": "MP/1",
        "job_id": "job-c13-test",
        "project_id": None,
        "input_sha256": "abc",
        "code_sha": "def",
        "reference_date": "2024-06-01",
        "generated_at": "2024-06-02T00:00:00Z",
        "target": {"column": "preco", "unit": "BRL", "estimand": "mean"},
        "value": {
            "point": 100000.0,
            "mean_ci80": {"lower": 90000.0, "upper": 110000.0},
            "prediction_interval": None,
            "arbitration_interval": None,
            "admissible_interval": None,
        },
        "sample": {
            "received": 26,
            "observed_target": 26,
            "prepared": 26,
            "used": 26,
            "excluded": 0,
            "used_row_ids": [f"r{i}" for i in range(26)],
            "excluded_row_ids": [],
        },
        "validation": {
            "fundamentacao": {"grade": 2, "points": 12, "items": []},
            "precisao": {"status": "classified", "grade": 2, "amplitude_pct": 35.0},
            "statistical": {},
            "documentary": {"status": "verified", "items": []},
            "issuance": {"status": "review_required", "reasons": []},
        },
        "issues": [],
        "model": {"k": 4, "candidate_id": "ols-1"},
        "search": {},
        "alternatives": [],
        "next_actions": [],
        "provenance": {},
    }
    snap.update(overrides)
    return snap


def _assert_action_shape(action: Mapping[str, Any]) -> None:
    assert set(ACTION_KEYS) <= set(action.keys())
    assert isinstance(action["code"], str) and action["code"]
    assert isinstance(action["priority"], int)
    assert isinstance(action["reason"], str) and action["reason"].strip()
    assert isinstance(action["next_step"], str) and action["next_step"].strip()
    assert isinstance(action["evidence_refs"], list)
    assert isinstance(action["limitations"], list)


def _blob(action: Mapping[str, Any]) -> str:
    return " ".join(
        [
            action.get("reason", ""),
            action.get("next_step", ""),
            " ".join(str(x) for x in action.get("limitations") or []),
            str(action.get("evidence_refs")),
        ]
    )


def _all_text(actions: List[Mapping[str, Any]]) -> str:
    return " ".join(_blob(a) for a in actions)


def test_empty_and_partial_snapshots_return_action_lists():
    for snap in ({}, {"schema_version": "MP/1"}, {"issues": []}):
        actions = recommend_next_actions(snap)
        assert isinstance(actions, list)
        for action in actions:
            _assert_action_shape(action)


def test_c13_a01_k4_n26_deficit_four_does_not_guarantee_global_grade():
    k = 4
    n = 26
    expected_deficit = 6 * (k + 1) - n
    assert expected_deficit == 4

    snapshot = _base_snapshot(
        sample={
            "received": n,
            "observed_target": n,
            "prepared": n,
            "used": n,
            "excluded": 0,
            "used_row_ids": [f"r{i}" for i in range(n)],
            "excluded_row_ids": [],
        },
        model={"k": k},
        validation={
            "fundamentacao": {
                "grade": 2,
                "points": 12,
                "items": [
                    {
                        "id": "item_2",
                        "item": 2,
                        "description": "Quantidade mínima de dados de mercado",
                        "grade": 2,
                        "evidence_status": "verified",
                        "calculation": {"n": n, "k": k, "rule": "6(k+1)"},
                        "source": "NBR 14653-2:2011 Tabela 1 item 2",
                    }
                ],
            },
            "precisao": {"status": "classified", "grade": 2, "amplitude_pct": 35.0},
            "statistical": {"n": n, "k": k},
            "documentary": {"status": "verified", "items": []},
            "issuance": {"status": "review_required", "reasons": []},
        },
    )
    original = copy.deepcopy(snapshot)

    actions = recommend_next_actions(snapshot)
    assert snapshot == original
    assert isinstance(actions, list) and actions
    for action in actions:
        _assert_action_shape(action)

    sample_actions = [a for a in actions if a["code"] == CODE_SAMPLE]
    assert len(sample_actions) == 1
    text = _blob(sample_actions[0]).lower()
    assert str(expected_deficit) in _blob(sample_actions[0])
    assert "este item" in text
    assert "não garante" in text and "grau global" in text
    assert INVENTED_IMPACT.search(_blob(sample_actions[0])) is None


def test_c13_a01_deficit_not_computed_without_n_k_and_verified_rule():
    snapshot = {
        "schema_version": "MP/1",
        "sample": {"used": 26},
        "validation": {
            "fundamentacao": {
                "items": [
                    {
                        "id": "item_2",
                        "item": 2,
                        "evidence_status": "pending",
                        "calculation": {},
                    }
                ]
            }
        },
        "issues": [
            {
                "code": "SAMPLE_INSUFFICIENT",
                "severity": "warning",
                "origin": "validation",
                "message": "Suporte amostral a conferir",
                "affected_ids": [],
                "evidence": {},
            }
        ],
    }
    actions = recommend_next_actions(snapshot)
    sample_actions = [a for a in actions if a["code"] == CODE_SAMPLE]
    assert len(sample_actions) == 1
    text = _blob(sample_actions[0]).lower()
    assert "déficit de 4" not in text
    assert "deficit de 4" not in text
    assert sample_actions[0]["limitations"]
    assert any(
        "n" in str(lim).lower() and "regra" in str(lim).lower()
        for lim in sample_actions[0]["limitations"]
    )


def test_c13_a02_imputed_price_outranks_r2_and_influence_is_not_removal():
    snapshot = _base_snapshot(
        issues=[
            {
                "code": "IMPUTED_TARGET",
                "severity": "error",
                "origin": "ingest",
                "message": "Preço da variável-alvo foi imputado",
                "affected_ids": ["r3"],
                "evidence": {"column": "preco", "policy": "mean"},
            },
            {
                "code": "LOW_R2",
                "severity": "info",
                "origin": "evaluation",
                "message": "R² ajustado baixo em relação ao uso pretendido",
                "affected_ids": [],
                "evidence": {"r2_adjusted": 0.41},
            },
            {
                "code": "INFLUENTIAL_OBSERVATION",
                "severity": "warning",
                "origin": "fitting",
                "message": "Observação com alta distância de Cook",
                "affected_ids": ["r7"],
                "evidence": {"cooks_distance": 1.4},
            },
        ]
    )
    actions = recommend_next_actions(snapshot)
    for action in actions:
        _assert_action_shape(action)

    imputed = next(a for a in actions if a["code"] == CODE_IMPUTED_PRICE)
    r2 = next(a for a in actions if a["code"] == CODE_FIT_QUALITY)
    influence = next(a for a in actions if a["code"] == CODE_INFLUENTIAL)

    assert imputed["priority"] < r2["priority"]

    inf_text = _blob(influence).lower()
    assert "investig" in inf_text or "revis" in inf_text
    assert REMOVAL_RECOMMENDATION.search(inf_text) is None
    assert "não remover automaticamente" in inf_text or "nao remover automaticamente" in inf_text
    assert not any("remove" in a["code"] for a in actions)

    combined = _all_text(actions)
    assert FORBIDDEN_FABRICATION.search(combined) is None
    assert INVENTED_IMPACT.search(combined) is None


def test_c13_a03_four_distinct_codes_for_pending_kinds():
    snap_not_computed = {
        "schema_version": "MP/1",
        "validation": {
            "precisao": {"status": "not_computed", "grade": None, "amplitude_pct": None}
        },
    }
    snap_unclassified = {
        "schema_version": "MP/1",
        "validation": {
            "precisao": {"status": "unclassified", "grade": None, "amplitude_pct": 62.0}
        },
    }
    snap_declared = {
        "schema_version": "MP/1",
        "validation": {
            "documentary": {
                "status": "declared",
                "provenance": "declared",
                "items": [
                    {
                        "id": "fonte_oferta",
                        "evidence_status": "declared",
                        "source": "informado pelo solicitante",
                    }
                ],
            }
        },
    }
    snap_pdf = {
        "schema_version": "MP/1",
        "issues": [
            {
                "code": "PDF_FAILED",
                "severity": "error",
                "origin": "report",
                "message": "Falha ao gerar o PDF do laudo",
                "affected_ids": ["report_pdf"],
                "evidence": {"artifact": "report_pdf", "state": "failed"},
            }
        ],
        "artifact_states": {
            "report_pdf": {
                "state": "failed",
                "error": {"code": "PDF_RENDER_ERROR", "message": "weasyprint missing"},
            }
        },
    }

    def codes_for(snap):
        return {a["code"] for a in recommend_next_actions(snap)}

    c_nc = codes_for(snap_not_computed)
    c_un = codes_for(snap_unclassified)
    c_dec = codes_for(snap_declared)
    c_pdf = codes_for(snap_pdf)

    assert CODE_PRECISION_NOT_COMPUTED in c_nc
    assert CODE_PRECISION_UNCLASSIFIED in c_un
    assert CODE_DOCUMENT_SOURCE in c_dec
    assert CODE_ARTIFACT in c_pdf

    four = {
        CODE_PRECISION_NOT_COMPUTED,
        CODE_PRECISION_UNCLASSIFIED,
        CODE_DOCUMENT_SOURCE,
        CODE_ARTIFACT,
    }
    assert len(four) == 4

    combined = _base_snapshot(
        validation={
            "fundamentacao": {"grade": None, "points": None, "items": []},
            "precisao": {"status": "not_computed", "grade": None, "amplitude_pct": None},
            "statistical": {},
            "documentary": {"status": "declared", "provenance": "declared", "items": []},
            "issuance": {"status": "draft", "reasons": ["precisao não calculada"]},
        },
        issues=[
            {
                "code": "PRECISION_UNCLASSIFIED",
                "severity": "warning",
                "origin": "validation",
                "message": "Precisão não classificável",
                "affected_ids": [],
                "evidence": {"amplitude_pct": 62.0},
            },
            {
                "code": "PDF_FAILED",
                "severity": "error",
                "origin": "report",
                "message": "Falha ao gerar o PDF do laudo",
                "affected_ids": ["report_pdf"],
                "evidence": {"state": "failed"},
            },
        ],
    )
    combined_codes = {a["code"] for a in recommend_next_actions(combined)}
    assert four <= combined_codes


def test_c13_a04_no_invented_inferences_and_duplicates_keep_evidence():
    empty_actions = recommend_next_actions({})
    assert INVENTED_IMPACT.search(_all_text(empty_actions)) is None
    assert "15%" not in _all_text(empty_actions)
    assert "30%" not in _all_text(empty_actions)

    snapshot = {
        "schema_version": "MP/1",
        "issues": [
            {
                "code": "PARSE_ERROR",
                "severity": "error",
                "origin": "ingest",
                "message": "Valor ambíguo na coluna preco",
                "affected_ids": ["r1"],
                "evidence": {"column": "preco", "raw": "1.234,56 ou 1,234.56"},
            },
            {
                "code": "PARSE_ERROR",
                "severity": "error",
                "origin": "ingest",
                "message": "Unidade não resolvida na coluna area",
                "affected_ids": ["r2"],
                "evidence": {"column": "area", "raw": "m2?"},
            },
        ],
    }
    actions = recommend_next_actions(snapshot)
    parse_actions = [a for a in actions if a["code"] == CODE_UNIT_PARSE]
    assert len(parse_actions) == 1
    refs = parse_actions[0]["evidence_refs"]
    dumped = str(refs)
    assert "r1" in dumped and "r2" in dumped
    assert "preco" in dumped and "area" in dumped
    assert INVENTED_IMPACT.search(_all_text(actions)) is None


def test_c13_a05_alternatives_require_compatible_unit_date_estimand():
    mismatched = _base_snapshot(
        alternatives=[
            {
                "candidate_id": "alt_a",
                "value": {"point": 100000.0},
                "target": {"unit": "BRL", "estimand": "mean"},
                "reference_date": "2024-06-01",
            },
            {
                "candidate_id": "alt_b",
                "value": {"point": 8500.0},
                "target": {"unit": "BRL/m2", "estimand": "mean"},
                "reference_date": "2024-06-01",
            },
        ]
    )
    actions = recommend_next_actions(mismatched)
    incompat = [a for a in actions if a["code"] == CODE_INCOMPATIBLE_ALT]
    assert len(incompat) == 1
    text = _blob(incompat[0])
    assert "100000" not in text and "8500" not in text
    assert "ic normativo" not in text.lower()
    assert "intervalo de confiança normativo" not in text.lower()
    assert CODE_SENSITIVITY not in {a["code"] for a in actions}

    compatible = _base_snapshot(
        alternatives=[
            {
                "candidate_id": "alt_a",
                "value": {"point": 100000.0},
                "target": {"unit": "BRL", "estimand": "mean"},
                "reference_date": "2024-06-01",
            },
            {
                "candidate_id": "alt_c",
                "value": {"point": 118000.0},
                "target": {"unit": "BRL", "estimand": "mean"},
                "reference_date": "2024-06-01",
            },
        ]
    )
    actions_ok = recommend_next_actions(compatible)
    sens = [a for a in actions_ok if a["code"] == CODE_SENSITIVITY]
    assert len(sens) == 1
    stext = _blob(sens[0]).lower()
    assert "sensibilidade" in stext
    assert "ic normativo" not in stext
    assert "intervalo de confiança normativo" not in stext
    assert "precisão normativa" not in stext
    assert CODE_INCOMPATIBLE_ALT not in {a["code"] for a in actions_ok}


def test_determinism_same_snapshot_same_actions():
    snapshot = _base_snapshot(
        issues=[
            {
                "code": "UNIT_PENDING",
                "severity": "error",
                "origin": "ingest",
                "message": "Unidade do alvo pendente",
                "affected_ids": ["preco"],
                "evidence": {"unit": None},
            }
        ]
    )
    a = recommend_next_actions(snapshot)
    b = recommend_next_actions(copy.deepcopy(snapshot))
    assert a == b


def test_does_not_call_normative_classifier_or_llm():
    import modules.decision_support as ds

    source = inspect.getsource(ds)
    assert "nbr14653_validation" not in source
    assert "NBRValidator" not in source
    assert "openai" not in source.lower()
    assert "anthropic" not in source.lower()
    assert "litellm" not in source.lower()


def test_missing_subject_characteristic_from_feature_schema():
    snapshot = _base_snapshot(subject_raw={"bairro": "Centro"})
    schema = {
        "version": 1,
        "columns": {
            "area": {
                "original_name": "area",
                "role": "predictor",
                "kind": "numeric",
                "unit": "m2",
                "group_id": None,
                "categories": None,
                "reference_category": None,
            },
            "bairro": {
                "original_name": "bairro",
                "role": "predictor",
                "kind": "categorical",
                "unit": None,
                "group_id": "g_bairro",
                "categories": ["Centro", "Norte"],
                "reference_category": "Centro",
            },
        },
        "groups": {},
        "target": {"column": "preco", "unit": "BRL"},
    }
    actions = recommend_next_actions(snapshot, feature_schema=schema)
    codes = [a["code"] for a in actions]
    assert "provide_subject_characteristic" in codes
    action = next(a for a in actions if a["code"] == "provide_subject_characteristic")
    assert "area" in _blob(action)


def test_reference_date_pending_and_extrapolation_and_assumption():
    snapshot = _base_snapshot(
        reference_date=None,
        issues=[
            {
                "code": "EXTRAPOLATION",
                "severity": "warning",
                "origin": "validation",
                "message": "Variável area fora do intervalo amostral",
                "affected_ids": ["area"],
                "evidence": {"sample_min": 40, "sample_max": 80, "subject": 120},
            },
            {
                "code": "HETEROSCEDASTICITY",
                "severity": "warning",
                "origin": "evaluation",
                "message": "Breusch-Pagan rejeitado",
                "affected_ids": [],
                "evidence": {"p_value": 0.01},
            },
        ],
    )
    codes = {a["code"] for a in recommend_next_actions(snapshot)}
    assert "define_reference_date" in codes
    assert "investigate_extrapolation" in codes
    assert "check_assumption" in codes


def test_original_issues_are_referenced_not_dropped():
    snapshot = _base_snapshot(
        issues=[
            {
                "code": "IMPUTED_TARGET",
                "severity": "error",
                "origin": "ingest",
                "message": "Preço imputado",
                "affected_ids": ["r9"],
                "evidence": {"column": "preco"},
            }
        ]
    )
    before = copy.deepcopy(snapshot["issues"])
    actions = recommend_next_actions(snapshot)
    assert snapshot["issues"] == before
    imputed = next(a for a in actions if a["code"] == CODE_IMPUTED_PRICE)
    assert "r9" in str(imputed["evidence_refs"])
    assert "IMPUTED_TARGET" in str(imputed["evidence_refs"])


def test_c13_a01_complete_tabela1_list_still_uses_item2_six_k_plus_1():
    k, n = 4, 26
    expected_deficit = 6 * (k + 1) - n
    snapshot = {
        "schema_version": "MP/1",
        "reference_date": "2024-06-01",
        "sample": {"used": n},
        "model": {"k": k},
        "issues": [
            {
                "code": "SAMPLE_INSUFFICIENT",
                "severity": "warning",
                "origin": "validation",
                "message": "Suporte amostral insuficiente",
                "affected_ids": ["item_2"],
                "evidence": {},
            }
        ],
        "validation": {
            "fundamentacao": {
                "items": [
                    {"item": 1, "evidence_status": "verified", "rule": "3(k+1)"},
                    {
                        "item": 2,
                        "evidence_status": "verified",
                        "calculation": {"n": n, "k": k, "rule": "6(k+1)"},
                    },
                    {
                        "item": 3,
                        "evidence_status": "verified",
                        "calculation": {"formula": "identificação documental"},
                    },
                ]
            }
        },
    }
    actions = recommend_next_actions(snapshot)
    sample_actions = [a for a in actions if a["code"] == CODE_SAMPLE]
    assert len(sample_actions) == 1
    text = _blob(sample_actions[0])
    assert str(expected_deficit) in text
    assert "este item" in text.lower()
    assert "grau global" in text.lower()


def test_c13_a01_items_as_mapping_and_declared_rule_is_not_a_deficit():
    k, n = 4, 26
    expected_deficit = 6 * (k + 1) - n
    mapped = {
        "schema_version": "MP/1",
        "reference_date": "2024-06-01",
        "sample": {"used": n},
        "model": {"k": k},
        "validation": {
            "fundamentacao": {
                "items": {
                    "1": {"evidence_status": "verified", "rule": "3(k+1)"},
                    "2": {
                        "evidence_status": "verified",
                        "calculation": {"n": n, "k": k, "rule": "6(k+1)"},
                    },
                }
            }
        },
    }
    actions = recommend_next_actions(mapped)
    sample = next(a for a in actions if a["code"] == CODE_SAMPLE)
    assert str(expected_deficit) in sample["reason"]

    declared = {
        "schema_version": "MP/1",
        "sample": {"used": n},
        "model": {"k": k},
        "validation": {
            "fundamentacao": {
                "items": [
                    {
                        "item": 2,
                        "evidence_status": "declared",
                        "calculation": {"n": n, "k": k, "rule": "6(k+1)"},
                    }
                ]
            }
        },
    }
    declared_actions = recommend_next_actions(declared)
    sample_declared = [a for a in declared_actions if a["code"] == CODE_SAMPLE]
    assert sample_declared == []
    assert f"Déficit de {expected_deficit}" not in _all_text(declared_actions)


def test_c13_a05_two_identity_groups_are_incompatible_not_one_sensitivity():
    snapshot = _base_snapshot(
        alternatives=[
            {
                "candidate_id": "a1",
                "value": {"point": 100000.0},
                "target": {"unit": "BRL", "estimand": "mean"},
                "reference_date": "2024-06-01",
            },
            {
                "candidate_id": "a2",
                "value": {"point": 118000.0},
                "target": {"unit": "BRL", "estimand": "mean"},
                "reference_date": "2024-06-01",
            },
            {
                "candidate_id": "b1",
                "value": {"point": 8000.0},
                "target": {"unit": "BRL/m2", "estimand": "mean"},
                "reference_date": "2024-06-01",
            },
            {
                "candidate_id": "b2",
                "value": {"point": 9000.0},
                "target": {"unit": "BRL/m2", "estimand": "mean"},
                "reference_date": "2024-06-01",
            },
        ]
    )
    actions = recommend_next_actions(snapshot)
    codes = [a["code"] for a in actions]
    assert CODE_INCOMPATIBLE_ALT in codes
    assert CODE_SENSITIVITY not in codes
    incompat = next(a for a in actions if a["code"] == CODE_INCOMPATIBLE_ALT)
    text = _blob(incompat)
    assert "100000" not in text
    assert "118000" not in text
    assert "8000" not in text
    assert "9000" not in text
