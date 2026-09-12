"""Formulário da avaliação e contrato HTTP C10/C11 (campanha P02 / C09).

A leitura semântica do arquivo e a codificação de categorias NÃO são feitas
aqui: /preview e o esquema de C02 são a fonte. Este módulo apenas:

- monta RequestSpec / payload do avaliando a partir das escolhas do usuário;
- valida o disparo (lista vazia = nenhuma autorizada, nunca todas);
- consome a API com timeout e recuperação por job_id;
- vincula o mapeamento ao arquivo/esquema e emite só a chave canônica de grau.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Mapping, MutableMapping, Optional, Sequence

import httpx
import pandas as pd
import streamlit as st

from .professional import (
    BACKUP_NOTICE,
    KNOWN_ASSET_SCOPES,
    KNOWN_PURPOSES,
    KNOWN_RECIPIENTS,
    KNOWN_RIGHTS,
    KNOWN_VALUE_BASES,
    build_encomenda,
    build_inspection_record,
    build_professional_identity,
    empty_inspection_record,
    known_profiles,
    qualification_profile_wire,
    record_justified_exclusion,
    select_qualification_profile,
)
from .workflow import (
    SUPPORTED_EVALUATION_METHODS,
    SUPPORTED_EVALUATION_METHOD_IDS,
    merge_invalidation,
    canonical_evaluation_policy,
    canonical_search_policy,
    cost_estimate_from_payload,
    execution_fingerprint,
    interpreted_sample_rows,
    mapping_binding_token,
    normalize_minimum_grade,
    normalize_projects_list,
    list_route_unavailable,
    pick_revision,
    policies_on_the_wire,
    preview_failure_clears_interpretation,
    revision_recovery_plan,
    schema_fingerprint,
    should_block_duplicate_submit,
    unused_columns_view,
    widget_namespace,
)

SCHEMA_VERSION = "MP/1"
DEFAULT_API_URL = os.environ.get("MODELA_API_URL", "http://127.0.0.1:8000")
DEFAULT_TIMEOUT = float(os.environ.get("MODELA_API_TIMEOUT", "30"))

VALID_ROLES = ("target", "predictor", "identifier", "source", "date", "excluded")
VALID_LOCALES = ("auto", "pt-BR", "en-US")
ACTIVE_JOB_STATES = frozenset({"queued", "running"})
TERMINAL_JOB_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})

PROFESSIONAL_FINDING_RULES = (
    ("anexoA.2.f.variaveis_relevantes", "Variáveis relevantes e interações"),
    ("anexoA.2.g.multicolinearidade", "Coerência do avaliando com a multicolinearidade"),
    ("anexoA.2.h.residuos_vs_independentes", "Resíduos versus variáveis independentes"),
    ("anexoA.2.i.pontos_influenciantes", "Pontos influenciantes"),
    ("anexoA.8.agrupamentos", "Agrupamentos e interações"),
)

PREVIEW_CONNECTION_ERROR = (
    "Erro de conexão: não foi possível obter a prévia da interpretação. "
    "A interface não inventa uma leitura local alternativa, porque ela "
    "seria incompatível com o contrato da API."
)
EMPTY_SELECTION_MESSAGE = (
    "Nenhuma variável autorizada. A lista vazia não seleciona todas as "
    "colunas — autorize ao menos uma variável ou use a seleção automática "
    "por papel."
)
DEGREE_HELP = (
    "Grau de fundamentação mínimo solicitado: objetivo da busca, não "
    "promessa de emissão nem de classificação integral. Ausência = não solicitado."
)
METHOD_HELP = (
    "Validação independente só corre se um método suportado pela API for "
    "escolhido. «Não executar» envia evaluation_policy.method=none — não é erro."
)
HOLD_OUT_HELP = (
    "O holdout não fica oculto e não é disparado a cada edição de campo. "
    "Entra no pedido apenas quando você executar o cálculo."
)


class ApiConnectionError(Exception):
    """API inacessível, tempo esgotado ou conexão fechada."""


class ApiResponseError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class DuplicateExecutionError(Exception):
    """Tentativa de POST /jobs enquanto já há execução ativa."""


class DispatchBlocked(Exception):
    """Disparo recusado por inconsistência do RequestSpec/avaliando."""


# ---------------------------------------------------------------------------
# Heurística legada — só sugere papel padrão; nunca restringe a escolha.
# ---------------------------------------------------------------------------

def _looks_like_price(col_name: str, original: str = "") -> bool:
    """Default target guess only. Never hides other columns from the selectbox."""
    tokens = [t for t in re.split(r"[^a-z0-9]+", str(col_name).lower()) if t]
    tokens.extend(t for t in re.split(r"[^a-z0-9]+", str(original).lower()) if t)
    return bool({"preco", "preço", "price", "valor"} & set(tokens))


def _looks_like_identification(col_name: str, series: pd.Series) -> bool:
    """
    Simple heuristic used ONLY to pre-select the default state of the
    "Variáveis candidatas para o modelo" multiselect below. It never
    restricts what the user can pick - it just tries to guess which
    columns are pure identification data (nome, endereço, telefone...)
    so they start unchecked, while every other column (any dtype, any
    number of unique values) starts checked and can be freely
    added/removed by the user regardless of this guess.

    Per spec, this only applies to dtype object/string columns whose text
    is clearly non-numeric - a numeric column (e.g. "idade") must never be
    caught by this, regardless of its name. The dtype check runs first, and
    the keyword check below uses whole-token matching (split on
    non-alphanumeric boundaries) so e.g. "id" never matches inside "idade",
    "cidade", "unidade" etc. "bairro" is intentionally NOT a keyword here -
    it is a legitimate categorical model variable, not identification data.

    Uses pd.api.types.is_string_dtype instead of `series.dtype == object`:
    pandas 2.x/3.x can read text columns as the dedicated StringDtype
    ("string"/"str") instead of legacy `object`, depending on version and
    settings (confirmed happening here with pandas 3.0 + pd.read_excel) - an
    `== object` check silently never matches those columns, disabling this
    entire heuristic for every text column without any error or warning.
    """
    if not pd.api.types.is_string_dtype(series):
        return False

    keywords = {
        "nome", "endereco", "endereço", "telefone", "fone", "celular",
        "email", "e-mail", "cpf", "cnpj", "rg", "contato", "informante",
        "id", "matricula", "matrícula", "observacao", "observação", "obs",
    }
    name_tokens = [t for t in re.split(r"[^a-z0-9]+", str(col_name).lower()) if t]
    if any(t in keywords for t in name_tokens):
        return True

    non_null = series.dropna().astype(str)
    if len(non_null) == 0:
        return False

    def _is_numeric_like(s: str) -> bool:
        cleaned = s.replace("R$", "").replace(".", "").replace(",", ".").strip()
        try:
            float(cleaned)
            return True
        except ValueError:
            return False

    numeric_ratio = non_null.apply(_is_numeric_like).mean()
    if numeric_ratio >= 0.5:
        return False

    avg_words = non_null.apply(lambda s: len(s.split())).mean()
    return avg_words >= 2


def _is_bairro(name: str, original_name: Optional[str] = None) -> bool:
    tokens = [t for t in re.split(r"[^a-z0-9]+", str(name).lower()) if t]
    if "bairro" in tokens:
        return True
    if original_name:
        orig_tokens = [t for t in re.split(r"[^a-z0-9]+", str(original_name).lower()) if t]
        return "bairro" in orig_tokens
    return False


def dummy_column_names(feature_schema: Optional[Mapping[str, Any]]) -> set:
    names: set = set()
    groups = (feature_schema or {}).get("groups") or {}
    for group in groups.values():
        for col in group.get("columns") or []:
            names.add(col)
    return names


def preview_to_form_model(preview: Optional[Mapping[str, Any]]) -> dict:
    if not preview:
        return {
            "columns": [],
            "column_map": {},
            "feature_schema": {},
            "issues": [],
            "input_sha256": None,
        }
    feature_schema = dict(preview.get("feature_schema") or {})
    schema_cols = dict((feature_schema.get("columns") or {}))
    raw_map = preview.get("column_map") or {}
    column_map: dict = {}
    if isinstance(raw_map, Mapping) and isinstance(raw_map.get("entries"), list):
        for entry in raw_map.get("entries") or []:
            if not isinstance(entry, Mapping):
                continue
            name = str(entry.get("internal") or entry.get("original") or "")
            if not name:
                continue
            meta = dict(schema_cols.get(name) or {})
            meta.setdefault("original_name", entry.get("original") or name)
            if entry.get("kind"):
                meta.setdefault("kind", entry.get("kind"))
            if entry.get("unit"):
                meta.setdefault("unit", entry.get("unit"))
            column_map[name] = meta
    elif isinstance(raw_map, Mapping):
        for name, meta in raw_map.items():
            if isinstance(meta, Mapping):
                column_map[str(name)] = dict(meta)
    if not column_map:
        column_map = {str(k): dict(v) if isinstance(v, Mapping) else {"original_name": str(k)} for k, v in schema_cols.items()}
    issues = list(preview.get("issues") or [])
    columns = list(column_map.keys())
    if not columns:
        columns = list(schema_cols.keys())
    return {
        "columns": columns,
        "column_map": column_map,
        "feature_schema": feature_schema,
        "issues": issues,
        "input_sha256": preview.get("input_sha256"),
        "row_ledger": preview.get("row_ledger"),
        "sample_preview": preview.get("sample_preview"),
    }


def suggest_roles(
    column_map: Mapping[str, Any],
    *,
    target_col: Optional[str] = None,
) -> dict:
    """Papéis padrão. bairro é preditor categórico, nunca identificador."""
    roles: dict = {}
    for name, meta in (column_map or {}).items():
        meta = meta or {}
        original = meta.get("original_name") or name
        if target_col and name == target_col:
            roles[name] = "target"
            continue
        suggestion = meta.get("role_suggestion")
        if suggestion in VALID_ROLES:
            roles[name] = suggestion
            continue
        if _is_bairro(name, original):
            roles[name] = "predictor"
            continue
        if target_col is None and "target" not in roles.values() and _looks_like_price(name, original):
            roles[name] = "target"
            continue
        if str(name).lower() == "id" or str(original).lower() == "id":
            roles[name] = "identifier"
            continue
        sample = meta.get("sample") or meta.get("sample_raw") or []
        if sample:
            series = pd.Series(list(sample), dtype="string")
            if _looks_like_identification(name, series) or _looks_like_identification(original, series):
                roles[name] = "identifier"
                continue
        kind = str(meta.get("kind") or "").lower()
        if kind in {"text", "id", "identifier"}:
            roles[name] = "identifier"
        elif kind in {"date", "datetime"}:
            roles[name] = "date"
        elif kind in {"source"}:
            roles[name] = "source"
        else:
            roles[name] = "predictor"
    return roles


def candidate_cols_from_selection(
    selected: Optional[Sequence[str]],
    *,
    auto: bool = False,
) -> Optional[list]:
    """None = seleção automática por papel. [] = nenhuma autorizada."""
    if auto:
        return None
    if selected is None:
        return []
    return list(selected)


def default_missing_policy() -> dict:
    return {"target": "never_impute", "predictors": "complete_case"}


def default_outlier_policy() -> dict:
    return {"mode": "report_only", "reviewed_exclusions": []}


def default_import_options() -> dict:
    return {"locale": "auto", "delimiter": None, "encoding": None}


def default_search_policy(minimum_grade: Optional[int] = None) -> dict:
    """P02 emite só search_policy.minimum_fundamentacao_grade como chave de grau."""
    return canonical_search_policy(minimum_grade)


def default_evaluation_policy(
    minimum_grade: Optional[int] = None,
    *,
    documentary: Optional[Mapping[str, Any]] = None,
    method: str = "none",
    seed: Optional[int] = None,
) -> dict:
    """P02 não copia o grau para evaluation_policy (chave canônica só em search_policy)."""
    del minimum_grade  # grau canônico não vive aqui
    return canonical_evaluation_policy(method=method, seed=seed, documentary=documentary)


def build_request_spec(
    *,
    target_col: str,
    candidate_cols: Optional[Sequence[str]],
    roles: Mapping[str, str],
    units: Optional[Mapping[str, Any]] = None,
    import_options: Optional[Mapping[str, Any]] = None,
    missing_policy: Optional[Mapping[str, Any]] = None,
    outlier_policy: Optional[Mapping[str, Any]] = None,
    search_policy: Optional[Mapping[str, Any]] = None,
    evaluation_policy: Optional[Mapping[str, Any]] = None,
    reference_date: Optional[str] = None,
    inspection_date: Optional[str] = None,
    target_unit: Optional[str] = None,
    applicant: str = "",
    purpose: str = "",
    minimum_fundamentacao_grade: Optional[int] = None,
    documentary: Optional[Mapping[str, Any]] = None,
    evaluation_method: Optional[str] = None,
    rights: Optional[str] = None,
    recipient_id: Optional[str] = None,
    value_basis: Optional[str] = None,
    asset_scope: Optional[str] = None,
    qualification_profile: Optional[Mapping[str, Any]] = None,
    justified_exclusions: Optional[Sequence[Mapping[str, Any]]] = None,
    profile_evidence: Optional[Mapping[str, Any]] = None,
    professional_findings: Optional[Mapping[str, Any]] = None,
    value_policy: Optional[Mapping[str, Any]] = None,
    synthetic_test_only: bool = False,
) -> dict:
    """Monta RequestSpec MP/1. Não presume BRL, BRL/m² nem data de hoje.

    candidate_cols=None → seleção automática por papel.
    candidate_cols=[] → nenhuma variável autorizada (nunca expandido para todas).
    Grau mínimo só em search_policy.minimum_fundamentacao_grade (null ou 1..3).
    Campos C02 (qualification_profile, rights, recipient_id, value_basis,
    asset_scope) são aditivos; o schema raiz permanece MP/1.
    """
    if candidate_cols is not None and not isinstance(candidate_cols, (list, tuple)):
        raise TypeError("candidate_cols deve ser None ou lista")

    cols: Optional[list]
    if candidate_cols is None:
        cols = None
    else:
        cols = list(candidate_cols)

    unit_map = dict(units or {})
    declared_target_unit = target_unit if target_unit else ""
    grade = normalize_minimum_grade(minimum_fundamentacao_grade)

    method = evaluation_method
    if method is None and evaluation_policy:
        method = evaluation_policy.get("method")
    if method is None:
        method = "none"

    search = canonical_search_policy(grade, base=search_policy)
    evaluation = canonical_evaluation_policy(
        method=method,
        partitions=(evaluation_policy or {}).get("partitions") if evaluation_policy else None,
        groups=(evaluation_policy or {}).get("groups") if evaluation_policy else None,
        seed=(evaluation_policy or {}).get("seed") if evaluation_policy else None,
        documentary=documentary if documentary is not None else (
            (evaluation_policy or {}).get("documentary") if evaluation_policy else None
        ),
        extra=evaluation_policy,
    )
    if documentary is not None and "documentary" not in evaluation:
        evaluation["documentary"] = dict(documentary)

    import_opts = dict(default_import_options())
    if import_options:
        import_opts.update(import_options)
    locale = import_opts.get("locale") or "auto"
    if locale not in VALID_LOCALES:
        raise ValueError(f"locale de importação inválido: {locale!r}")
    import_opts["locale"] = locale

    missing = dict(missing_policy or default_missing_policy())
    if "target" not in missing:
        missing["target"] = "never_impute"
    outlier = dict(outlier_policy or default_outlier_policy())

    spec = {
        "schema_version": SCHEMA_VERSION,
        "declared_documentary": {
            "item1_grade": (documentary or {}).get("item1_grade_declared"),
            "item3_grade": (documentary or {}).get("item3_grade_declared"),
            "item1_provenance": (documentary or {}).get("item1_provenance"),
            "item3_provenance": (documentary or {}).get("item3_provenance"),
        },
        "target_col": target_col,
        "candidate_cols": cols,
        "roles": dict(roles or {}),
        "units": unit_map,
        "import_options": import_opts,
        "missing_policy": missing,
        "outlier_policy": outlier,
        "search_policy": search,
        "evaluation_policy": evaluation,
        "reference_date": reference_date or None,
        "inspection_date": inspection_date or None,
        "target_unit": declared_target_unit,
        "applicant": applicant or "",
        "purpose": purpose or "",
    }
    if rights:
        spec["rights"] = rights
    if recipient_id:
        spec["recipient_id"] = recipient_id
    if value_basis:
        spec["value_basis"] = value_basis
    if asset_scope:
        spec["asset_scope"] = asset_scope
    if qualification_profile:
        spec["qualification_profile"] = qualification_profile_wire(qualification_profile)
    if justified_exclusions:
        spec["justified_exclusions"] = [dict(item) for item in justified_exclusions]
    if profile_evidence:
        spec["profile_evidence"] = dict(profile_evidence)
    if professional_findings:
        spec["professional_findings"] = {
            str(rule_id): dict(finding) if isinstance(finding, Mapping) else finding
            for rule_id, finding in professional_findings.items()
        }
    if value_policy:
        spec["value_policy"] = dict(value_policy)
    if synthetic_test_only:
        spec["synthetic_test_only"] = True
    return spec


def request_spec_json(spec: Mapping[str, Any]) -> str:
    return json.dumps(spec, ensure_ascii=False, allow_nan=False)


def build_subject_payload(
    feature_schema: Optional[Mapping[str, Any]],
    raw_values: Optional[Mapping[str, Any]],
    *,
    resolutions: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict:
    """Payload do avaliando em variáveis-base (sem dummies).

    Números originalmente formatados são preservados em raw_values — este
    módulo não interpreta locale nem aplica encoder.
    """
    resolutions = dict(resolutions or {})
    schema_columns = dict((feature_schema or {}).get("columns") or {})
    dummies = dummy_column_names(feature_schema)
    raw_values = dict(raw_values or {})
    raw_out: dict = {}
    issues: list = []
    supported = True

    def _meta_for(key: str) -> tuple:
        if key in schema_columns:
            return key, schema_columns[key] or {}
        for internal, meta in schema_columns.items():
            meta = meta or {}
            if meta.get("original_name") == key:
                return internal, meta
        return key, {}

    def _record_unsupported(code: str, message: str, name: str, evidence: dict, resolved: bool) -> None:
        nonlocal supported
        if not resolved:
            supported = False
        issues.append({
            "code": code,
            "severity": "error",
            "origin": "c09.forms",
            "message": message,
            "affected_ids": [name],
            "evidence": evidence,
            "requires_resolution": not resolved,
            "resolved": resolved,
        })

    handled_originals = set()

    for internal, meta in schema_columns.items():
        meta = meta or {}
        original = meta.get("original_name") or internal
        role = meta.get("role")
        if role == "target":
            continue
        if internal in dummies and internal not in raw_values and original not in raw_values:
            continue

        value = raw_values.get(internal)
        if value is None:
            value = raw_values.get(original)

        kind = str(meta.get("kind") or "").lower()
        categories = meta.get("categories")

        if value is None or value == "":
            issues.append({
                "code": "subject_absence",
                "severity": "info",
                "origin": "c09.forms",
                "message": f"Característica '{original}' ausente no avaliando.",
                "affected_ids": [original],
                "evidence": {"unit": meta.get("unit")},
            })
            raw_out[original] = None
            handled_originals.add(original)
            handled_originals.add(internal)
            continue

        if kind in {"categorical", "category"} and categories:
            if value not in categories:
                res = resolutions.get(internal) or resolutions.get(original) or {}
                action = res.get("action")
                if action == "map_to_supported":
                    mapped = res.get("mapped_value")
                    if mapped in categories:
                        raw_out[original] = mapped
                        issues.append({
                            "code": "unsupported_category",
                            "severity": "warning",
                            "origin": "c09.forms",
                            "message": (
                                f"Categoria '{value}' de '{original}' foi mapeada "
                                f"explicitamente para '{mapped}'."
                            ),
                            "affected_ids": [original],
                            "evidence": {"value": value, "mapped_value": mapped, "categories": list(categories)},
                            "requires_resolution": False,
                            "resolved": True,
                            "action": action,
                        })
                    else:
                        _record_unsupported(
                            "unsupported_category",
                            f"Mapeamento de '{original}' para '{mapped}' não é uma categoria suportada.",
                            original,
                            {"value": value, "mapped_value": mapped, "categories": list(categories)},
                            False,
                        )
                elif action == "exclude":
                    raw_out[original] = None
                    issues.append({
                        "code": "unsupported_category",
                        "severity": "warning",
                        "origin": "c09.forms",
                        "message": f"Categoria não suportada de '{original}' excluída por decisão explícita.",
                        "affected_ids": [original],
                        "evidence": {"value": value, "categories": list(categories)},
                        "requires_resolution": False,
                        "resolved": True,
                        "action": action,
                    })
                elif action == "abort":
                    supported = False
                    _record_unsupported(
                        "unsupported_category",
                        f"Categoria '{value}' de '{original}' não suportada; disparo interrompido por decisão explícita.",
                        original,
                        {"value": value, "categories": list(categories)},
                        True,
                    )
                    issues[-1]["requires_resolution"] = False
                    issues[-1]["action"] = action
                else:
                    _record_unsupported(
                        "unsupported_category",
                        (
                            f"Categoria '{value}' de '{original}' não é suportada pelo "
                            "esquema. Resolva explicitamente: mapear, excluir ou interromper."
                        ),
                        original,
                        {"value": value, "categories": list(categories)},
                        False,
                    )
            else:
                raw_out[original] = value
        else:
            raw_out[original] = value

        handled_originals.add(original)
        handled_originals.add(internal)

    for key, value in raw_values.items():
        if key in handled_originals or key in dummies:
            continue
        internal, meta = _meta_for(key)
        if meta:
            continue
        original = key
        res = resolutions.get(key) or {}
        action = res.get("action")
        if action == "exclude":
            issues.append({
                "code": "unsupported_column",
                "severity": "warning",
                "origin": "c09.forms",
                "message": f"Coluna '{original}' fora do esquema, excluída por decisão explícita.",
                "affected_ids": [original],
                "evidence": {"value": value},
                "requires_resolution": False,
                "resolved": True,
                "action": action,
            })
        elif action == "abort":
            supported = False
            _record_unsupported(
                "unsupported_column",
                f"Coluna '{original}' não suportada; disparo interrompido por decisão explícita.",
                original,
                {"value": value},
                True,
            )
            issues[-1]["requires_resolution"] = False
            issues[-1]["action"] = action
        else:
            _record_unsupported(
                "unsupported_column",
                (
                    f"Coluna '{original}' não está no esquema do avaliando. "
                    "Resolva explicitamente: excluir ou interromper."
                ),
                original,
                {"value": value},
                False,
            )

    return {
        "raw_values": raw_out,
        "supported": supported,
        "issues": issues,
    }


def validate_dispatch(
    request_spec: Mapping[str, Any],
    subject_payload: Optional[Mapping[str, Any]] = None,
    preview: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Recusa disparo inconsistente. [] não vira 'todas as colunas'."""
    blocking: list = []
    pending: list = []

    if not (request_spec or {}).get("target_col"):
        blocking.append({
            "code": "missing_target",
            "message": "Informe a variável-alvo.",
        })

    cols = (request_spec or {}).get("candidate_cols", "MISSING")
    if cols == []:
        blocking.append({
            "code": "no_authorized_variables",
            "message": EMPTY_SELECTION_MESSAGE,
        })

    missing_policy = (request_spec or {}).get("missing_policy") or {}
    target_policy = missing_policy.get("target")
    if target_policy not in (None, "never_impute"):
        blocking.append({
            "code": "target_imputation_forbidden",
            "message": "Nenhum valor-alvo ausente pode ser imputado.",
        })
    if "predictors" in missing_policy and missing_policy.get("predictors") in (None, ""):
        blocking.append({
            "code": "missing_predictor_policy",
            "message": "Ausência de características exige política declarada para preditores.",
        })

    if not (request_spec or {}).get("target_unit"):
        pending.append({
            "code": "pending_target_unit",
            "message": "Unidade do alvo não informada — permanece pendente. Não se presume BRL nem BRL/m².",
        })
    if not (request_spec or {}).get("reference_date"):
        pending.append({
            "code": "pending_reference_date",
            "message": "Data da avaliação (data-base) não informada — permanece pendente. Não se presume a data de hoje.",
        })
    if not (request_spec or {}).get("inspection_date"):
        pending.append({
            "code": "pending_inspection_date",
            "message": "Data da vistoria não informada — permanece pendente. Não confundir com a data-base nem com a emissão.",
        })

    subject = subject_payload or {}
    for iss in subject.get("issues") or []:
        if iss.get("requires_resolution") and not iss.get("resolved"):
            blocking.append({
                "code": "unsupported_unresolved",
                "message": iss.get("message")
                or "Há coluna ou categoria não suportada sem resolução explícita.",
            })
    if subject.get("supported") is False:
        if not any(item["code"] in {"unsupported_unresolved", "subject_unsupported"} for item in blocking):
            blocking.append({
                "code": "subject_unsupported",
                "message": "O avaliando não é suportado pelo esquema até que as pendências sejam resolvidas.",
            })

    if preview is None:
        pending.append({
            "code": "preview_not_consumed",
            "message": "A interpretação do arquivo ainda não foi revisada via /preview.",
        })

    seen = set()
    unique_blocking = []
    for item in blocking:
        key = (item.get("code"), item.get("message"))
        if key in seen:
            continue
        seen.add(key)
        unique_blocking.append(item)

    ok = len(unique_blocking) == 0
    return {
        "ok": ok,
        "can_dispatch": ok,
        "blocking": unique_blocking,
        "pending": pending,
    }


