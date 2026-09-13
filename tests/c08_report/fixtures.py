"""Known MP/1 snapshot fixtures for C08. Values are literals, not recomputed."""

from __future__ import annotations

from typing import Any, Dict, List

# Canonical known case (C08-A01). These numbers are the oracle; the renderer
# must copy them, never refit OLS to obtain them.
KNOWN_POINT = 350000.0
KNOWN_MEAN_CI80_LOWER = 320000.0
KNOWN_MEAN_CI80_UPPER = 380000.0
KNOWN_PRED_LOWER = 280000.0
KNOWN_PRED_UPPER = 420000.0
KNOWN_ARB_LOWER = 297500.0
KNOWN_ARB_UPPER = 402500.0
KNOWN_ADM_LOWER = 320000.0
KNOWN_ADM_UPPER = 380000.0
KNOWN_REFERENCE_DATE = "2024-03-15"
KNOWN_INSPECTION_DATE = "2024-03-01"
KNOWN_GENERATED_AT = "2024-03-20T12:00:00Z"
KNOWN_UNIT = "BRL"
KNOWN_UNIT_M2 = "BRL/m2"
KNOWN_JOB = "job-mp1-known"
KNOWN_MODEL_ID = "OLS-MP1-17"
KNOWN_MODEL_REVISION = "r3"
KNOWN_MODEL_SHA = "abc123def456"
KNOWN_CODE_SHA = "c92949e4db8c559c6b02ef58b7df90d6cf01e7ed"
KNOWN_INPUT_SHA = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
KNOWN_COEF_AREA = 1234.56789012345

# Portuguese + Greek + currency/math symbols supported by DejaVu Sans
# (no CJK/emoji: the environment has no CJK font for WeasyPrint).
LONG_UNICODE_NAME = "José da Silva — Avaliação nº αβ € ção " + ("N" * 72)

N_USED = 210
N_EXCLUDED = 12
N_RECEIVED = 240
N_OBSERVED = 230
N_PREPARED = 222


def _used_id(i: int) -> str:
    return f"used-{i:04d}"


def _excl_id(i: int) -> str:
    return f"excl-{i:04d}"


def used_row_ids(n: int = N_USED) -> List[str]:
    return [_used_id(i) for i in range(1, n + 1)]


def excluded_row_ids(n: int = N_EXCLUDED) -> List[str]:
    return [_excl_id(i) for i in range(1, n + 1)]


