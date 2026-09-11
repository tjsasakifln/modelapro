"""Owned packaging/config files must not ship secrets or client data."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_FORBIDDEN_SNIPPETS = (
    "BEGIN OPENSSH PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
    "AKIA",
)


def test_env_example_has_empty_token_and_loopback():
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "LOCAL_AUTH_TOKEN=" in text
    assert "LOCAL_AUTH_TOKEN=changeme" not in text
    assert "API_HOST=127.0.0.1" in text
    assert "API_HOST=0.0.0.0" not in text
    assert "REDIS_ENABLED=false" in text.lower() or "REDIS_ENABLED=false" in text
    for snippet in _FORBIDDEN_SNIPPETS:
        assert snippet not in text


def test_gitignore_excludes_env_and_runtime_data():
    text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in text
    assert "logs/" in text
    assert "data/" in text
    assert "uploads/*" in text
    assert "reports/*" in text
    assert "!.env.example" in text
