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