def may_start_execution(job_status: Optional[Mapping[str, Any]]) -> bool:
    state = (job_status or {}).get("state")
    return state not in ACTIVE_JOB_STATES


# ---------------------------------------------------------------------------
# Cliente HTTP C10/C11 — recuperação por GET; WebSocket é opcional.
# ---------------------------------------------------------------------------

def _json_or_text(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


class JobClient:
    """Consome POST /preview, POST /jobs e GETs de estado/resultado.

    O resultado nunca depende de escutar o primeiro evento WebSocket.
    job_id é preservado mesmo se a conexão cair depois do 202.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_API_URL,
        timeout: float = DEFAULT_TIMEOUT,
        *,
        client: Optional[httpx.Client] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http = client
        self.job_id: Optional[str] = None
        self.access_token: Optional[str] = None
        self.status_url: Optional[str] = None
        self.last_status: Optional[dict] = None
        self.last_snapshot: Optional[dict] = None
        self.last_error: Optional[str] = None
        self.last_submit_fingerprint: Optional[str] = None
        self.last_request_spec: Optional[dict] = None

    def _own_client(self) -> httpx.Client:
        if self._http is not None:
            return self._http
        return httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def _call(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        from modules.operacao_local.runtime import local_client_headers
        from urllib.parse import urlsplit
        if urlsplit(url).netloc != urlsplit(self.base_url).netloc:
            raise ApiConnectionError("Destino da API diverge do serviço local configurado.")
        if self._http is None and (urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}
                                   or urlsplit(url).scheme != "http"):
            raise ApiConnectionError("A distribuição local exige API em loopback.")
        kwargs["headers"] = {**local_client_headers(), **kwargs.pop("headers", {})}
        http = self._own_client()
        owns = self._http is None
        try:
            response = http.request(method, url, timeout=self.timeout, **kwargs)
            return response
        except httpx.TimeoutException as exc:
            self.last_error = "timeout"
            raise ApiConnectionError(
                "Tempo esgotado ao contatar a API. O identificador do trabalho, "
                "se já existir, foi preservado."
            ) from exc
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.NetworkError, httpx.HTTPError) as exc:
            self.last_error = "connection"
            raise ApiConnectionError(PREVIEW_CONNECTION_ERROR if path.endswith("/preview") else (
                "Erro de conexão com a API. O identificador do trabalho, se já existir, foi preservado."
            )) from exc
        finally:
            if owns:
                http.close()

    def is_active(self) -> bool:
        state = (self.last_status or {}).get("state")
        return bool(self.job_id) and state in ACTIVE_JOB_STATES

    def preview(
        self,
        file_bytes: bytes,
        filename: str,
        request_spec: Mapping[str, Any],
        content_type: str = "application/octet-stream",
        subject: Optional[Mapping[str, Any]] = None,
    ) -> dict:
        files = {"file": (filename, file_bytes, content_type)}
        data = {"request_json": request_spec_json(request_spec)}
        if subject is not None:
            data["subject_json"] = json.dumps(subject, ensure_ascii=False, allow_nan=False)
        response = self._call("POST", "/preview", files=files, data=data)
        if response.status_code >= 400:
            payload = _json_or_text(response)
            raise ApiResponseError(
                f"A prévia não pôde ser obtida (HTTP {response.status_code}).",
                status_code=response.status_code,
                payload=payload,
            )
        payload = _json_or_text(response)
        if not isinstance(payload, dict):
            raise ApiResponseError("Prévia em formato inesperado.", status_code=response.status_code, payload=payload)
        return payload

    def submit_job(
        self,
        file_bytes: Optional[bytes],
        filename: str,
        request_spec: Mapping[str, Any],
        subject: Optional[Mapping[str, Any]] = None,
        content_type: str = "application/octet-stream",
        project_id: Optional[str] = None,
        input_sha256: Optional[str] = None,
    ) -> dict:
        fingerprint = execution_fingerprint(
            input_sha256=input_sha256,
            filename=filename,
            nbytes=len(file_bytes) if file_bytes is not None else None,
            request_spec=request_spec,
            subject=subject,
        )
        if should_block_duplicate_submit(
            current_fingerprint=fingerprint,
            last_fingerprint=self.last_submit_fingerprint,
            job_status=self.last_status,
            last_job_id=self.job_id,
        ):
            raise DuplicateExecutionError(
                "Este mesmo pedido já foi enviado. A interface não dispara "
                "trabalho equivalente de novo por reexecução ou duplo clique."
            )
        if self.is_active():
            raise DuplicateExecutionError(
                "Já existe uma execução em andamento para este trabalho. "
                "Aguarde, cancele ou recupere o resultado antes de disparar outra."
            )
        files = (
            {"file": (filename, file_bytes, content_type)}
            if file_bytes is not None
            else None
        )
        data = {"request_json": request_spec_json(request_spec)}
        if project_id:
            data["project_id"] = project_id
        if subject is not None:
            payload = subject
            if isinstance(subject, Mapping) and isinstance(subject.get("raw_values"), Mapping):
                payload = subject.get("raw_values")
            data["subject_json"] = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        response = self._call("POST", "/jobs", files=files, data=data)
        payload = _json_or_text(response)
        if response.status_code not in (200, 202) or not isinstance(payload, dict) or not payload.get("job_id"):
            raise ApiResponseError(
                f"Não foi possível iniciar o trabalho (HTTP {response.status_code}).",
                status_code=response.status_code,
                payload=payload,
            )
        self.last_submit_fingerprint = fingerprint
        self.last_request_spec = dict(request_spec)
        self.job_id = str(payload["job_id"])
        self.access_token = payload.get("access_token")
        self.status_url = payload.get("status_url") or f"/jobs/{self.job_id}"
        if "state" in payload:
            self.last_status = {
                "job_id": self.job_id,
                "state": payload.get("state"),
                "result_available": payload.get("result_available", False),
            }
        else:
            self.last_status = {
                "job_id": self.job_id,
                "state": "queued",
                "result_available": False,
            }
        return payload

    def operation(self, method: str, path: str, **kwargs):
        response = self._call(method, path, **kwargs)
        if response.status_code >= 400:
            raise ApiResponseError(
                f"Operação recusada (HTTP {response.status_code}).",
                status_code=response.status_code, payload=_json_or_text(response),
            )
        return response

    def documents(self, action: str = "", *, method: str = "GET", **kwargs) -> dict:
        if not self.job_id:
            raise ApiResponseError("Selecione um trabalho calculado antes da emissão.")
        if not self.access_token:
            self.access_token = self.operation("POST", f"/jobs/{self.job_id}/access-token").json()["access_token"]
        return self.operation(method, f"/jobs/{self.job_id}/documents{action}",
                              headers={"X-Job-Token": self.access_token or ""}, **kwargs).json()

    def get_status(self, job_id: Optional[str] = None) -> dict:
        jid = job_id or self.job_id
        if not jid:
            raise ApiResponseError("Identificador do trabalho ausente.")
        self.job_id = jid
        response = self._call("GET", f"/jobs/{jid}")
        payload = _json_or_text(response)
        if response.status_code >= 400 or not isinstance(payload, dict):
            raise ApiResponseError(
                f"Não foi possível obter o estado do trabalho (HTTP {response.status_code}).",
                status_code=response.status_code,
                payload=payload,
            )
        self.last_status = payload
        if payload.get("job_id"):
            self.job_id = str(payload["job_id"])
        return payload

    def get_result(self, job_id: Optional[str] = None) -> dict:
        jid = job_id or self.job_id
        if not jid:
            raise ApiResponseError("Identificador do trabalho ausente.")
        self.job_id = jid
        response = self._call("GET", f"/jobs/{jid}/result")
        payload = _json_or_text(response)
        if response.status_code >= 400 or not isinstance(payload, dict):
            raise ApiResponseError(
                f"Resultado ainda não disponível (HTTP {response.status_code}).",
                status_code=response.status_code,
                payload=payload,
            )
        self.last_snapshot = payload
        return payload

    def recover(self, job_id: Optional[str] = None) -> Optional[dict]:
        """GET de estado/resultado após falha de WS, rerun ou reabertura.

        Nunca descarta job_id, mesmo se o GET falhar. Ao trocar de trabalho,
        limpa antes todo estado derivado do anterior. O RequestSpec de um
        resultado recuperado vem exclusivamente do frozen_project persistido,
        não dos widgets que estiverem na tela.
        """
        jid = job_id or self.job_id
        if not jid:
            return None
        switching_job = jid != self.job_id
        if switching_job:
            self.access_token = None
            self.status_url = f"/jobs/{jid}"
            self.last_status = None
            self.last_snapshot = None
            self.last_request_spec = None
            self.last_submit_fingerprint = None
            self.last_error = None
        self.job_id = jid
        status = self.get_status(jid)
        if status.get("result_available"):
            # Nunca deixe um snapshot anterior visível se a leitura atual
            # falhar. A exceção é deliberadamente bloqueante para a interface.
            self.last_snapshot = None
            self.last_request_spec = None
            self.last_snapshot = self.get_result(jid)
            frozen_state = (
                ((status.get("artifact_states") or {}).get("frozen_project.json") or {})
                .get("state")
            )
            if frozen_state == "ready":
                raw = self.get_artifact("frozen_project.json", jid)
                try:
                    frozen = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ApiResponseError(
                        "Projeto congelado em formato inesperado.", payload=str(exc)
                    ) from exc
                request_spec = frozen.get("request_spec") if isinstance(frozen, Mapping) else None
                if not isinstance(request_spec, Mapping):
                    raise ApiResponseError(
                        "Projeto congelado não contém RequestSpec canônico.", payload=frozen
                    )
                self.last_request_spec = dict(request_spec)
        else:
            self.last_snapshot = None
            if switching_job:
                self.last_request_spec = None
        return status

    def cancel(self, job_id: Optional[str] = None) -> dict:
        jid = job_id or self.job_id
        if not jid:
            raise ApiResponseError("Identificador do trabalho ausente.")
        self.job_id = jid
        response = self._call("POST", f"/jobs/{jid}/cancel")
        payload = _json_or_text(response)
        if response.status_code >= 400:
            raise ApiResponseError(
                f"Não foi possível cancelar (HTTP {response.status_code}).",
                status_code=response.status_code,
                payload=payload,
            )
        if isinstance(payload, dict):
            self.last_status = payload if payload.get("state") else self.last_status
        return payload if isinstance(payload, dict) else {"raw": payload}

    def get_artifact(self, name: str, job_id: Optional[str] = None) -> bytes:
        jid = job_id or self.job_id
        if not jid:
            raise ApiResponseError("Identificador do trabalho ausente.")
        response = self._call("GET", f"/jobs/{jid}/artifacts/{name}")
        if response.status_code >= 400:
            raise ApiResponseError(
                f"Artefato indisponível (HTTP {response.status_code}).",
                status_code=response.status_code,
                payload=_json_or_text(response),
            )
        return response.content

    def list_projects(self) -> Any:
        response = self._call("GET", "/projects")
        payload = _json_or_text(response)
        if response.status_code >= 400:
            raise ApiResponseError(
                f"Projetos indisponíveis (HTTP {response.status_code}).",
                status_code=response.status_code,
                payload=payload,
            )
        return normalize_projects_list(payload)

    def list_revisions(self, project_id: str) -> dict:
        """GET /projects/{id}/revisions if the producer exposes it; else latest only.

        BASE_SHA registers POST /projects/{id}/revisions only. GET on that path
        is 405 Method Not Allowed (not 404). A list route is a P01 handoff —
        this client does not invent it.
        """
        response = self._call("GET", f"/projects/{project_id}/revisions")
        payload = _json_or_text(response)
        if list_route_unavailable(response.status_code):
            return self._revisions_without_list_route(project_id, http_status=response.status_code)
        if response.status_code >= 400:
            raise ApiResponseError(
                f"Revisões indisponíveis (HTTP {response.status_code}).",
                status_code=response.status_code,
                payload=payload,
            )
        if isinstance(payload, Mapping) and isinstance(payload.get("revisions"), list):
            return {
                "project_id": project_id,
                "revisions": list(payload["revisions"]),
                "list_route_available": True,
                "integration": None,
            }
        if isinstance(payload, list):
            return {
                "project_id": project_id,
                "revisions": payload,
                "list_route_available": True,
                "integration": None,
            }
        return {
            "project_id": project_id,
            "revisions": [payload] if payload else [],
            "list_route_available": True,
            "integration": None,
        }

    def _revisions_without_list_route(self, project_id: str, *, http_status: int) -> dict:
        items = []
        try:
            latest = self.get_project(project_id)
            revision = latest.get("revision") if isinstance(latest, Mapping) else None
            if isinstance(revision, Mapping):
                items = [revision]
        except ApiResponseError:
            items = []
        return {
            "project_id": project_id,
            "revisions": items,
            "list_route_available": False,
            "http_status": http_status,
            "integration": "INTEGRATION_PENDING",
            "handoff": {
                "producer": "P01",
                "method": "GET",
                "path": f"/projects/{project_id}/revisions",
                "base_sha_note": "POST-only on BASE_SHA; GET returns 405 Method Not Allowed.",
                "example_response": {
                    "schema_version": SCHEMA_VERSION,
                    "project_id": project_id,
                    "revisions": [
                        {"revision_id": "rev-…", "created_at": "ISO-8601", "job_id": "job-…"}
                    ],
                },
            },
        }

    def reopen_revision(
        self,
        project_id: str,
        revision_id: str,
        revisions_payload: Optional[Mapping[str, Any]] = None,
    ) -> dict:
        """Recover the selected revision via GET /jobs/{id}/result or GET /projects/{id}.

        Never reconstructs from on-screen text. Historical revisions beyond the
        latest require the P01 list route.
        """
        picked = pick_revision(revisions_payload, revision_id)
        if picked is None:
            latest = self.get_project(project_id)
            candidate = latest.get("revision") if isinstance(latest, Mapping) else None
            if isinstance(candidate, Mapping):
                labels = {
                    str(candidate.get("revision_id") or ""),
                    str(candidate.get("job_id") or ""),
                    str((candidate.get("snapshot_ref") or {}).get("job_id") or ""),
                }
                if str(revision_id) in labels:
                    picked = dict(candidate)
            if picked is None:
                return {
                    "recovered": False,
                    "from_screen_text": False,
                    "integration": "INTEGRATION_PENDING",
                    "reason": (
                        "A revisão selecionada não é a atual e GET "
                        f"/projects/{project_id}/revisions não está na BASE_SHA."
                    ),
                    "handoff": {
                        "producer": "P01",
                        "method": "GET",
                        "path": f"/projects/{project_id}/revisions",
                    },
                }
        plan = revision_recovery_plan({"project_id": project_id, "revision": picked})
        if plan.get("job_id"):
            status = self.recover(plan["job_id"])
            return {
                "recovered": True,
                "from_screen_text": False,
                "via": f"GET /jobs/{plan['job_id']}/result",
                "job_id": plan["job_id"],
                "revision_id": picked.get("revision_id") or revision_id,
                "snapshot": self.last_snapshot,
                "status": status,
            }
        return {
            "recovered": True,
            "from_screen_text": False,
            "via": "GET /projects/{id}",
            "job_id": None,
            "revision_id": picked.get("revision_id") or revision_id,
            "frozen": picked,
        }

    def get_project(self, project_id: str) -> dict:
        response = self._call("GET", f"/projects/{project_id}")
        payload = _json_or_text(response)
        if response.status_code >= 400 or not isinstance(payload, dict):
            raise ApiResponseError(
                f"Projeto indisponível (HTTP {response.status_code}).",
                status_code=response.status_code,
                payload=payload,
            )
        return payload

    def save_revision(self, project_id: str, revision_payload: Mapping[str, Any]) -> dict:
        response = self._call(
            "POST",
            f"/projects/{project_id}/revisions",
            json=dict(revision_payload),
            headers={"Content-Type": "application/json"},
        )
        payload = _json_or_text(response)
        if response.status_code >= 400 or not isinstance(payload, dict):
            raise ApiResponseError(
                f"Não foi possível salvar a revisão (HTTP {response.status_code}).",
                status_code=response.status_code,
                payload=payload,
            )
        return payload

    def submit_batch(self, project_id: str, payload: Mapping[str, Any]) -> dict:
        response = self._call(
            "POST",
            f"/projects/{project_id}/batch",
            json=dict(payload),
            headers={"Content-Type": "application/json"},
        )
        body = _json_or_text(response)
        if response.status_code not in (200, 202) or not isinstance(body, dict):
            raise ApiResponseError(
                f"Não foi possível iniciar o lote (HTTP {response.status_code}).",
                status_code=response.status_code,
                payload=body,
            )
        if body.get("job_id") and not self.is_active():
            self.job_id = str(body["job_id"])
            self.status_url = body.get("status_url") or f"/jobs/{self.job_id}"
        return body


def restore_client_from_session(
    session: MutableMapping[str, Any],
    *,
    base_url: str = DEFAULT_API_URL,
    timeout: float = DEFAULT_TIMEOUT,
    client: Optional[httpx.Client] = None,
) -> JobClient:
    job_client = JobClient(base_url=base_url, timeout=timeout, client=client)
    job_client.job_id = session.get("c09_job_id")
    job_client.access_token = session.get("c06_job_access_token")
    job_client.last_status = session.get("c09_job_status")
    job_client.last_snapshot = session.get("c09_snapshot")
    job_client.last_submit_fingerprint = session.get("p02_submit_fingerprint")
    job_client.last_request_spec = session.get("p02_last_request_spec")
    return job_client


def persist_client_to_session(session: MutableMapping[str, Any], job_client: JobClient) -> None:
    session["c09_job_id"] = job_client.job_id
    session["c06_job_access_token"] = job_client.access_token
    session["c09_job_status"] = job_client.last_status
    session["c09_snapshot"] = job_client.last_snapshot
    session["p02_submit_fingerprint"] = job_client.last_submit_fingerprint
    session["p02_last_request_spec"] = job_client.last_request_spec


# ---------------------------------------------------------------------------
# Widgets Streamlit — I/O apenas; regras acima.
# ---------------------------------------------------------------------------

def _iso_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _encomenda_widgets() -> dict:
    """Opening of the professional order. Never auto-attests ART/inspection."""
    st.subheader("1. Encomenda e perfil")
    st.caption(
        "Finalidade, bem, direitos, data-base, unidade, solicitante, destinatário "
        "e perfil versionado entram no pedido. Compatibilidade verificada não é "
        "aceite de banco ou seguradora."
    )
    catalog = known_profiles()
    profile_ids = [row["id"] for row in catalog]
    labels = {row["id"]: row["label"] for row in catalog}
    profile_id = st.selectbox(
        "Perfil de qualificação (versionado, catálogo conhecido)",
        options=profile_ids,
        format_func=lambda value: labels.get(value, value),
        index=0,
        key="c02_profile_id",
        help=(
            "C02 escolhe perfis conhecidos. Regras e conferência normativa são da C05. "
            "Perfil bancário/securitário não homologado não é vendido como aceite."
        ),
    )
    chosen = select_qualification_profile(profile_id)
    purpose_ids = [item[0] for item in KNOWN_PURPOSES]
    purpose_labels = {item[0]: item[1] for item in KNOWN_PURPOSES}
    purpose_index = purpose_ids.index(chosen["purpose"]) if chosen.get("purpose") in purpose_ids else 0
    purpose = st.selectbox(
        "Finalidade da encomenda",
        options=purpose_ids,
        index=purpose_index,
        format_func=lambda value: purpose_labels.get(value, value),
        key="c02_purpose",
    )
    asset_ids = [item[0] for item in KNOWN_ASSET_SCOPES]
    asset_labels = {item[0]: item[1] for item in KNOWN_ASSET_SCOPES}
    asset_scope = st.selectbox(
        "Tipo de bem",
        options=asset_ids,
        index=asset_ids.index(chosen["asset_scope"]) if chosen.get("asset_scope") in asset_ids else 0,
        format_func=lambda value: asset_labels.get(value, value),
        key="c02_asset_scope",
    )
    rights_ids = [item[0] for item in KNOWN_RIGHTS]
    rights_labels = {item[0]: item[1] for item in KNOWN_RIGHTS}
    rights = st.selectbox(
        "Direitos avaliados",
        options=rights_ids,
        format_func=lambda value: rights_labels.get(value, value),
        key="c02_rights",
    )
    basis_ids = [item[0] for item in KNOWN_VALUE_BASES]
    basis_labels = {item[0]: item[1] for item in KNOWN_VALUE_BASES}
    basis_index = basis_ids.index(chosen["value_basis"]) if chosen.get("value_basis") in basis_ids else 0
    value_basis = st.selectbox(
        "Base de valor",
        options=basis_ids,
        index=basis_index,
        format_func=lambda value: basis_labels.get(value, value),
        key="c02_value_basis",
        help="Valor de mercado, custo de reconstrução, valor depreciado e limite de garantia não são sinônimos.",
    )
    recipient_ids = [item[0] for item in KNOWN_RECIPIENTS]
    recipient_labels = {item[0]: item[1] for item in KNOWN_RECIPIENTS}
    rec_index = recipient_ids.index(chosen["recipient_id"]) if chosen.get("recipient_id") in recipient_ids else 0
    recipient_id = st.selectbox(
        "Destinatário",
        options=recipient_ids,
        index=rec_index,
        format_func=lambda value: recipient_labels.get(value, value),
        key="c02_recipient",
    )
    applicant = st.text_input("Solicitante", value="", key="c02_applicant")
    synthetic_test_only = st.checkbox(
        "Caso composto exclusivamente com dados e atos sintéticos de TESTE",
        value=False,
        key="c02_synthetic_test_only",
        help=(
            "Rotula documentos, revisões e assinatura como evidência interna de teste. "
            "Não representa caso real, parecer profissional ou aceite institucional."
        ),
    )
    if synthetic_test_only:
        st.warning(
            "TESTE SINTÉTICO — sem validade externa, sem parecer profissional e sem "
            "aceite institucional."
        )
    resolved = select_qualification_profile(
        profile_id,
        purpose=purpose,
        value_basis=value_basis,
        method=chosen.get("method"),
        asset_scope=asset_scope,
        recipient_id=recipient_id,
    )
    encomenda = build_encomenda(
        purpose=purpose,
        asset_scope=asset_scope,
        rights=rights,
        applicant=applicant,
        recipient_id=recipient_id,
        value_basis=value_basis,
        profile=resolved,
    )
    previous_profile = st.session_state.get("c02_profile_token")
    current_token = f"{resolved.get('id')}|{purpose}|{value_basis}|{asset_scope}|{recipient_id}"
    if previous_profile and previous_profile != current_token:
        st.session_state["c02_review_stale"] = True
        st.session_state["c02_signature_stale"] = True
        st.session_state["c02_issuance_stale"] = True
        st.session_state["p02_result_stale"] = True
        st.session_state["p02_result_stale_reason"] = (
            "O perfil de qualificação mudou. Emissão e revisão anteriores ficam no histórico."
        )
    st.session_state["c02_profile_token"] = current_token
    support = encomenda["method_support_note"]
    if encomenda["method_supports_purpose"]:
        st.info(f"Método do perfil: {resolved.get('method')} — {support}")
    else:
        st.warning(support)
    if resolved.get("recipient_id") in {"banco", "seguradora"}:
        st.warning(
            "Perfil institucional **não homologado**. Compatibilidade do recorte "
            "não é aceite recebido do banco ou da seguradora."
        )
    if resolved.get("homologation_status") == "not_homologated":
        st.caption("Estado de homologação: não homologado. Sem selo de aceite institucional.")
    if purpose == "seguro":
        st.info(
            "Base de valor requerida para este perfil: "
            f"{resolved.get('required_value_basis') or value_basis}. "
            "Não converter preço de mercado em custo por coeficiente."
        )
    st.caption(BACKUP_NOTICE)
    return {
        "encomenda": encomenda,
        "profile": resolved,
        "applicant": applicant,
        "purpose": purpose,
        "rights": rights,
        "recipient_id": recipient_id,
        "value_basis": value_basis,
        "asset_scope": asset_scope,
        "synthetic_test_only": synthetic_test_only,
    }


def _vistoria_and_identity_widgets(*, ns: str, inspection_date: Optional[str]) -> dict:
    st.subheader("3. Avaliando e vistoria")
    st.caption(
        "Vistoria, documentos e identidade profissional com procedência. "
        "Campo com formato válido de ART/RRT não autentica o conselho. "
        "Ato de terceiro permanece informação recebida."
    )
    procedencia = st.selectbox(
        "Procedência da vistoria",
        options=["not_recorded", "professional_act", "received_information"],
        format_func=lambda value: {
            "not_recorded": "Não registrada — ausência não é inspeção atestada",
            "professional_act": "Ato do profissional responsável",
            "received_information": "Informação recebida de terceiro",
        }[value],
        key=f"c02_{ns}_insp_procedencia",
    )
    responsible = st.text_input(
        "Responsável pela vistoria",
        value="",
        key=f"c02_{ns}_insp_responsible",
        help="Vazio permanece não registrado. A tela não preenche inspeção por omissão.",
    )
    verified = st.text_area(
        "Características verificadas",
        value="",
        key=f"c02_{ns}_insp_verified",
    )
    cadastral = st.text_area(
        "Divergências cadastrais",
        value="",
        key=f"c02_{ns}_insp_cadastral",
    )
    physical = st.text_area(
        "Divergências físicas",
        value="",
        key=f"c02_{ns}_insp_physical",
    )
    assumptions = st.text_area(
        "Pressupostos especiais",
        value="",
        key=f"c02_{ns}_insp_assumptions",
    )
    limitations = st.text_area(
        "Limitações da vistoria",
        value="",
        key=f"c02_{ns}_insp_limitations",
    )
    third_party = None
    if procedencia == "received_information":
        third_party = st.text_input(
            "Fonte da informação recebida (terceiro)",
            value="",
            key=f"c02_{ns}_insp_third",
        )
        st.caption("Informação recebida — não é atestado de regularidade nem inspeção realizada por esta tela.")
    inspection = build_inspection_record(
        responsible=responsible,
        date=inspection_date,
        verified_characteristics=verified,
        cadastral_divergences=cadastral,
        physical_divergences=physical,
        special_assumptions=assumptions,
        limitations=limitations,
        procedencia=procedencia,
        third_party_source=third_party,
    )
    st.markdown("#### Identidade profissional e ART/RRT")
    st.caption("Nenhum campo abaixo nasce preenchido como atestado. Formato válido ≠ autenticação do conselho.")
    prof_name = st.text_input("Nome do profissional responsável", value="", key=f"c02_{ns}_prof_name")
    registration = st.text_input("Registro profissional", value="", key=f"c02_{ns}_prof_reg")
    council = st.text_input("Conselho (CREA/CAU/…)", value="", key=f"c02_{ns}_prof_council")
    art_rrt = st.text_input(
        "ART/RRT ou referência documental",
        value="",
        key=f"c02_{ns}_prof_art",
        help="Exigida por alguns perfis. Preenchimento com formato válido não autentica o conselho.",
    )
    documentary_ref = st.text_input(
        "Referência documental adicional",
        value="",
        key=f"c02_{ns}_prof_doc",
    )
    identity = build_professional_identity(
        name=prof_name,
        registration=registration,
        council=council,
        art_rrt=art_rrt,
        documentary_reference=documentary_ref,
    )
    if identity["art_rrt_format_valid"]:
        st.caption("Formato de ART/RRT aparente — não é autenticação junto ao conselho.")
    return {"inspection": inspection, "identity": identity}


def _qualification_evidence_widgets(*, ns: str, profile: Mapping[str, Any]) -> dict:
    """Collect C05 evidence and professional findings without asserting validity.

    Profile evidence is an auditable reference supplied by the professional. It
    is not a boolean approval. Non-automatable assumptions carry an explicit
    satisfied/violated decision and a justification; blank/pending entries stay
    absent and therefore remain pending in C05.
    """
    profile_evidence: dict[str, str] = {}
    professional_findings: dict[str, dict[str, Any]] = {}
    with st.expander("Evidências do perfil e achados profissionais", expanded=False):
        st.caption(
            "Referências vazias não cumprem requisitos. Identifique o arquivo ou "
            "registro íntegro; a emissão posterior deve carregar os bytes autorizados."
        )
        for requirement in profile.get("requirements") or []:
            if not isinstance(requirement, Mapping) or not requirement.get("id"):
                continue
            requirement_id = str(requirement["id"])
            evidence_ref = st.text_input(
                f"Referência de evidência — {requirement_id}",
                value="",
                key=f"p02_{ns}_profile_evidence_{requirement_id}",
                help=str(requirement.get("requirement") or ""),
            ).strip()
            if evidence_ref:
                profile_evidence[requirement_id] = evidence_ref

        st.markdown("##### Exames profissionais dos pressupostos")
        st.caption(
            "A conclusão é um ato informado pelo profissional, não inferido pelo software. "
            "Sem justificativa registrada, a regra permanece pendente."
        )
        for rule_id, label in PROFESSIONAL_FINDING_RULES:
            decision = st.selectbox(
                f"Conclusão profissional — {label}",
                options=("pending", "satisfied", "violated"),
                format_func=lambda value: {
                    "pending": "Pendente — nenhuma conclusão registrada",
                    "satisfied": "Satisfeito — conclusão do profissional",
                    "violated": "Violado — conclusão do profissional",
                }[value],
                key=f"p02_{ns}_professional_finding_{rule_id}",
            )
            justification = st.text_area(
                f"Justificativa profissional — {label}",
                value="",
                key=f"p02_{ns}_professional_justification_{rule_id}",
            ).strip()
            if decision != "pending":
                professional_findings[rule_id] = {
                    "satisfied": decision == "satisfied",
                    "justification": justification,
                }
    return {
        "profile_evidence": profile_evidence,
        "professional_findings": professional_findings,
    }


def upload_form(
    preview_provider: Optional[Callable[..., dict]] = None,
    cached_preview: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Fluxo profissional: encomenda → amostra → avaliando/vistoria.

    Não lê CSV/Excel para interpretar colunas. Se a prévia falhar por
    conexão, devolve erro e não fabrica uma leitura local. O mapeamento
    fica vinculado ao arquivo/esquema — outro arquivo não herda o imóvel anterior.
    """
    encomenda_state = _encomenda_widgets()
    st.subheader("2. Amostra e evidências")
    st.markdown("**1. Preparação da amostra**")
    st.caption("A interpretação vem da prévia da API. Esta tela não relê a planilha.")
    uploaded_file = st.file_uploader(
        "Arquivo de dados de mercado (CSV ou Excel)",
        type=["csv", "xlsx", "xls"],
        help="A interpretação das colunas vem da prévia da API, não de uma leitura paralela nesta tela.",
        key="p02_uploader",
    )

    locale = st.selectbox(
        "Formato numérico e de texto da planilha",
        options=list(VALID_LOCALES),
        index=0,
        help="Enviado em import_options. A API interpreta; esta tela não relê o arquivo.",
    )
    delimiter = st.text_input("Separador (opcional)", value="", help="Vazio = detectar automaticamente.")
    encoding = st.text_input("Codificação (opcional)", value="", help="Vazio = detectar automaticamente.")

    import_options = {
        "locale": locale,
        "delimiter": delimiter or None,
        "encoding": encoding or None,
    }

    preview = cached_preview or st.session_state.get("c09_preview")
    connection_error = None
    preview_error = None

    binding_token = mapping_binding_token(
        filename=getattr(uploaded_file, "name", None),
        nbytes=len(uploaded_file.getvalue()) if uploaded_file is not None else None,
        import_options=import_options,
    )
    ns = widget_namespace(binding_token) if uploaded_file is not None else "none"

    if uploaded_file is not None:
        previous_token = st.session_state.get("p02_preview_token") or st.session_state.get("c09_preview_token")
        if previous_token != binding_token:
            flags, dropped = merge_invalidation(dict(st.session_state), "file")
            for key, value in flags.items():
                st.session_state[key] = value
            for key in dropped:
                st.session_state.pop(key, None)
            preview = None
        if preview is None:
            if preview_provider is None:
                connection_error = PREVIEW_CONNECTION_ERROR
            else:
                draft = build_request_spec(
                    target_col="",
                    candidate_cols=None,
                    roles={},
                    import_options=import_options,
                )
                try:
                    preview = preview_provider(
                        uploaded_file.getvalue(),
                        uploaded_file.name,
                        draft,
                    )
                    fingerprint = schema_fingerprint(preview)
                    binding_token = mapping_binding_token(
                        filename=uploaded_file.name,
                        nbytes=len(uploaded_file.getvalue()),
                        import_options=import_options,
                        input_sha256=(preview or {}).get("input_sha256"),
                        schema_fingerprint=fingerprint,
                    )
                    ns = widget_namespace(binding_token)
                    st.session_state["c09_preview"] = preview
                    st.session_state["c09_preview_token"] = binding_token
                    st.session_state["p02_preview"] = preview
                    st.session_state["p02_preview_token"] = binding_token
                except ApiConnectionError as exc:
                    connection_error = str(exc) or PREVIEW_CONNECTION_ERROR
                    preview = None
                    for key, value in preview_failure_clears_interpretation(dict(st.session_state)).items():
                        if value is True or key.endswith("_cleared"):
                            st.session_state[key] = value
                    st.session_state.pop("c09_preview", None)
                    st.session_state.pop("p02_preview", None)
                except ApiResponseError as exc:
                    preview_error = str(exc)
                    preview = None
                    st.session_state.pop("c09_preview", None)
                    st.session_state.pop("p02_preview", None)
                    st.session_state["p02_preview_error_cleared"] = True
                except Exception as exc:  # noqa: BLE001 — falha de rede inesperada vira erro de conexão
                    connection_error = PREVIEW_CONNECTION_ERROR
                    preview = None
                    st.session_state["c09_preview_exception"] = repr(exc)
                    st.session_state.pop("c09_preview", None)
                    st.session_state.pop("p02_preview", None)

    if connection_error:
        st.error(connection_error)
        return {
            "uploaded_file": uploaded_file,
            "request_spec": None,
            "subject": None,
            "dispatch": {"ok": False, "can_dispatch": False, "blocking": [{"code": "connection", "message": connection_error}], "pending": []},
            "preview": None,
            "connection_error": connection_error,
            "preview_error": preview_error,
            "execute": False,
            "encomenda": encomenda_state.get("encomenda"),
            "qualification_profile": encomenda_state.get("profile"),
        }

    if preview_error:
        st.error(preview_error)

    if uploaded_file is None:
        st.info("Envie o arquivo para revisar a interpretação devolvida pela API.")
        return {
            "uploaded_file": None,
            "request_spec": None,
            "subject": None,
            "dispatch": {"ok": False, "can_dispatch": False, "blocking": [], "pending": []},
            "preview": None,
            "connection_error": None,
            "preview_error": preview_error,
            "execute": False,
            "encomenda": encomenda_state.get("encomenda"),
            "qualification_profile": encomenda_state.get("profile"),
        }

    if preview is None:
        st.warning("A prévia ainda não está disponível. Sem ela, a execução não é disparada.")
        return {
            "uploaded_file": uploaded_file,
            "request_spec": None,
            "subject": None,
            "dispatch": {
                "ok": False,
                "can_dispatch": False,
                "blocking": [{"code": "preview_unavailable", "message": preview_error or PREVIEW_CONNECTION_ERROR}],
                "pending": [],
            },
            "preview": None,
            "connection_error": None,
            "preview_error": preview_error,
            "execute": False,
            "encomenda": encomenda_state.get("encomenda"),
            "qualification_profile": encomenda_state.get("profile"),
        }

    model = preview_to_form_model(preview)
    st.markdown("#### Interpretação recebida")
    if model["issues"]:
        for issue in model["issues"]:
            severity = (issue or {}).get("severity") or "info"
            message = (issue or {}).get("message") or str(issue)
            if severity == "error":
                st.error(message)
            elif severity == "warning":
                st.warning(message)
            else:
                st.info(message)
    else:
        st.caption("Nenhum aviso de interpretação na prévia.")

    if model["columns"]:
        st.dataframe(
            [
                {
                    "Coluna": name,
                    "Tipo": (model["column_map"].get(name) or {}).get("kind") or "",
                    "Unidade detectada": (model["column_map"].get(name) or {}).get("unit") or "não informada",
                    "Exemplo original": _sample_raw(model["column_map"].get(name)),
                    "Exemplo interpretado": _sample_interpreted(model["column_map"].get(name)),
                }
                for name in model["columns"]
            ],
            use_container_width=True,
            hide_index=True,
        )

    sample_rows = interpreted_sample_rows(preview)
    if sample_rows:
        st.markdown("#### Amostra interpretada")
        st.caption("Primeiras linhas devolvidas pela prévia — não é uma leitura local do arquivo.")
        st.dataframe(sample_rows, use_container_width=True, hide_index=True)

    st.markdown("#### Alvo, características e unidades")
    st.caption("Mapeamento editável, vinculado a este arquivo e ao esquema da prévia.")
    columns = model["columns"]
    suggested = suggest_roles(model["column_map"])
    target_options = columns or [""]
    default_target = next((c for c, role in suggested.items() if role == "target"), target_options[0] if target_options else "")
    target_col = st.selectbox(
        "Variável-alvo (valor)",
        options=target_options,
        index=target_options.index(default_target) if default_target in target_options else 0,
        help="Coluna do valor observado. Ausências desta coluna nunca são imputadas.",
    )

    roles: dict = {}
    units: dict = {}
    for name in columns:
        meta = model["column_map"].get(name) or {}
        original = meta.get("original_name") or name
        cols_role, cols_unit = st.columns([2, 1])
        default_role = "target" if name == target_col else suggested.get(name, "predictor")
        if name == target_col:
            default_role = "target"
        with cols_role:
            roles[name] = st.selectbox(
                f"Papel de «{original}»",
                options=list(VALID_ROLES),
                index=list(VALID_ROLES).index(default_role) if default_role in VALID_ROLES else 1,
                key=f"p02_{ns}_role_{name}",
            )
        with cols_unit:
            detected = meta.get("unit") or ""
            entered = st.text_input(
                f"Unidade de «{original}»",
                value=detected,
                key=f"p02_{ns}_unit_{name}",
                help="Vazio = unidade desconhecida (permanece pendente).",
            )
            if entered:
                units[name] = entered
        if roles[name] == "target" and name != target_col:
            roles[name] = "predictor"
    roles[target_col] = "target"

    auto_candidates = st.checkbox(
        "Seleção automática das variáveis autorizadas conforme o papel preditor",
        value=False,
        key=f"p02_{ns}_auto_candidates",
        help="Marcado: candidate_cols=null. Desmarcado: a lista abaixo é a autorização explícita.",
    )
    predictor_names = [n for n, role in roles.items() if role == "predictor"]
    default_selected = [
        n for n in predictor_names
        if (model["column_map"].get(n) or {}).get("kind") != "identifier"
    ]
    selected_candidates = st.multiselect(
        "Variáveis autorizadas para o modelo",
        options=predictor_names,
        default=default_selected,
        disabled=auto_candidates,
        key=f"p02_{ns}_candidates",
        help="Lista vazia significa nenhuma autorizada, nunca todas as colunas.",
    )
    if auto_candidates:
        candidate_cols = None
        st.caption("Seleção automática por papel (candidate_cols ausente / nulo).")
    else:
        candidate_cols = candidate_cols_from_selection(selected_candidates, auto=False)
        if candidate_cols == []:
            st.warning(EMPTY_SELECTION_MESSAGE)

    unused = unused_columns_view(
        model["column_map"],
        roles=roles,
        candidate_cols=None if auto_candidates else selected_candidates,
        target_col=target_col,
        preview_issues=model.get("issues"),
    )
    st.markdown("#### Dados não utilizados")
    if unused:
        st.dataframe(
            [
                {
                    "Coluna": item.get("original_name") or item["name"],
                    "Razão": item["reason"],
                }
                for item in unused
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("Nenhuma coluna candidata ficou de fora sem razão visível.")

    exclusions = list(st.session_state.get("c02_justified_exclusions") or [])
    with st.expander("Exclusões justificadas da amostra", expanded=False):
        st.caption("Exclusão não é automática para melhorar R²/grau. Motivo, responsável e efeito são obrigatórios.")
        excl_row = st.text_input("Identificador do registro excluído", value="", key=f"c02_{ns}_excl_row")
        excl_reason = st.text_input("Motivo da exclusão", value="", key=f"c02_{ns}_excl_reason")
        excl_who = st.text_input("Profissional que decide a exclusão", value="", key=f"c02_{ns}_excl_who")
        excl_effect = st.text_input("Efeito da exclusão (n, grau, etc.)", value="", key=f"c02_{ns}_excl_effect")
        if excl_row and excl_reason and excl_who:
            try:
                item = record_justified_exclusion(
                    row_id=excl_row,
                    reason=excl_reason,
                    reviewer=excl_who,
                    effect=excl_effect,
                    fingerprint=st.session_state.get("p02_form_fingerprint"),
                )
                identity_key = (str(item["row_id"]), item["reason"], item["reviewer"])
                seen = {(str(e.get("row_id")), e.get("reason"), e.get("reviewer")) for e in exclusions}
                if identity_key not in seen:
                    exclusions.append(item)
                    st.session_state["c02_justified_exclusions"] = exclusions
                st.caption(
                    f"Exclusão de {excl_row} registrada com motivo, responsável e efeito — não é filtro silencioso."
                )
            except ValueError as exc:
                st.error(str(exc))
        if exclusions:
            st.dataframe(
                [
                    {
                        "Registro": item.get("row_id"),
                        "Motivo": item.get("reason"),
                        "Profissional": item.get("reviewer"),
                        "Efeito": item.get("effect"),
                    }
                    for item in exclusions
                ],
                use_container_width=True,
                hide_index=True,
            )

    target_unit = st.text_input(
        "Unidade do valor-alvo",
        value=units.get(target_col, ""),
        key=f"p02_{ns}_target_unit",
        help="Campo próprio. Vazio permanece pendente — não se presume BRL ou BRL/m².",
    )
    if target_unit:
        units[target_col] = target_unit

    col_ref, col_insp = st.columns(2)
    with col_ref:
        has_reference = st.checkbox(
            "Informar data da avaliação (data-base)",
            value=False,
            key=f"p02_{ns}_has_reference",
        )
        reference_date = None
        if has_reference:
            reference_date = _iso_or_none(
                st.date_input("Data da avaliação (data-base)", key=f"p02_{ns}_reference_date")
            )
        else:
            st.caption("Data-base pendente. Não se usa a data de hoje nem a data de emissão.")
    with col_insp:
        has_inspection = st.checkbox(
            "Informar data da vistoria",
            value=False,
            key=f"p02_{ns}_has_inspection",
        )
        inspection_date = None
        if has_inspection:
            inspection_date = _iso_or_none(
                st.date_input("Data da vistoria", key=f"p02_{ns}_inspection_date")
            )
        else:
            st.caption("Data da vistoria é campo próprio, distinto da data-base e da emissão.")

    applicant = encomenda_state.get("applicant") or ""
    purpose = encomenda_state.get("purpose") or ""
    st.caption(f"Solicitante e finalidade vêm da encomenda: {applicant or 'não informado'} / {purpose or 'não informada'}.")

    degree_choice = st.selectbox(
        "Grau mínimo solicitado",
        options=["not_requested", 1, 2, 3],
        format_func=lambda value: "Não solicitar" if value == "not_requested" else f"Grau {value}",
        index=0,
        key=f"p02_{ns}_degree",
        help=DEGREE_HELP,
    )
    degree = None if degree_choice == "not_requested" else int(degree_choice)
    st.caption(DEGREE_HELP)

    method_ids = list(SUPPORTED_EVALUATION_METHOD_IDS)
    method_labels = {item[0]: item[1] for item in SUPPORTED_EVALUATION_METHODS}
    evaluation_method = st.selectbox(
        "Validação independente",
        options=method_ids,
        format_func=lambda value: method_labels.get(value, value),
        index=0,
        key=f"p02_{ns}_eval_method",
        help=METHOD_HELP,
    )
    st.caption(METHOD_HELP)
    if evaluation_method == "holdout":
        st.caption(HOLD_OUT_HELP)

    adopted_value_method = st.selectbox(
        "Política do valor adotado",
        options=("not_declared", "point"),
        format_func=lambda value: {
            "not_declared": "Não declarada — valor adotado permanece pendente",
            "point": "Adotar a estimativa pontual calculada",
        }[value],
        key=f"p02_{ns}_adopted_value_method",
        help=(
            "A política é um insumo explícito e reproduzível. Selecioná-la não "
            "constitui aprovação profissional do conteúdo."
        ),
    )
    value_policy_source = ""
    if adopted_value_method != "not_declared":
        value_policy_source = st.text_input(
            "Fundamento da política do valor adotado",
            value="",
            key=f"p02_{ns}_adopted_value_source",
            help="Identifique a encomenda, procedimento ou decisão que fundamenta a política.",
        ).strip()
    value_policy = (
        {
            "adopted": {"method": adopted_value_method},
            "source": value_policy_source,
        }
        if adopted_value_method != "not_declared"
        else None
    )

    missing_predictors = st.selectbox(
        "Política para características ausentes nos preditores",
        options=["complete_case", "declared_method_on_train"],
        index=0,
        key=f"p02_{ns}_missing_pred",
        help="O alvo nunca é imputado. Exclusões precisam ser declaradas.",
    )
    grau_item1 = st.selectbox(
        "Grau declarado de caracterização do imóvel avaliando (item documental)",
        options=[None, 0, 1, 2, 3],
        index=0,
        key=f"p02_{ns}_grau_item1",
        format_func=lambda v: "Não declarado" if v is None else str(v),
        help="Declaração do profissional, não verificação automática da planilha.",
    )
    grau_item3 = st.selectbox(
        "Grau declarado de identificação dos dados de mercado (item documental)",
        options=[None, 0, 1, 2, 3],
        index=0,
        key=f"p02_{ns}_grau_item3",
        format_func=lambda v: "Não declarado" if v is None else str(v),
        help="Declaração do profissional. Pontuação documental declarada não vira comprovação.",
    )

    item1_ref = st.text_input("Evidência da caracterização do avaliando", key=f"p02_{ns}_item1_ref")
    item3_ref = st.text_input("Evidência da identificação dos dados de mercado", key=f"p02_{ns}_item3_ref")
    qualification_evidence = _qualification_evidence_widgets(
        ns=ns,
        profile=encomenda_state.get("profile") or {},
    )
    request_spec = build_request_spec(
        target_col=target_col,
        candidate_cols=candidate_cols,
        roles=roles,
        units=units,
        import_options=import_options,
        missing_policy={"target": "never_impute", "predictors": missing_predictors},
        reference_date=reference_date,
        inspection_date=inspection_date,
        target_unit=target_unit,
        applicant=applicant,
        purpose=purpose,
        minimum_fundamentacao_grade=degree,
        evaluation_method=evaluation_method,
        documentary={
            "item1_grade_declared": grau_item1,
            "item3_grade_declared": grau_item3,
            "provenance": "declared_by_user",
            "item1_provenance": {"source": "professional_declaration", "evidence_ref": item1_ref} if item1_ref else None,
            "item3_provenance": {"source": "professional_declaration", "evidence_ref": item3_ref} if item3_ref else None,
        },
        rights=encomenda_state.get("rights"),
        recipient_id=encomenda_state.get("recipient_id"),
        value_basis=encomenda_state.get("value_basis"),
        asset_scope=encomenda_state.get("asset_scope"),
        qualification_profile=encomenda_state.get("profile"),
        justified_exclusions=exclusions,
        profile_evidence=qualification_evidence["profile_evidence"],
        professional_findings=qualification_evidence["professional_findings"],
        value_policy=value_policy,
        synthetic_test_only=bool(encomenda_state.get("synthetic_test_only")),
    )

    policies = policies_on_the_wire(request_spec)
    with st.expander("Políticas que serão enviadas no pedido", expanded=False):
        st.caption("Somente o que entra no RequestSpec. Controle que não muda o pedido não aparece aqui.")
        st.json({
            "search_policy": policies["search_policy"],
            "evaluation_policy": {
                k: v for k, v in policies["evaluation_policy"].items() if k != "documentary"
            },
            "missing_policy": policies["missing_policy"],
            "outlier_policy": policies["outlier_policy"],
        })
        cost = cost_estimate_from_payload(preview)
        if cost:
            st.write("Estimativa de custo devolvida pela API:", cost["value"])

    evidence_state = _vistoria_and_identity_widgets(ns=ns, inspection_date=inspection_date)
    request_spec["inspection"] = evidence_state.get("inspection")
    request_spec["professional_identity"] = evidence_state.get("identity")
    st.markdown("**2. Imóvel avaliando**")
    st.caption(
        "Use as variáveis-base do esquema (categorias, números já interpretados, "
        "ausências e unidades). Não preencha colunas dummy. "
        "O botão de executar abaixo envia estes valores junto com o disparo."
    )
    feature_schema = _feature_schema_from_column_map(model["column_map"], target_col, roles, units)
    preview_cols = ((model.get("feature_schema") or {}).get("columns") or {})
    for name, meta in (feature_schema.get("columns") or {}).items():
        prev = preview_cols.get(name) or {}
        for key in ("kind", "categories", "unit", "group_id", "reference_category"):
            if prev.get(key) and not meta.get(key):
                meta[key] = prev[key]
    raw_values: dict = {}
    resolutions: dict = {}
    schema_columns = (feature_schema.get("columns") or {})
    dummies = dummy_column_names(feature_schema)
    execute_clicked = False

    with st.form(f"p02_{ns}_avaliando_executar", clear_on_submit=False):
        for internal, meta in schema_columns.items():
            meta = meta or {}
            if meta.get("role") in {"target", "identifier", "excluded", "source", "date"} or internal in dummies:
                continue
            original = meta.get("original_name") or internal
            kind = str(meta.get("kind") or "").lower()
            unit = meta.get("unit")
            unit_note = f" (unidade: {unit})" if unit else " (unidade não informada no esquema)"
            categories = meta.get("categories") or []
            if kind in {"categorical", "category"}:
                options = list(categories) + ["(ausente)", "(categoria não suportada)"]
                chosen = st.selectbox(
                    f"{original}{unit_note}",
                    options=options,
                    key=f"p02_{ns}_subj_{internal}",
                )
                if chosen == "(ausente)":
                    raw_values[internal] = None
                elif chosen == "(categoria não suportada)":
                    custom = st.text_input(
                        f"Categoria informada para «{original}» (não está no esquema)",
                        key=f"p02_{ns}_subj_custom_{internal}",
                    )
                    raw_values[internal] = custom or "__unsupported__"
                    resolution = st.radio(
                        f"Resolução para categoria não suportada de «{original}»",
                        options=["pendente", "map_to_supported", "exclude", "abort"],
                        key=f"p02_{ns}_res_{internal}",
                        help="Coluna/categoria fora de suporte exige decisão explícita.",
                    )
                    mapped = None
                    if resolution == "map_to_supported" and categories:
                        mapped = st.selectbox(
                            f"Mapear «{original}» para",
                            options=list(categories),
                            key=f"p02_{ns}_map_{internal}",
                        )
                    if resolution != "pendente":
                        resolutions[internal] = {"action": resolution, "mapped_value": mapped}
                else:
                    raw_values[internal] = chosen
            else:
                entered = st.text_input(
                    f"{original}{unit_note}",
                    value="",
                    key=f"p02_{ns}_subj_{internal}",
                    placeholder="ex.: 73,5",
                    help="Número pode permanecer no formato original; a interpretação é da API/C02, não desta tela.",
                )
                raw_values[internal] = entered if entered != "" else None

        extra_unsupported = st.text_input(
            "Coluna adicional não listada no esquema (deixe vazio se não houver)",
            value="",
            help="Se preenchida, exige resolução explícita. Não gera dummy.",
        )
        if extra_unsupported:
            extra_value = st.text_input("Valor da coluna adicional", value="")
            raw_values[extra_unsupported] = extra_value
            extra_res = st.radio(
                "Resolução para coluna não suportada",
                options=["pendente", "exclude", "abort"],
                key=f"p02_{ns}_res_extra_col",
            )
            if extra_res != "pendente":
                resolutions[extra_unsupported] = {"action": extra_res}

        execute_clicked = st.form_submit_button(
            "Executar avaliação",
            help="Envia o avaliando preenchido neste passo. Não dispara com campos ainda não confirmados.",
        )

    subject = build_subject_payload(feature_schema, raw_values, resolutions=resolutions)
    for iss in subject.get("issues") or []:
        if iss.get("requires_resolution"):
            st.error(iss.get("message"))
        elif iss.get("code") == "subject_absence":
            st.caption(iss.get("message"))
        elif iss.get("severity") == "warning":
            st.warning(iss.get("message"))

    dispatch = validate_dispatch(request_spec, subject, preview=preview)
    if dispatch["blocking"]:
        for item in dispatch["blocking"]:
            st.error(item["message"])
    for item in dispatch["pending"]:
        st.info(item["message"])

    fingerprint = execution_fingerprint(
        input_sha256=(preview or {}).get("input_sha256"),
        filename=getattr(uploaded_file, "name", None),
        nbytes=len(uploaded_file.getvalue()) if uploaded_file is not None else None,
        request_spec=request_spec,
        subject=subject,
    )
    return {
        "uploaded_file": uploaded_file,
        "request_spec": request_spec,
        "subject": subject,
        "dispatch": dispatch,
        "preview": preview,
        "connection_error": None,
        "preview_error": preview_error,
        "degree": degree,
        "evaluation_method": evaluation_method,
        "feature_schema": feature_schema,
        "execute": bool(execute_clicked),
        "binding_token": binding_token,
        "unused_columns": unused,
        "policies": policies,
        "fingerprint": fingerprint,
        "stale_reason": st.session_state.get("p02_result_stale_reason"),
        "encomenda": encomenda_state.get("encomenda"),
        "qualification_profile": encomenda_state.get("profile"),
        "inspection": evidence_state.get("inspection") or empty_inspection_record(),
        "professional_identity": evidence_state.get("identity"),
        "justified_exclusions": exclusions,
    }


def _sample_raw(meta: Optional[Mapping[str, Any]]) -> str:
    if not meta:
        return ""
    sample = meta.get("sample_raw") or meta.get("sample") or []
    if not sample:
        return ""
    return str(sample[0])


def _sample_interpreted(meta: Optional[Mapping[str, Any]]) -> str:
    if not meta:
        return ""
    sample = meta.get("sample_interpreted") or []
    if not sample:
        return ""
    value = sample[0]
    return "" if value is None else str(value)


def _feature_schema_from_column_map(
    column_map: Mapping[str, Any],
    target_col: str,
    roles: Mapping[str, str],
    units: Mapping[str, Any],
) -> dict:
    """Esquema mínimo a partir da prévia, sem inventar dummies."""
    columns = {}
    for name, meta in (column_map or {}).items():
        meta = meta or {}
        columns[name] = {
            "original_name": meta.get("original_name") or name,
            "role": roles.get(name) or ("target" if name == target_col else "predictor"),
            "kind": meta.get("kind"),
            "unit": units.get(name) or meta.get("unit"),
            "group_id": meta.get("group_id"),
            "categories": meta.get("categories"),
            "reference_category": meta.get("reference_category"),
        }
    return {
        "version": 1,
        "columns": columns,
        "groups": {},
        "target": {"column": target_col, "unit": units.get(target_col) or ""},
    }
