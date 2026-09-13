from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime
import pandas as pd

@dataclass
class BaseResult:
    success: bool
    message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None

@dataclass
class ItemScore:
    item: int                 # 1 a 6
    description: str
    grau_achieved: int = 0    # 0, 1, 2 ou 3
    detail: str = ""

@dataclass
class ValidationResult(BaseResult):
    # is_valid semantics: True somente se grau_fundamentacao is not None
    # and grau_fundamentacao >= target_degree.
    is_valid: bool = False
    messages: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    item_scores: List[ItemScore] = field(default_factory=list)
    grau_fundamentacao: Optional[int] = None       # 1, 2, 3 ou None
    grau_fundamentacao_pontos: int = 0
    grau_precisao: Optional[int] = None            # 1, 2, 3 ou None
    precisao_amplitude_pct: Optional[float] = None
    target_degree: Optional[int] = None
    # Anexo A.10.1.1: "valores admissíveis" quando adotada a estimativa de
    # tendência central = interseção entre o intervalo de confiança de 80%
    # (Tabela 5 / CONFIDENCE_LEVEL_PRECISION) e o campo de arbítrio de ±15%
    # (NBR 14653-1 3.8 / NBR 14653-2 8.2.1.5.1, CAMPO_ARBITRIO) em torno da
    # estimativa pontual central. None até que o grau de precisão seja
    # calculado (finalize_precision_and_extrapolation) com os limites do IC
    # disponíveis.
    valores_admissiveis_inferior: Optional[float] = None
    valores_admissiveis_superior: Optional[float] = None

@dataclass
class ModelMetrics:
    r2: float
    r2_adjusted: float
    f_statistic: float
    f_pvalue: float
    std_error: float
    aic: float
    bic: float
    condition_number: float
    normality_pvalue: float
    homoscedasticity_pvalue: float
    autocorrelation_durbin_watson: float

@dataclass
class ModelResult(BaseResult):
    model_metrics: Optional[ModelMetrics] = None
    coefficients: Dict[str, float] = field(default_factory=dict)
    pvalues: Dict[str, float] = field(default_factory=dict)
    vif: Dict[str, float] = field(default_factory=dict)
    residuals: List[float] = field(default_factory=list)
    fitted_values: List[float] = field(default_factory=list)
    formula: str = ""
    outliers_removed: List[int] = field(default_factory=list)
    transformations: Dict[str, str] = field(default_factory=dict)
    validation_result: Optional[ValidationResult] = None
    
    # For serialization, we might need to exclude the actual statsmodels object
    # but we can keep it if needed for internal use, just not for JSON response
    model_object: Any = None 

@dataclass
class DataLoadResult(BaseResult):
    dataframe: Optional[pd.DataFrame] = None
    validation: Optional[ValidationResult] = None
    variables: List[str] = field(default_factory=list)
    sample_size: int = 0
    missing_values: Dict[str, int] = field(default_factory=dict)
    # Columns technically excluded from modeling (never silently dropped -
    # see modules/data_loader.py), with their ORIGINAL untransformed values,
    # e.g. Endereço, Informante, Telefone. Aligned to the same row index as
    # `dataframe`. None when no column was excluded.
    identification_df: Optional[pd.DataFrame] = None
    # Column name -> textual reason it could not become a usable numeric
    # model variable (e.g. "texto livre com N valores únicos, acima do
    # limite de MAX_ONE_HOT_CATEGORIES"). Empty dict when nothing was
    # excluded. This only reflects technical modelability, not the user's
    # later choice of which remaining columns to actually use as
    # candidates.
    excluded_columns: Dict[str, str] = field(default_factory=dict)

@dataclass
class TransformationResult(BaseResult):
    variable: str = ""
    transformation_type: str = ""
    normality_score_before: float = 0.0
    normality_score_after: float = 0.0
    transformed_values: List[float] = field(default_factory=list)

@dataclass
class OptimalCombinationResult(BaseResult):
    best_model: Optional[ModelResult] = None
    combinations_tested: int = 0
    time_elapsed: float = 0.0
    history: List[Dict[str, Any]] = field(default_factory=list)
    target_achieved: bool = False
    best_grau_reached: Optional[int] = None
    # True quando a busca cobriu 100% do espaço de transformação x inclusão
    # de variáveis (produto cartesiano, respeitando o teto normativo de
    # variáveis por modelo). False quando o espaço excedeu o limite de
    # segurança combinatória e a busca recorreu ao fallback heurístico de
    # poda por correlação (top-N) — ver OptimalCombinationFinder para o
    # limiar exato e a mensagem de aviso correspondente.
    exhaustive: bool = True


