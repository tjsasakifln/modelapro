"""Private first-use credentials shared by the installed backend and local UI."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile

from .security import LocalSecurityPolicy


def runtime_root() -> Path:
    from modules.config_manager import config
    return Path(os.environ.get("MODELA_RUNTIME_ROOT") or config.DATA_DIR).resolve()


def _credentials() -> dict:
    token, secret = os.environ.get("LOCAL_AUTH_TOKEN"), os.environ.get("LOCAL_CSRF_SECRET")
    if token and secret:
        return {"bearer": token, "csrf_secret": secret}
    root = runtime_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root_stat = root.stat()
    if os.name == "posix" and (root_stat.st_uid != os.getuid() or root_stat.st_mode & 0o077):
        raise ValueError("credential directory must be private and owned by the current user")
    path = root / "local-credentials.json"
    if not path.exists():
        data = {"bearer": secrets.token_urlsafe(32), "csrf_secret": secrets.token_urlsafe(32)}
        fd, temporary = tempfile.mkstemp(prefix=".credentials-", dir=root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                # Publish complete bytes without replacing another process's
                # winning identity. Both files are on the same local volume.
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
        metadata = os.fstat(handle.fileno())
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ValueError("credentials must be a regular non-symlink file")
        if os.name == "posix" and (metadata.st_uid != os.getuid() or metadata.st_mode & 0o077):
            raise ValueError("credentials must be private and owned by the current user")
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("bearer"), str) or not isinstance(data.get("csrf_secret"), str):
        raise ValueError("invalid credential record")
    return data


def local_origin() -> str:
    from modules.config_manager import config
    return f"http://{config.FRONTEND_HOST}:{config.FRONTEND_PORT}"


def get_security_policy() -> LocalSecurityPolicy:
    from modules.config_manager import config
    data = _credentials()
    encoded = data["csrf_secret"]
    return LocalSecurityPolicy(
        bearer_token=data["bearer"],
        csrf_secret=base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)),
        allowed_origins=frozenset([local_origin(), *config.cors_origin_list()]),
    )


def local_client_headers() -> dict[str, str]:
    policy = get_security_policy()
    return {"Authorization": f"Bearer {policy.bearer_token}", "X-CSRF-Token": policy.csrf_token(),
            "Origin": local_origin(), "X-Workspace-ID": os.environ.get("MODELA_WORKSPACE_ID", "local")}


def license_decision():
    from modules.commercial_license import LicenseDecision, load_license, trusted_vendor_public_key
    path = Path(os.environ.get("MODELA_LICENSE_PATH") or runtime_root() / "entitlement.json")
    try:
        return load_license(path, trusted_vendor_public_key())
    except (ValueError, OSError):
        return LicenseDecision(False, False, None, frozenset(), "license unavailable or invalid")


def active_store_root() -> Path | None:
    pointer = runtime_root() / "restored-store.json"
    if not pointer.exists():
        return None
    relative = json.loads(pointer.read_text(encoding="utf-8"))["relative_path"]
    path = (runtime_root() / relative).resolve()
    if (runtime_root() / "restored-stores").resolve() not in path.parents:
        raise ValueError("restored store pointer escaped workspace")
    return path
