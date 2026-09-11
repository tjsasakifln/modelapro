"""Safe localhost defaults and C10/C11 key validation."""

from __future__ import annotations

import pytest

from modules.config_manager import (
    LOOPBACK_HOSTS,
    build_config,
    is_loopback_host,
    validate_config,
)

_ENV_KEYS = (
    "APP_NAME",
    "DEBUG",
    "API_HOST",
    "API_PORT",
    "API_PUBLIC_URL",
    "FRONTEND_HOST",
    "FRONTEND_PORT",
    "CORS_ORIGINS",
    "REDIS_ENABLED",
    "REDIS_HOST",
    "REDIS_PORT",
    "LOG_LEVEL",
    "LOG_DIR",
    "DATA_DIR",
    "UPLOAD_DIR",
    "REPORTS_DIR",
    "JOBS_DIR",
    "PROJECTS_DIR",
    "MAX_UPLOAD_MB",
    "MAX_CONCURRENT_JOBS",
    "JOB_TIMEOUT_SECONDS",
    "LOCAL_AUTH_TOKEN",
    "MAX_ONE_HOT_CATEGORIES",
)


def _clear(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MODELA_SKIP_DOTENV", "1")


def test_default_bind_is_loopback_not_all_interfaces(monkeypatch):
    _clear(monkeypatch)
    cfg = build_config()
    assert is_loopback_host(cfg.API_HOST)
    assert cfg.API_HOST in LOOPBACK_HOSTS
    assert cfg.API_HOST != "0.0.0.0"
    assert cfg.FRONTEND_HOST in LOOPBACK_HOSTS
    assert "127.0.0.1" in cfg.API_PUBLIC_URL
    assert "0.0.0.0" not in cfg.API_PUBLIC_URL


def test_default_cors_is_explicit_localhost_not_star(monkeypatch):
    _clear(monkeypatch)
    cfg = build_config()
    assert "*" not in cfg.CORS_ORIGINS
    assert cfg.cors_origin_list()
    assert all(
        origin.startswith("http://127.0.0.1") or origin.startswith("http://localhost")
        for origin in cfg.CORS_ORIGINS
    )


def test_star_cors_is_rejected(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        build_config()


def test_redis_server_not_required_to_load_config(monkeypatch):
    _clear(monkeypatch)
    cfg = build_config()
    assert cfg.REDIS_ENABLED is False
    # Loading config must not open a Redis socket; defaults exist for optional extra only.
    assert cfg.REDIS_HOST
    assert cfg.REDIS_PORT > 0


def test_c10_c11_keys_exist_and_reject_empty_or_invalid(monkeypatch):
    _clear(monkeypatch)
    cfg = build_config()
    for name in (
        "DATA_DIR",
        "UPLOAD_DIR",
        "REPORTS_DIR",
        "JOBS_DIR",
        "PROJECTS_DIR",
        "MAX_UPLOAD_MB",
        "MAX_CONCURRENT_JOBS",
        "JOB_TIMEOUT_SECONDS",
        "LOCAL_AUTH_TOKEN",
    ):
        assert hasattr(cfg, name), name
    assert cfg.MAX_UPLOAD_MB >= 1
    assert cfg.MAX_CONCURRENT_JOBS >= 1
    assert cfg.LOCAL_AUTH_TOKEN == ""

    monkeypatch.setenv("DATA_DIR", "   ")
    with pytest.raises(ValueError, match="DATA_DIR"):
        build_config()

    _clear(monkeypatch)
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "0")
    with pytest.raises(ValueError, match="MAX_CONCURRENT_JOBS"):
        build_config()

    _clear(monkeypatch)
    monkeypatch.setenv("MAX_UPLOAD_MB", "nope")
    with pytest.raises(ValueError, match="MAX_UPLOAD_MB"):
        build_config()

    _clear(monkeypatch)
    monkeypatch.setenv("LOCAL_AUTH_TOKEN", "changeme")
    with pytest.raises(ValueError, match="LOCAL_AUTH_TOKEN"):
        build_config()


def test_no_embedded_secret_in_defaults(monkeypatch):
    _clear(monkeypatch)
    cfg = build_config()
    validate_config(cfg)
    assert cfg.LOCAL_AUTH_TOKEN == ""


def test_nbr_reference_constants_preserved(monkeypatch):
    _clear(monkeypatch)
    cfg = build_config()
    assert cfg.MIN_SAMPLES_GRAU_1 == 15
    assert cfg.MIN_R2 == 0.75
    assert cfg.MAX_ONE_HOT_CATEGORIES == 50
    assert cfg.CAMPO_ARBITRIO == 0.15