# ---------------------------------------------------------------------------
# MP/1 adapters (C10). Legacy dataclasses above stay the public surface for
# existing callers. These helpers convert them into MP/1 mappings and
# explicitly list capabilities they CANNOT represent. They never rebuild
# value.point from the arbitration (campo de arbítrio) interval, never treat
# is_valid as issuance approval, and never invent missing row ledgers.
# ---------------------------------------------------------------------------

LEGACY_CAPABILITY_GAPS = {
    "DataLoadResult": (
        "row_ledger with observed_target/disposition/missing_before/changes/reasons",
        "input_sha256",
        "raw_frame versus parsed_frame (only a processed dataframe is kept)",
        "stable row_id that is guaranteed never to enter as a predictor",
        "roles applied before cleaning",
        "column_map of original → internal names as a first-class object",
    ),
    "ModelResult": (
        "used_row_ids / excluded_row_ids distinct from outliers_removed",
        "feature_schema groups and reference categories",
        "declarative encoder_state",
        "target_transform_state with estimand/limitations",
        "model_sha256 of the fitted specification",
        "coefficients at integral precision as a typed structure",
        "CandidateFit.status (fitted|rejected|error)",
    ),
    "ValidationResult": (
        "verification_status of listed rules (verified_rules_listed|partial|pending)",
        "rule edition/source/status per item",
        "separation of documentary declared points from verified evidence",
        "issuance readiness distinct from grau_fundamentacao / is_valid",
        "precisao.status in {not_computed, classified, unclassified, error}",
        "predict_original callback identity with the same pipeline",
    ),
    "OptimalCombinationResult": (
        "search_audit of possible/generated/evaluated/rejected candidates",
        "coverage versus ranking-criterion completeness",
        "budget and objective as declared search_policy fields",
        "alternatives as CandidateAssessment list",
        "cancel_requested cooperative stop",
    ),
}


def _legacy_gap_issues(kind: str, origin: str = "results.legacy_adapter") -> List[Dict[str, Any]]:
    from modules.result_contract import make_issue

    gaps = LEGACY_CAPABILITY_GAPS.get(kind, ())
    return [
        make_issue(
            "LEGACY_CAPABILITY_GAP",
            f"{kind} cannot represent: {gap}",
            severity="warning",
            origin=origin,
            evidence={"legacy_type": kind, "gap": gap},
        )
        for gap in gaps
    ]


def adapt_validation_result(vr: Optional["ValidationResult"]) -> Dict[str, Any]:
    """Map ValidationResult into snapshot.validation without authorizing a laudo.

    is_valid / grau_fundamentacao never become issuance.status =
    ready_for_professional_review. Declared documentary scores stay
    declared, not verified. Missing precision stays not_computed, not 0.
    """
    issues = _legacy_gap_issues("ValidationResult")
    if vr is None:
        return {
            "fundamentacao": {"grade": None, "points": None, "items": []},
            "precisao": {
                "status": "not_computed",
                "grade": None,
                "amplitude_pct": None,
            },
            "statistical": {},
            "documentary": {"status": "declared", "verified": False},
            "issuance": {
                "status": "draft",
                "reasons": [
                    "legacy_validation_absent",
                    "no_automatic_report_approval",
                ],
            },
            "legacy_capability_gaps": issues,
        }

    precisao_status = "not_computed" if vr.grau_precisao is None else "classified"
    items = []
    for score in vr.item_scores or []:
        items.append(
            {
                "item": score.item,
                "description": score.description,
                "grade": score.grau_achieved,
                "detail": score.detail,
                "evidence_status": "declared",
            }
        )
    # Never promote is_valid to an approved report. At most, a valid
    # fundamentação grade is a draft that still requires professional review.
    issuance_status = "draft"
    reasons = [
        "legacy_validation_does_not_authorize_issuance",
        "no_automatic_report_approval",
        "documentary_declared_is_not_verified_proof",
    ]
    if vr.is_valid:
        reasons.append("legacy_is_valid_true_is_not_issuance_readiness")
        issuance_status = "review_required"

    admissible = None
    if (
        vr.valores_admissiveis_inferior is not None
        and vr.valores_admissiveis_superior is not None
    ):
        admissible = {
            "lower": vr.valores_admissiveis_inferior,
            "upper": vr.valores_admissiveis_superior,
        }

    return {
        "fundamentacao": {
            "grade": vr.grau_fundamentacao,
            "points": vr.grau_fundamentacao_pontos,
            "items": items,
        },
        "precisao": {
            "status": precisao_status,
            "grade": vr.grau_precisao,
            "amplitude_pct": vr.precisao_amplitude_pct,
        },
        "statistical": dict(vr.details or {}),
        "documentary": {
            "status": "declared",
            "verified": False,
            "messages": list(vr.messages or []),
            "warnings": list(vr.warnings or []),
        },
        "issuance": {"status": issuance_status, "reasons": reasons},
        "admissible_interval": admissible,
        "legacy_is_valid": vr.is_valid,
        "legacy_capability_gaps": issues,
    }


