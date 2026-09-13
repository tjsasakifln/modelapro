"""First-use credentials are synthetic, private, and atomically shared."""
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from modules.operacao_local.runtime import _credentials


@pytest.fixture
def bootstrap(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCAL_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("LOCAL_CSRF_SECRET", raising=False)
    root = tmp_path / "private"
    monkeypatch.setenv("MODELA_RUNTIME_ROOT", str(root))
    return root


def test_concurrent_processes_obtain_one_complete_identity(bootstrap):
    code = (
        "import hashlib,json; from modules.operacao_local.runtime import _credentials; "
        "print(hashlib.sha256(json.dumps(_credentials(),sort_keys=True).encode()).hexdigest())"
    )
    def load(_):
        return subprocess.check_output([sys.executable, "-c", code], text=True,
                                       cwd=Path(__file__).resolve().parents[2]).strip()
    with ThreadPoolExecutor(max_workers=8) as pool:
        identities = list(pool.map(load, range(8)))
    assert len(set(identities)) == 1
    assert len(identities[0]) == 64
    assert not list(bootstrap.glob(".credentials-*"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX-specific permission bits; this does not verify Windows ACLs")
def test_insecure_file_and_directory_permissions_are_refused(bootstrap):
    _credentials()
    record = bootstrap / "local-credentials.json"
    assert record.stat().st_mode & 0o777 == 0o600
    assert bootstrap.stat().st_mode & 0o777 == 0o700
    record.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        _credentials()
    record.chmod(0o600)
    bootstrap.chmod(0o755)
    with pytest.raises(ValueError, match="private"):
        _credentials()


def test_symlink_credentials_are_refused(bootstrap, tmp_path):
    bootstrap.mkdir(mode=0o700)
    target = tmp_path / "untrusted.json"
    target.write_text('{}')
    try:
        (bootstrap / "local-credentials.json").symlink_to(target)
    except OSError as exc:
        pytest.fail(f"NOT_RUN: cannot exercise symlink rejection: {type(exc).__name__}")
    with pytest.raises((ValueError, OSError)):
        _credentials()


def test_config_and_guard_agree_on_minimum_token(monkeypatch):
    from modules.config_manager import build_config
    monkeypatch.setenv("LOCAL_AUTH_TOKEN", "1234567890")
    with pytest.raises(ValueError, match="16 characters"):
        build_config()