def known_snapshot(**overrides: Any) -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {
        "schema_version": "MP/1",
        "job_id": KNOWN_JOB,
        "project_id": "proj-sintetico-c08",
        "input_sha256": KNOWN_INPUT_SHA,
        "code_sha": KNOWN_CODE_SHA,
        "reference_date": KNOWN_REFERENCE_DATE,
        "inspection_date": KNOWN_INSPECTION_DATE,
        "generated_at": KNOWN_GENERATED_AT,
        "target": {
            "column": "preco",
            "unit": KNOWN_UNIT,
            "estimand": "média condicional do preço na unidade original",
        },
        "value": {
            "point": KNOWN_POINT,
            "mean_ci80": {"lower": KNOWN_MEAN_CI80_LOWER, "upper": KNOWN_MEAN_CI80_UPPER},
            "prediction_interval": {"lower": KNOWN_PRED_LOWER, "upper": KNOWN_PRED_UPPER},
            "arbitration_interval": {"lower": KNOWN_ARB_LOWER, "upper": KNOWN_ARB_UPPER},
            "admissible_interval": {"lower": KNOWN_ADM_LOWER, "upper": KNOWN_ADM_UPPER},
        },
        "sample": {
            "received": 40,
            "observed_target": 38,
            "prepared": 36,
            "used": 30,
            "excluded": 6,
            "used_row_ids": used_row_ids(30),
            "excluded_row_ids": excluded_row_ids(6),
        },
        "validation": {
            "fundamentacao": {
                "grade": 2,
                "points": 11,
                "items": [
                    {
                        "item": 1,
                        "description": "Caracterização do imóvel avaliando",
                        "grade": 2,
                        "detail": "declarado pelo solicitante",
                        "evidence_status": "declared",
                    }
                ],
            },
            "precisao": {"status": "classified", "grade": 2, "amplitude_pct": 17.1},
            "statistical": {"limitations": ["IC da média não é intervalo preditivo."]},
            "documentary": {
                "declared": [{"name": "Matrícula informada pelo usuário", "provenance": "upload"}],
                "present": [{"name": "Planilha de mercado sintética", "provenance": "fixture C08"}],
                "verified": [],
            },
            "issuance": {
                "status": "review_required",
                "reasons": ["Documentos apenas declarados/presentes, não verificados"],
            },
        },
        "issues": [
            {
                "code": "NBR_ITEM1_DECLARED_ONLY",
                "severity": "warning",
                "origin": "normative",
                "message": "Caracterização do avaliando permanece declarada, não vistoriada.",
                "affected_ids": [],
                "evidence": {},
            }
        ],
        "model": {
            "model_id": KNOWN_MODEL_ID,
            "revision": KNOWN_MODEL_REVISION,
            "model_sha256": KNOWN_MODEL_SHA,
            "formula": "preco = 18000 + 1234.56789012345*area + 8500*quartos",
            "coefficients": {"const": 18000.0, "area": KNOWN_COEF_AREA, "quartos": 8500.0},
            "pvalues": {"const": 0.01, "area": 0.001, "quartos": 0.02},
            "vif": {"area": 1.4, "quartos": 1.2},
            "metrics": {
                "r2": 0.91,
                "r2_adjusted": 0.90,
                "f_statistic": 120.0,
                "f_pvalue": 0.0001,
                "durbin_watson": 1.85,
            },
        },
        "search": {
            "exhaustive": True,
            "mode": "exhaustive",
            "combinations_tested": 12,
            "coverage": "1.0",
            "objective": "grau de fundamentação, depois R² ajustado como desempate descritivo",
            "message": "Busca enumerou o espaço declarado.",
            "limitations": [],
        },
        "alternatives": [{"candidate_id": "alt-lin-lin", "summary": "especificacao alternativa nao selecionada"}],
        "next_actions": [
            {
                "code": "VERIFY_INSPECTION",
                "priority": "high",
                "reason": "Vistoria não comprovada",
                "next_step": "Anexar evidência de vistoria e reemitir a minuta",
                "evidence_refs": ["documentary.declared"],
                "limitations": "Sem vistoria o grau permanece declarado",
            }
        ],
        "provenance": {
            "model_id": KNOWN_MODEL_ID,
            "model_revision": KNOWN_MODEL_REVISION,
            "code_sha": KNOWN_CODE_SHA,
            "input_sha256": KNOWN_INPUT_SHA,
        },
        "applicant": "Solicitante sintético C08",
        "purpose": "Teste de contrato MP/1 — sem dados reais de cliente",
    }
    snapshot.update(overrides)
    return snapshot


def known_context(*, n_used: int = 30, n_excluded: int = 6) -> Dict[str, Any]:
    used = []
    for i, rid in enumerate(used_row_ids(n_used), start=1):
        name = LONG_UNICODE_NAME if i == n_used else f"Comparável {i}"
        used.append(
            {
                "row_id": rid,
                "source": "planilha sintética C08",
                "justification": "Registro na amostra efetiva do snapshot",
                "label": name,
                "values": {
                    "nome": name,
                    "area_m2": 50 + i,
                    "preco_brl": 200000 + i * 100,
                    "preco_m2": "BRL/m2",
                    "nota": "linha 1\nlinha 2 com quebra",
                },
            }
        )
    excluded = []
    for i, rid in enumerate(excluded_row_ids(n_excluded), start=1):
        excluded.append(
            {
                "row_id": rid,
                "source": "planilha sintética C08",
                "justification": f"Excluído por política declarada (motivo {i})",
                "values": {"nome": f"Excluído {i}"},
            }
        )
    fitted = [float(200000 + 1000 * i) for i in range(30)]
    resid = [float((i % 5) - 2) * 500 for i in range(30)]
    return {
        "applicant": "Solicitante sintético C08",
        "purpose": "Teste de contrato MP/1 — sem dados reais de cliente",
        "inspection_date": KNOWN_INSPECTION_DATE,
        "sources": [
            {"id": "S1", "label": "Planilha sintética", "citation": "fixture C08, não é dado de cliente"}
        ],
        "used_rows": used,
        "excluded_rows": excluded,
        "documents": [
            {"name": "ART/RRT", "status": "pending", "provenance": "não anexada"}
        ],
        "fitted_values": fitted,
        "residuals": resid,
        "market_descriptive": {
            "n": n_used,
            "variables": [
                {
                    "name": "area",
                    "unit": "m²",
                    "min": 40.0,
                    "mean": 90.0,
                    "median": 88.0,
                    "max": 180.0,
                }
            ],
        },
        "inference_limitations": [
            "O intervalo preditivo cobre uma nova observação; o IC da média cobre a média condicional."
        ],
        "subject": {"area": 120.0, "quartos": 3, "endereco_sintetico": LONG_UNICODE_NAME},
    }