def adapt_model_result(mr: Optional["ModelResult"]) -> Dict[str, Any]:
    """JSON-safe model summary. model_object is never included."""
    issues = _legacy_gap_issues("ModelResult")
    if mr is None:
        return {"status": "absent", "legacy_capability_gaps": issues}
    metrics = None
    if mr.model_metrics is not None:
        metrics = {
            "r2": mr.model_metrics.r2,
            "r2_adjusted": mr.model_metrics.r2_adjusted,
            "f_statistic": mr.model_metrics.f_statistic,
            "f_pvalue": mr.model_metrics.f_pvalue,
            "std_error": mr.model_metrics.std_error,
            "aic": mr.model_metrics.aic,
            "bic": mr.model_metrics.bic,
            "condition_number": mr.model_metrics.condition_number,
            "normality_pvalue": mr.model_metrics.normality_pvalue,
            "homoscedasticity_pvalue": mr.model_metrics.homoscedasticity_pvalue,
            "autocorrelation_durbin_watson": mr.model_metrics.autocorrelation_durbin_watson,
        }
    return {
        "status": "fitted" if mr.success else "error",
        "formula": mr.formula,
        "coefficients": dict(mr.coefficients or {}),
        "pvalues": dict(mr.pvalues or {}),
        "vif": dict(mr.vif or {}),
        "transformations": dict(mr.transformations or {}),
        "outliers_removed": list(mr.outliers_removed or []),
        "metrics": metrics,
        "message": mr.message,
        "legacy_capability_gaps": issues,
        # model_object intentionally omitted — never JSON / pickle restore.
    }


def adapt_data_load_result(dlr: Optional["DataLoadResult"]) -> Dict[str, Any]:
    """Surface what DataLoadResult can say and mark what it cannot."""
    issues = _legacy_gap_issues("DataLoadResult")
    if dlr is None:
        return {"success": False, "legacy_capability_gaps": issues}
    return {
        "success": dlr.success,
        "message": dlr.message,
        "variables": list(dlr.variables or []),
        "sample_size": dlr.sample_size,
        "missing_values": dict(dlr.missing_values or {}),
        "excluded_columns": dict(dlr.excluded_columns or {}),
        "has_dataframe": dlr.dataframe is not None,
        "has_identification_df": dlr.identification_df is not None,
        "legacy_capability_gaps": issues,
    }


def adapt_optimal_combination_result(
    ocr: Optional["OptimalCombinationResult"],
) -> Dict[str, Any]:
    issues = _legacy_gap_issues("OptimalCombinationResult")
    if ocr is None:
        return {"success": False, "legacy_capability_gaps": issues}
    return {
        "success": ocr.success,
        "combinations_tested": ocr.combinations_tested,
        "exhaustive": ocr.exhaustive,
        "target_achieved": ocr.target_achieved,
        "best_grau_reached": ocr.best_grau_reached,
        "time_elapsed": ocr.time_elapsed,
        "legacy_capability_gaps": issues,
        "winner": adapt_model_result(ocr.best_model),
    }


def value_block_from_legacy_validation(
    vr: Optional["ValidationResult"],
    *,
    point: Optional[float] = None,
) -> Dict[str, Any]:
    """Build the snapshot value object.

    `point` must be the model's direct estimate. This function does not
    derive it from valores_admissiveis_* or from a ±15% arbitration band.
    """
    from modules.result_contract import empty_value_block

    block = empty_value_block()
    block["point"] = point
    if vr is None:
        return block
    if (
        vr.valores_admissiveis_inferior is not None
        and vr.valores_admissiveis_superior is not None
    ):
        block["admissible_interval"] = {
            "lower": vr.valores_admissiveis_inferior,
            "upper": vr.valores_admissiveis_superior,
        }
    return block

