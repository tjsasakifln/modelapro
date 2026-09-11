import os
from dotenv import load_dotenv
from dataclasses import dataclass

load_dotenv()

@dataclass
class Config:
    APP_NAME: str = os.getenv("APP_NAME", "CONFENGE MODELA PRO")
    DEBUG: bool = os.getenv("DEBUG", "True").lower() == "true"
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # NBR 14653-2 Defaults
    # MIN_SAMPLES_GRAU_1/2/3 are informational references only - they are NOT
    # normative absolute minimums independent of k (number of model variables).
    # They must never be used to fail/block a model. The actual normative
    # criterion is n >= 3(k+1) / 4(k+1) / 6(k+1) for Grau 1/2/3 respectively,
    # which can only be evaluated once k is known (inside model validation).
    MIN_SAMPLES_GRAU_1: int = 15
    MIN_SAMPLES_GRAU_2: int = 20
    MIN_SAMPLES_GRAU_3: int = 30

    MAX_EXTRAPOLATION_GRAU_1_2: float = 2.0  # 200% (Double) or 0.5 (Half) logic handled in validation
    MAX_EXTRAPOLATION_GRAU_3: float = 0.0    # No extrapolation

    # MIN_R2 has no normative basis (see Anexo A.4) and must never be used as a
    # blocking/reprovação criterion by any validator. Kept only for reference.
    MIN_R2: float = 0.75
    MIN_CORRELATION: float = 0.75
    MAX_VIF: float = 10.0
    MAX_COOK_DISTANCE: float = 1.0
    MAX_RESIDUAL_REL: float = 0.40 # 40%

    SIGNIFICANCE_LEVEL_AUX: float = 0.10   # Anexo A.3.1 - testes não citados na Tabela 1 (Shapiro-Wilk, Breusch-Pagan)
    CAMPO_ARBITRIO: float = 0.15           # NBR 14653-1 3.8 / NBR 14653-2 8.2.1.5.1
    CONFIDENCE_LEVEL_PRECISION: float = 0.80  # Tabela 5

    # Data loading (modules/data_loader.py): max number of distinct values a
    # categorical (text) column may have and still be one-hot encoded into
    # usable numeric candidate variables. The user must have total freedom
    # to bring in whatever market variables they can obtain - a column is
    # NEVER silently dropped just because it is above this threshold; it is
    # instead surfaced via DataLoadResult.excluded_columns (with a reason)
    # and DataLoadResult.identification_df (its original values preserved),
    # and reported as a warning. This constant only controls where the line
    # between "technically encodable as a model variable" and "kept as
    # identification-only data" sits, and is configurable via the
    # MAX_ONE_HOT_CATEGORIES env var.
    MAX_ONE_HOT_CATEGORIES: int = int(os.getenv("MAX_ONE_HOT_CATEGORIES", "50"))

config = Config()
