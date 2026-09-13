"""Formulário da avaliação e contrato HTTP C10/C11 (campanha C09).

A leitura semântica do arquivo e a codificação de categorias NÃO são feitas
aqui: /preview e o esquema de C02 são a fonte. Este módulo apenas:

- monta RequestSpec / payload do avaliando a partir das escolhas do usuário;
- valida o disparo (lista vazia = nenhuma autorizada, nunca todas);
- consome a API com timeout e recuperação por job_id.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Mapping, MutableMapping, Optional, Sequence

import httpx
import pandas as pd
import streamlit as st

SCHEMA_VERSION = "MP/1"
DEFAULT_API_URL = os.environ.get("MODELA_API_URL", "http://127.0.0.1:8000")
DEFAULT_TIMEOUT = float(os.environ.get("MODELA_API_TIMEOUT", "30"))

VALID_ROLES = ("target", "predictor", "identifier", "source", "date", "excluded")
VALID_LOCALES = ("auto", "pt-BR", "en-US")
ACTIVE_JOB_STATES = frozenset({"queued", "running"})
TERMINAL_JOB_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})

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
    "promessa de emissão nem de classificação integral."
)


class ApiConnectionError(Exception):
    """API inacessível, tempo esgotado ou conexão fechada."""


class ApiResponseError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def _error_payload_body(payload: Any) -> dict:
    if isinstance(payload, Mapping):
        detail = payload.get("detail")
        if isinstance(detail, Mapping):
            return dict(detail)
        return dict(payload)
    return {}


def _issue_lines(issues: Any) -> list:
    lines = []
    if not isinstance(issues, list):
        return lines
    for item in issues:
        if isinstance(item, Mapping):
            code = item.get("code") or ""
            message = item.get("message") or ""
            if code and message:
                lines.append(f"{code}: {message}")
            elif code:
                lines.append(str(code))
            elif message:
                lines.append(str(message))
        elif item:
            lines.append(str(item))
    return lines


def recommended_preview_action(status_code: Optional[int], payload: Any = None) -> str:
    body = _error_payload_body(payload)
    codes = []
    issues = body.get("issues")
    if isinstance(issues, list):
        codes = [str(item.get("code") or "") for item in issues if isinstance(item, Mapping)]
    if status_code == 413 or "FILE_TOO_LARGE" in codes:
        return "Reduza o arquivo ou o limite MP_MAX_UPLOAD_BYTES e envie de novo."
    if status_code == 503 or "PEER_UNAVAILABLE" in codes:
        return (
            "A API não está pronta para a prévia (dependência ingest_market ausente). "
            "Reinicie com `uvicorn backend.api:app --reload` na versão corrigida e "
            "confirme GET /ready."
        )
    if status_code == 422:
        return (
            "O arquivo foi recusado na interpretação. Verifique extensão, "
            "assinatura XLSX/CSV e se a primeira aba tem cabeçalho."
        )
    if "MISSING_FIELD" in codes or "TARGET_ROLE_MISSING" in codes:
        return (
            "Corrija os campos indicados. A prévia admite alvo ainda não escolhido; "
            "a execução (POST /jobs) continua exigindo variável-alvo."
        )
    if status_code == 400:
        return "Corrija os campos indicados e envie o arquivo novamente."
    return "Revise a mensagem acima e tente novamente após corrigir a causa."


def format_preview_error(status_code: Optional[int], payload: Any, *, fallback: str = "") -> str:
    """Texto único para 400/422/503: HTTP, error, códigos, mensagens, próxima ação."""
    body = _error_payload_body(payload)
    error = body.get("error")
    if not error and isinstance(payload, str) and payload.strip():
        error = payload.strip()
    if not error:
        error = fallback or "A prévia não pôde ser obtida."
    lines = [f"A prévia não pôde ser obtida (HTTP {status_code})." if status_code is not None else error]
    if status_code is not None:
        lines.append(f"HTTP {status_code}")
    if error and error not in lines[0]:
        lines.append(f"error: {error}")
    elif error and status_code is not None:
        lines.append(f"error: {error}")
    issue_lines = _issue_lines(body.get("issues"))
    if issue_lines:
        lines.append("issues:")
        lines.extend(f"- {item}" for item in issue_lines)
    lines.append(f"Próxima ação: {recommended_preview_action(status_code, payload)}")
    return "\n".join(lines)


class DuplicateExecutionError(Exception):
    """Tentativa de POST /jobs enquanto já há execução ativa."""


class DispatchBlocked(Exception):
    """Disparo recusado por inconsistência do RequestSpec/avaliando."""


# ---------------------------------------------------------------------------
# Heurística legada — só sugere papel padrão; nunca restringe a escolha.
# ---------------------------------------------------------------------------

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
    column_map = dict(preview.get("column_map") or {})
    feature_schema = dict(preview.get("feature_schema") or {})
    issues = list(preview.get("issues") or [])
    columns = list(column_map.keys())
    if not columns:
        columns = list((feature_schema.get("columns") or {}).keys())
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
    return {
        "mode": "default",
        "budget": None,
        "objective": "minimum_fundamentacao_grade",
        "seed": None,
        "minimum_fundamentacao_grade": minimum_grade,
    }


def default_evaluation_policy(
    minimum_grade: Optional[int] = None,
    *,
    documentary: Optional[Mapping[str, Any]] = None,
) -> dict:
    policy = {
        "method": None,
        "partitions": None,
        "groups": None,
        "seed": None,
        "minimum_fundamentacao_grade": minimum_grade,
    }
    if documentary is not None:
        policy["documentary"] = dict(documentary)
    return policy


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
) -> dict:
    """Monta RequestSpec MP/1. Não presume BRL, BRL/m² nem data de hoje.

    candidate_cols=None → seleção automática por papel.
    candidate_cols=[] → nenhuma variável autorizada (nunca expandido para todas).
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

    search = dict(search_policy or default_search_policy(minimum_fundamentacao_grade))
    evaluation = dict(
        evaluation_policy
        or default_evaluation_policy(minimum_fundamentacao_grade, documentary=documentary)
    )
    if minimum_fundamentacao_grade is not None:
        search.setdefault("minimum_fundamentacao_grade", minimum_fundamentacao_grade)
        evaluation.setdefault("minimum_fundamentacao_grade", minimum_fundamentacao_grade)
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

    return {
        "schema_version": SCHEMA_VERSION,
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
        self.status_url: Optional[str] = None
        self.last_status: Optional[dict] = None
        self.last_snapshot: Optional[dict] = None
        self.last_error: Optional[str] = None

    def _own_client(self) -> httpx.Client:
        if self._http is not None:
            return self._http
        return httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def _call(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
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
                format_preview_error(response.status_code, payload),
                status_code=response.status_code,
                payload=payload,
            )
        payload = _json_or_text(response)
        if not isinstance(payload, dict):
            raise ApiResponseError("Prévia em formato inesperado.", status_code=response.status_code, payload=payload)
        return payload

    def submit_job(
        self,
        file_bytes: bytes,
        filename: str,
        request_spec: Mapping[str, Any],
        subject: Optional[Mapping[str, Any]] = None,
        content_type: str = "application/octet-stream",
    ) -> dict:
        if self.is_active():
            raise DuplicateExecutionError(
                "Já existe uma execução em andamento para este trabalho. "
                "Aguarde, cancele ou recupere o resultado antes de disparar outra."
            )
        files = {"file": (filename, file_bytes, content_type)}
        data = {"request_json": request_spec_json(request_spec)}
        if subject is not None:
            data["subject_json"] = json.dumps(subject, ensure_ascii=False, allow_nan=False)
        response = self._call("POST", "/jobs", files=files, data=data)
        payload = _json_or_text(response)
        if response.status_code not in (200, 202) or not isinstance(payload, dict) or not payload.get("job_id"):
            raise ApiResponseError(
                f"Não foi possível iniciar o trabalho (HTTP {response.status_code}).",
                status_code=response.status_code,
                payload=payload,
            )
        self.job_id = str(payload["job_id"])
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

        Nunca descarta job_id, mesmo se o GET falhar.
        """
        jid = job_id or self.job_id
        if not jid:
            return None
        self.job_id = jid
        status = self.get_status(jid)
        if status.get("result_available"):
            try:
                self.last_snapshot = self.get_result(jid)
            except (ApiConnectionError, ApiResponseError):
                pass
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
        return payload

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
    job_client.last_status = session.get("c09_job_status")
    job_client.last_snapshot = session.get("c09_snapshot")
    return job_client


def persist_client_to_session(session: MutableMapping[str, Any], job_client: JobClient) -> None:
    session["c09_job_id"] = job_client.job_id
    session["c09_job_status"] = job_client.last_status
    session["c09_snapshot"] = job_client.last_snapshot


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


def upload_form(
    preview_provider: Optional[Callable[..., dict]] = None,
    cached_preview: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Fluxo: importar → papéis/unidades/alvo → avaliando.

    Não lê CSV/Excel para interpretar colunas. Se a prévia falhar por
    conexão, devolve erro e não fabrica uma leitura local.
    """
    st.subheader("1. Importar e revisar interpretação")
    uploaded_file = st.file_uploader(
        "Arquivo de dados de mercado (CSV ou Excel)",
        type=["csv", "xlsx", "xls"],
        help="A interpretação das colunas vem da prévia da API, não de uma leitura paralela nesta tela.",
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

    if uploaded_file is not None:
        file_token = f"{uploaded_file.name}:{len(uploaded_file.getvalue())}:{locale}:{delimiter}:{encoding}"
        if st.session_state.get("c09_preview_token") != file_token:
            st.session_state.pop("c09_preview", None)
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
                    st.session_state["c09_preview"] = preview
                    st.session_state["c09_preview_token"] = file_token
                except ApiConnectionError as exc:
                    connection_error = str(exc) or PREVIEW_CONNECTION_ERROR
                    preview = None
                except ApiResponseError as exc:
                    preview_error = format_preview_error(
                        exc.status_code, exc.payload, fallback=str(exc)
                    )
                    preview = None
                except Exception as exc:  # noqa: BLE001 — falha de rede inesperada vira erro de conexão
                    connection_error = PREVIEW_CONNECTION_ERROR
                    preview = None
                    st.session_state["c09_preview_exception"] = repr(exc)

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

    st.subheader("2. Definir papéis, unidades e alvo")
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
                key=f"c09_role_{name}",
            )
        with cols_unit:
            detected = meta.get("unit") or ""
            entered = st.text_input(
                f"Unidade de «{original}»",
                value=detected,
                key=f"c09_unit_{name}",
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
        help="Lista vazia significa nenhuma autorizada, nunca todas as colunas.",
    )
    if auto_candidates:
        candidate_cols = None
        st.caption("Seleção automática por papel (candidate_cols ausente / nulo).")
    else:
        candidate_cols = candidate_cols_from_selection(selected_candidates, auto=False)
        if candidate_cols == []:
            st.warning(EMPTY_SELECTION_MESSAGE)

    target_unit = st.text_input(
        "Unidade do valor-alvo",
        value=units.get(target_col, ""),
        help="Campo próprio. Vazio permanece pendente — não se presume BRL ou BRL/m².",
    )
    if target_unit:
        units[target_col] = target_unit

    col_ref, col_insp = st.columns(2)
    with col_ref:
        has_reference = st.checkbox("Informar data da avaliação (data-base)", value=False)
        reference_date = None
        if has_reference:
            reference_date = _iso_or_none(st.date_input("Data da avaliação (data-base)"))
        else:
            st.caption("Data-base pendente. Não se usa a data de hoje nem a data de emissão.")
    with col_insp:
        has_inspection = st.checkbox("Informar data da vistoria", value=False)
        inspection_date = None
        if has_inspection:
            inspection_date = _iso_or_none(st.date_input("Data da vistoria"))
        else:
            st.caption("Data da vistoria é campo próprio, distinto da data-base e da emissão.")

    col_sol, col_fin = st.columns(2)
    with col_sol:
        applicant = st.text_input("Solicitante", value="")
    with col_fin:
        purpose = st.text_input("Finalidade da avaliação", value="")

    degree = st.selectbox(
        "Grau mínimo solicitado",
        options=[1, 2, 3],
        index=0,
        help=DEGREE_HELP,
    )
    st.caption(DEGREE_HELP)

    missing_predictors = st.selectbox(
        "Política para características ausentes nos preditores",
        options=["complete_case", "declared_method_on_train"],
        index=0,
        help="O alvo nunca é imputado. Exclusões precisam ser declaradas.",
    )
    grau_item1 = st.selectbox(
        "Grau declarado de caracterização do imóvel avaliando (item documental)",
        options=[1, 2, 3],
        index=0,
        help="Declaração do profissional, não verificação automática da planilha.",
    )
    grau_item3 = st.selectbox(
        "Grau declarado de identificação dos dados de mercado (item documental)",
        options=[1, 2, 3],
        index=0,
        help="Declaração do profissional. Pontuação documental declarada não vira comprovação.",
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
        documentary={
            "item1_grade_declared": grau_item1,
            "item3_grade_declared": grau_item3,
            "provenance": "declared_by_user",
        },
    )

    st.subheader("3. Informar o avaliando")
    st.caption(
        "Use as variáveis-base do esquema (categorias, números já interpretados, "
        "ausências e unidades). Não preencha colunas dummy."
    )
    feature_schema = model["feature_schema"] or _feature_schema_from_column_map(model["column_map"], target_col, roles, units)
    raw_values: dict = {}
    resolutions: dict = {}
    schema_columns = (feature_schema.get("columns") or {})
    dummies = dummy_column_names(feature_schema)

    for internal, meta in schema_columns.items():
        meta = meta or {}
        if meta.get("role") == "target" or internal in dummies:
            continue
        original = meta.get("original_name") or internal
        kind = str(meta.get("kind") or "").lower()
        unit = meta.get("unit")
        unit_note = f" (unidade: {unit})" if unit else " (unidade não informada no esquema)"
        categories = meta.get("categories") or []
        if kind in {"categorical", "category"}:
            options = ["(ausente)"] + list(categories) + ["(categoria não suportada)"]
            chosen = st.selectbox(
                f"{original}{unit_note}",
                options=options,
                key=f"c09_subj_{internal}",
            )
            if chosen == "(ausente)":
                raw_values[internal] = None
            elif chosen == "(categoria não suportada)":
                custom = st.text_input(
                    f"Categoria informada para «{original}» (não está no esquema)",
                    key=f"c09_subj_custom_{internal}",
                )
                raw_values[internal] = custom or "__unsupported__"
                resolution = st.radio(
                    f"Resolução para categoria não suportada de «{original}»",
                    options=["pendente", "map_to_supported", "exclude", "abort"],
                    key=f"c09_res_{internal}",
                    help="Coluna/categoria fora de suporte exige decisão explícita.",
                )
                mapped = None
                if resolution == "map_to_supported" and categories:
                    mapped = st.selectbox(
                        f"Mapear «{original}» para",
                        options=list(categories),
                        key=f"c09_map_{internal}",
                    )
                if resolution != "pendente":
                    resolutions[internal] = {"action": resolution, "mapped_value": mapped}
            else:
                raw_values[internal] = chosen
        else:
            entered = st.text_input(
                f"{original}{unit_note}",
                value="",
                key=f"c09_subj_{internal}",
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
            key="c09_res_extra_col",
        )
        if extra_res != "pendente":
            resolutions[extra_unsupported] = {"action": extra_res}

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

    return {
        "uploaded_file": uploaded_file,
        "request_spec": request_spec,
        "subject": subject,
        "dispatch": dispatch,
        "preview": preview,
        "connection_error": None,
        "preview_error": preview_error,
        "degree": degree,
        "feature_schema": feature_schema,
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
