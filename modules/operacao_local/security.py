"""Fail-closed local deployment safeguards, independent of a web framework."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class AccessDenied(ValueError):
    """Raised when a request or filesystem object is outside its authority."""


_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_SENSITIVE_KEY = re.compile(
    r"password|secret|token|authorization|cookie|key|email|cpf|phone|"
    r"content|payload|raw|data|filename|path|address|endereco|client|customer|"
    r"property|location|document|cnpj", re.I
)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_CPF = re.compile(r"\b\d{3}[.]?\d{3}[.]?\d{3}-?\d{2}\b")
_CNPJ = re.compile(r"\b\d{2}[.]?\d{3}[.]?\d{3}/?\d{4}-?\d{2}\b")


def _constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


@dataclass(frozen=True)
class LocalSecurityPolicy:
    """Authorization policy for a browser-facing local service.

    Loopback is a network boundary only; every request still needs a bearer
    token.  Mutations additionally require an exact allowed Origin and a CSRF
    token bound to that bearer token.
    """

    bearer_token: str
    allowed_origins: frozenset[str]
    csrf_secret: bytes

    def __post_init__(self) -> None:
        if len(self.bearer_token) < 16:
            raise ValueError("bearer_token must be a non-placeholder secret of at least 16 characters")
        if not self.allowed_origins or "*" in self.allowed_origins:
            raise ValueError("allowed_origins must be a non-empty explicit set")
        if len(self.csrf_secret) < 16:
            raise ValueError("csrf_secret must contain at least 16 bytes")

    def csrf_token(self) -> str:
        """Return a deterministic token suitable for the authenticated local UI."""
        digest = hmac.new(self.csrf_secret, self.bearer_token.encode("utf-8"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def authorize(self, *, method: str, authorization: str | None, origin: str | None = None,
                  csrf_token: str | None = None) -> None:
        expected = f"Bearer {self.bearer_token}"
        if not authorization or not _constant_time_equal(authorization, expected):
            raise AccessDenied("missing or invalid bearer authorization")
        if method.upper() in _MUTATING:
            if not origin or origin not in self.allowed_origins:
                raise AccessDenied("mutating request origin is not explicitly allowed")
            if not csrf_token or not _constant_time_equal(csrf_token, self.csrf_token()):
                raise AccessDenied("missing or invalid CSRF token")


@dataclass(frozen=True)
class UploadPolicy:
    max_bytes: int = 25 * 1024 * 1024
    max_zip_members: int = 256
    max_uncompressed_bytes: int = 100 * 1024 * 1024
    max_compression_ratio: int = 100
    # Default ingestion is deliberately limited to supported tabular sources.
    # Document/archive endpoints must opt in with their own narrower policy.
    allowed_extensions: frozenset[str] = frozenset({".csv", ".xlsx", ".xls"})


def _safe_upload_name(name: str) -> str:
    if not name or "\x00" in name or name != os.path.basename(name):
        raise ValueError("upload name must be a plain filename")
    suffix = Path(name).suffix.lower()
    if suffix == "" or name.startswith("."):
        raise ValueError("upload filename must have a supported extension")
    return suffix


def _has_expected_magic(extension: str, content: bytes) -> bool:
    if extension == ".csv":
        # CSV has no authoritative magic number. Reject known binary/document
        # signatures and NUL bytes instead of pretending an extension is proof.
        return (b"\x00" not in content[:4096] and bool(content.strip())
                and not content.startswith((b"%PDF-", b"PK\x03\x04", b"PK\x05\x06")))
    if extension in {".xlsx", ".zip"}:
        return content.startswith(b"PK\x03\x04") or content.startswith(b"PK\x05\x06")
    if extension == ".xls":
        return content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    return content.startswith(b"%PDF-")


def _inspect_zip(content: bytes, policy: UploadPolicy, *, require_xlsx: bool = False) -> None:
    try:
        from io import BytesIO
        with zipfile.ZipFile(BytesIO(content)) as archive:
            infos = archive.infolist()
            if len(infos) > policy.max_zip_members:
                raise ValueError("zip has too many members")
            total = sum(item.file_size for item in infos)
            if total > policy.max_uncompressed_bytes:
                raise ValueError("zip uncompressed size exceeds limit")
            for item in infos:
                normalized = item.filename.replace("\\", "/")
                if normalized.startswith("/") or ".." in Path(normalized).parts:
                    raise ValueError("zip contains unsafe member path")
                if item.flag_bits & 0x1:
                    raise ValueError("encrypted zip members are not accepted")
                file_type = (item.external_attr >> 16) & 0o170000
                if file_type == 0o120000:
                    raise ValueError("zip symlink members are not accepted")
                if item.compress_size == 0 and item.file_size > 0:
                    raise ValueError("zip contains suspicious uncompressed member")
                if item.compress_size and item.file_size / item.compress_size > policy.max_compression_ratio:
                    raise ValueError("zip compression ratio exceeds limit")
            names = {item.filename for item in infos}
            if require_xlsx and "[Content_Types].xml" not in names:
                raise ValueError("xlsx container is missing required content types")
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid zip container") from exc


def validate_upload(name: str, content: bytes, policy: UploadPolicy = UploadPolicy()) -> dict[str, Any]:
    """Validate bytes before persistence; returns metadata only, never content."""
    extension = _safe_upload_name(name)
    if extension not in policy.allowed_extensions:
        raise ValueError("upload extension is not allowed")
    if not isinstance(content, bytes) or not content:
        raise ValueError("upload content must be non-empty bytes")
    if len(content) > policy.max_bytes:
        raise ValueError("upload exceeds byte limit")
    if not _has_expected_magic(extension, content):
        raise ValueError("upload magic does not match extension")
    if extension in {".xlsx", ".zip"}:
        _inspect_zip(content, policy, require_xlsx=extension == ".xlsx")
    return {"filename": os.path.basename(name), "extension": extension, "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest()}


class WorkspacePathResolver:
    """Maps a workspace/project pair to an isolated descendant of ``root``."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    @staticmethod
    def _id(value: str, label: str) -> str:
        if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
            raise AccessDenied(f"invalid {label} identifier")
        return value

    def project_path(self, workspace_id: str, project_id: str) -> Path:
        workspace_id = self._id(workspace_id, "workspace")
        project_id = self._id(project_id, "project")
        candidate = (self.root / workspace_id / project_id).resolve()
        if self.root not in candidate.parents:
            raise AccessDenied("resolved project path escaped storage root")
        return candidate

    def require_workspace(self, authenticated_workspace: str, requested_workspace: str) -> None:
        if not _constant_time_equal(self._id(authenticated_workspace, "workspace"),
                                    self._id(requested_workspace, "workspace")):
            raise AccessDenied("cross-workspace access denied")


def redact_diagnostic(value: Any, *, _depth: int = 0) -> Any:
    """Return useful structured diagnostics without request content or PII."""
    if _depth > 5:
        return "<redacted: nesting limit>"
    if isinstance(value, Mapping):
        return {
            str(key): (
                "<redacted>"
                if _SENSITIVE_KEY.search(str(key))
                else redact_diagnostic(item, _depth=_depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_diagnostic(item, _depth=_depth + 1) for item in value[:50]]
    if isinstance(value, bytes):
        return f"<redacted bytes n={len(value)} sha256={hashlib.sha256(value).hexdigest()[:12]}>"
    if isinstance(value, str):
        cleaned = _CNPJ.sub(
            "<redacted-cnpj>",
            _CPF.sub("<redacted-cpf>", _EMAIL.sub("<redacted-email>", value)),
        )
        return cleaned[:512]
    return value