def pending_date_unit_snapshot() -> Dict[str, Any]:
    snap = known_snapshot()
    snap["reference_date"] = None
    snap["inspection_date"] = None
    snap["target"] = dict(snap["target"])
    snap["target"]["unit"] = ""
    snap["generated_at"] = "2020-01-01T00:00:00Z"
    return snap


def warnings_snapshot() -> Dict[str, Any]:
    snap = known_snapshot()
    snap["validation"] = dict(snap["validation"])
    snap["validation"]["precisao"] = {
        "status": "unclassified",
        "grade": None,
        "amplitude_pct": 62.5,
    }
    snap["validation"]["issuance"] = {
        "status": "draft",
        "reasons": ["Precisão calculada mas não classificável", "Busca aproximada"],
    }
    snap["validation"]["documentary"] = {
        "declared": [{"name": "Laudo anterior (declarado)", "provenance": "usuário"}],
        "present": [{"name": "Fotos sintéticas", "provenance": "fixture"}],
        "verified": [],
    }
    snap["search"] = {
        "exhaustive": False,
        "mode": "approximate",
        "combinations_tested": 40,
        "coverage": "0.12",
        "budget": "top-N correlação",
        "objective": "desempate descritivo por R² ajustado — R² maior não implica avaliação superior",
        "message": "Fallback heurístico; garantia de ótimo global NÃO se aplica.",
        "limitations": ["Espaço não enumerado por completo"],
    }
    snap["issues"] = [
        {
            "code": "NBR_FUND_PENDING",
            "severity": "warning",
            "origin": "normative",
            "message": "Grau de fundamentação depende de evidência ainda declarada.",
            "affected_ids": [],
            "evidence": {},
        },
        {
            "code": "STAT_HETEROSCEDASTICITY",
            "severity": "warning",
            "origin": "statistical",
            "message": "Heterocedasticidade não rejeitada; IC da média e intervalo preditivo permanecem distintos.",
            "affected_ids": [],
            "evidence": {},
        },
        {
            "code": "DOC_NOT_VERIFIED",
            "severity": "warning",
            "origin": "documentary",
            "message": "Documento declarado não foi verificado.",
            "affected_ids": [],
            "evidence": {},
        },
        {
            "code": "SEARCH_NOT_EXHAUSTIVE",
            "severity": "warning",
            "origin": "search",
            "message": "Busca aproximada: cobertura parcial do espaço.",
            "affected_ids": [],
            "evidence": {},
        },
        {
            "code": "INFERENCE_TRANSFORM",
            "severity": "info",
            "origin": "inference",
            "message": "Não se atribui IC normativo à transformação sem método validado.",
            "affected_ids": [],
            "evidence": {},
        },
    ]
    snap["next_actions"] = [
        {
            "code": "JUSTIFY_PRECISION",
            "priority": "high",
            "reason": "Amplitude 62,5% não classificável",
            "next_step": "Justificar no diagnóstico de mercado ou revisar a amostra",
            "evidence_refs": ["validation.precisao"],
            "limitations": "Não inventar grau de precisão",
        }
    ]
    return snap


def long_table_snapshot() -> Dict[str, Any]:
    snap = known_snapshot()
    ids = used_row_ids(N_USED)
    excl = excluded_row_ids(N_EXCLUDED)
    snap["sample"] = {
        "received": N_RECEIVED,
        "observed_target": N_OBSERVED,
        "prepared": N_PREPARED,
        "used": N_USED,
        "excluded": N_EXCLUDED,
        "used_row_ids": ids,
        "excluded_row_ids": excl,
    }
    snap["target"] = dict(snap["target"])
    snap["target"]["unit"] = KNOWN_UNIT_M2
    snap["value"] = dict(snap["value"])
    snap["value"]["point"] = 3500.0
    snap["value"]["mean_ci80"] = {"lower": 3200.0, "upper": 3800.0}
    snap["value"]["prediction_interval"] = {"lower": 2800.0, "upper": 4200.0}
    snap["value"]["arbitration_interval"] = {"lower": 2975.0, "upper": 4025.0}
    snap["value"]["admissible_interval"] = {"lower": 3200.0, "upper": 3800.0}
    return snap


def long_table_context() -> Dict[str, Any]:
    return known_context(n_used=N_USED, n_excluded=N_EXCLUDED)
