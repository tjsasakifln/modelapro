"""Local configuration: loopback defaults, explicit origins, no embedded secrets."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field
from typing import Tuple

from dotenv import load_dotenv

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
UNSAFE_BIND_HOSTS = frozenset({"0.0.0.0", "::", "[::]"})
_PLACEHOLDER_TOKENS = frozenset(
    {"secret", "changeme", "password", "token", "admin", "123456", "changemeplease"}
)
_DEFAULT_CORS = (
    "http://127.0.0.1:8501",
    "http://localhost:8501",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
)


def default_runtime_root() -> str:
    """Return a per-user runtime location, never a directory in the checkout."""
    configured = os.getenv("MODELA_RUNTIME_ROOT", "").strip()
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    if platform.system().lower().startswith("win"):
        base = os.getenv("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
        return os.path.join(base, "MODELAPro")
    base = os.getenv("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )
    return os.path.join(base, "modelapro")


def load_dotenv_files() -> None:
    """Load `.env` from the process cwd unless tests request a skip."""
    flag = os.getenv("MODELA_SKIP_DOTENV", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return
    load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        value = default
    else:
        try:
            value = int(raw.strip())
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}, got {value}")
    return value


def _env_str(name: str, default: str, *, allow_empty: bool = True) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    stripped = raw.strip()
    if stripped:
        return stripped
    return "" if not allow_empty else default


def _nested_dir(name: str, parent: str, nested: str) -> str:
    """Blank env values (as in a copied .env.example) are treated as unset."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return os.path.join(parent, nested) if parent else ""
    return raw.strip()


def _parse_origins(raw: str | None) -> Tuple[str, ...]:
    if raw is None or not raw.strip():
        return _DEFAULT_CORS
    parts = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not parts:
        raise ValueError("CORS_ORIGINS is empty after parsing; list explicit localhost origins")
    if any(item == "*" for item in parts):
        raise ValueError(
            "CORS_ORIGINS must list explicit origins "
            "(e.g. http://127.0.0.1:8501); '*' is not allowed"
        )
    return parts


def is_loopback_host(host: str) -> bool:
    return host.strip().lower() in LOOPBACK_HOSTS


def _display_host(bind_host: str) -> str:
    if bind_host in UNSAFE_BIND_HOSTS:
        return "127.0.0.1"
    return bind_host


def _validate_local_token(token: str) -> None:
    if token == "":
        return
    if token.lower() in _PLACEHOLDER_TOKENS or len(token) < 8:
        raise ValueError(
            "LOCAL_AUTH_TOKEN is set but is a placeholder or shorter than 8 characters. "
            "Leave it empty for single-user loopback use, or set a non-guessable token. "
            "Do not commit the token."
        )


@dataclass
class Config:
    APP_NAME: str = "CONFENGE MODELA PRO"
    DEBUG: bool = False
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000
    API_PUBLIC_URL: str = "http://127.0.0.1:8000"
    FRONTEND_HOST: str = "127.0.0.1"
    FRONTEND_PORT: int = 8501
    CORS_ORIGINS: Tuple[str, ...] = _DEFAULT_CORS
    REDIS_ENABLED: bool = False
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    LOG_LEVEL: str = "INFO"
    RUNTIME_ROOT: str = ""
    LOG_DIR: str = ""
    DATA_DIR: str = ""
    UPLOAD_DIR: str = ""
    REPORTS_DIR: str = ""
    JOBS_DIR: str = ""
    PROJECTS_DIR: str = ""
    MAX_UPLOAD_MB: int = 25
    MAX_CONCURRENT_JOBS: int = 1
    JOB_TIMEOUT_SECONDS: int = 3600
    LOCAL_AUTH_TOKEN: str = ""
    # Shared/network serving is deliberately not a product mode yet.
    LOCAL_SHARED_MODE: bool = False

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
    MAX_RESIDUAL_REL: float = 0.40  # 40%

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
    MAX_ONE_HOT_CATEGORIES: int = 50

    extra_warnings: Tuple[str, ...] = field(default_factory=tuple)

    def cors_origin_list(self) -> list[str]:
        return list(self.CORS_ORIGINS)


def validate_config(cfg: Config) -> None:
    """Raise ValueError if required C10/C11 keys are empty or unsafe."""
    if not cfg.DATA_DIR.strip():
        raise ValueError("DATA_DIR must be a non-empty local directory path")
    if not cfg.UPLOAD_DIR.strip():
        raise ValueError("UPLOAD_DIR must be a non-empty local directory path")
    if not cfg.REPORTS_DIR.strip():
        raise ValueError("REPORTS_DIR must be a non-empty local directory path")
    if not cfg.JOBS_DIR.strip():
        raise ValueError("JOBS_DIR must be a non-empty local directory path")
    if not cfg.PROJECTS_DIR.strip():
        raise ValueError("PROJECTS_DIR must be a non-empty local directory path")
    if not cfg.LOG_DIR.strip():
        raise ValueError("LOG_DIR must be a non-empty local directory path")
    if cfg.MAX_UPLOAD_MB < 1:
        raise ValueError(f"MAX_UPLOAD_MB must be >= 1, got {cfg.MAX_UPLOAD_MB}")
    if cfg.MAX_CONCURRENT_JOBS < 1:
        raise ValueError(
            f"MAX_CONCURRENT_JOBS must be >= 1, got {cfg.MAX_CONCURRENT_JOBS}"
        )
    if cfg.JOB_TIMEOUT_SECONDS < 1:
        raise ValueError(
            f"JOB_TIMEOUT_SECONDS must be >= 1, got {cfg.JOB_TIMEOUT_SECONDS}"
        )
    if not cfg.CORS_ORIGINS:
        raise ValueError("CORS_ORIGINS must contain at least one explicit origin")
    if "*" in cfg.CORS_ORIGINS:
        raise ValueError("CORS_ORIGINS must not include '*'")
    _validate_local_token(cfg.LOCAL_AUTH_TOKEN)
    if cfg.LOCAL_SHARED_MODE:
        raise ValueError(
            "LOCAL_SHARED_MODE is not qualified for this release and remains disabled"
        )
    if not is_loopback_host(cfg.API_HOST):
        raise ValueError(
            "Non-loopback API_HOST is disabled until shared-mode authentication, "
            "RBAC and transport qualification are implemented."
        )
    if not is_loopback_host(cfg.FRONTEND_HOST):
        raise ValueError(
            "Non-loopback FRONTEND_HOST is disabled until shared-mode authentication, "
            "RBAC and transport qualification are implemented."
        )


def build_config() -> Config:
    """Read process environment and return a validated Config."""
    api_host = _env_str("API_HOST", "127.0.0.1") or "127.0.0.1"
    api_port = _env_int("API_PORT", 8000, minimum=1, maximum=65535)
    frontend_host = _env_str("FRONTEND_HOST", "127.0.0.1") or "127.0.0.1"
    frontend_port = _env_int("FRONTEND_PORT", 8501, minimum=1, maximum=65535)
    public_default = f"http://{_display_host(api_host)}:{api_port}"
    runtime_root = default_runtime_root()
    raw_store_override = os.getenv("MODELA_STORE_ROOT")
    raw_data_override = os.getenv("DATA_DIR")
    if raw_store_override is not None and not raw_store_override.strip():
        raise ValueError("MODELA_STORE_ROOT must not be blank when explicitly set")
    if raw_data_override is not None and not raw_data_override.strip():
        raise ValueError("DATA_DIR must not be blank when explicitly set")
    store_override = (raw_store_override or "").strip()
    data_override = (raw_data_override or "").strip()
    if store_override and data_override:
        if os.path.abspath(os.path.expanduser(store_override)) != os.path.abspath(
            os.path.expanduser(data_override)
        ):
            raise ValueError(
                "MODELA_STORE_ROOT and DATA_DIR must identify the same canonical store root"
            )
    data_dir = store_override or data_override or os.path.join(runtime_root, "store")
    jobs_dir = _nested_dir("JOBS_DIR", data_dir, "jobs")
    projects_dir = _nested_dir("PROJECTS_DIR", data_dir, "projects")
    cfg = Config(
        APP_NAME=_env_str("APP_NAME", "CONFENGE MODELA PRO") or "CONFENGE MODELA PRO",
        DEBUG=_env_bool("DEBUG", False),
        API_HOST=api_host,
        API_PORT=api_port,
        API_PUBLIC_URL=_env_str("API_PUBLIC_URL", public_default) or public_default,
        FRONTEND_HOST=frontend_host,
        FRONTEND_PORT=frontend_port,
        CORS_ORIGINS=_parse_origins(os.getenv("CORS_ORIGINS")),
        REDIS_ENABLED=_env_bool("REDIS_ENABLED", False),
        REDIS_HOST=_env_str("REDIS_HOST", "127.0.0.1") or "127.0.0.1",
        REDIS_PORT=_env_int("REDIS_PORT", 6379, minimum=1, maximum=65535),
        LOG_LEVEL=(_env_str("LOG_LEVEL", "INFO") or "INFO").upper(),
        RUNTIME_ROOT=runtime_root,
        LOG_DIR=_env_str("LOG_DIR", os.path.join(runtime_root, "logs"), allow_empty=False),
        DATA_DIR=data_dir,
        UPLOAD_DIR=_env_str("UPLOAD_DIR", os.path.join(runtime_root, "uploads"), allow_empty=False),
        REPORTS_DIR=_env_str("REPORTS_DIR", os.path.join(runtime_root, "reports"), allow_empty=False),
        JOBS_DIR=jobs_dir,
        PROJECTS_DIR=projects_dir,
        MAX_UPLOAD_MB=_env_int("MAX_UPLOAD_MB", 25, minimum=1, maximum=1024),
        MAX_CONCURRENT_JOBS=_env_int("MAX_CONCURRENT_JOBS", 1, minimum=1, maximum=32),
        JOB_TIMEOUT_SECONDS=_env_int(
            "JOB_TIMEOUT_SECONDS", 3600, minimum=1, maximum=86400
        ),
        LOCAL_AUTH_TOKEN=(os.getenv("LOCAL_AUTH_TOKEN") or "").strip(),
        LOCAL_SHARED_MODE=_env_bool("LOCAL_SHARED_MODE", False),
        MAX_ONE_HOT_CATEGORIES=_env_int(
            "MAX_ONE_HOT_CATEGORIES", 50, minimum=1, maximum=10_000
        ),
    )
    validate_config(cfg)
    return cfg


load_dotenv_files()
config = build_config()
