"""Immutable local project revisions with path-safe artifact references.

C11 persists FrozenProject *metadata and refs* only. Restoring a fitted
model is C04's job from a verified declarative spec (or a deterministic
refit). This module never unpickles or execs stored objects.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from modules.job_store import (
    CONTRACT_VERSION,
    PersistenceError,
    SchemaVersionError,
    UnsafePayloadError,
    PathEscapeError,
    _connect,
    atomic_write_json,
    canonical_jsonable,
    ensure_directory,
    init_store_root,
    lock_for_root,
    new_id,
    read_json_file,
    safe_id_component,
    safe_relative_path,
    transactional_connection,
    utc_now,
)

ALLOWED_MODEL_SCOPES = frozenset({"subject_specific", "population_model"})
KNOWN_CONTRACTS = frozenset({CONTRACT_VERSION})


class ProjectNotFound(PersistenceError):
    pass


class RevisionNotFound(PersistenceError):
    pass


class RevisionImmutableError(PersistenceError):
    pass


def _validate_artifact_refs(root: Path, project_id: str, refs: Any) -> Dict[str, str]:
    if refs is None:
        return {}
    if not isinstance(refs, Mapping):
        raise UnsafePayloadError("artifact_refs must be a mapping")
    out: Dict[str, str] = {}
    project_root = root / "projects" / safe_id_component(project_id, label="project_id")
    for name, rel in refs.items():
        if not isinstance(name, str) or not name:
            raise UnsafePayloadError("artifact_refs keys must be strings")
        if not isinstance(rel, str):
            raise PathEscapeError(f"artifact_refs[{name!r}] must be a relative path string")
        safe_relative_path(project_root, rel, label=f"artifact_refs[{name!r}]")
        out[name] = rel.replace("\\", "/")
    return out


def validate_revision_payload(
    project_id: str,
    payload: Mapping[str, Any],
    *,
    root: Path,
    revision_id: str,
) -> Dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise UnsafePayloadError("revision payload must be a mapping")
    data = canonical_jsonable(dict(payload), label="revision")
    schema = data.get("schema_version")
    if schema is None:
        data["schema_version"] = CONTRACT_VERSION
        schema = CONTRACT_VERSION
    if schema not in KNOWN_CONTRACTS:
        raise SchemaVersionError(f"unknown revision schema_version: {schema!r}")
    payload_project = data.get("project_id")
    if payload_project is None:
        data["project_id"] = project_id
    elif payload_project != project_id:
        raise UnsafePayloadError("revision.project_id does not match save target")
    data["revision_id"] = revision_id
    if "candidate_fit" in data:
        raise UnsafePayloadError(
            "candidate_fit is in-memory only after validated restore; refuse to persist it"
        )
    scope = data.get("model_scope")
    if scope is not None and scope not in ALLOWED_MODEL_SCOPES:
        raise UnsafePayloadError(f"invalid model_scope: {scope!r}")
    if "artifact_refs" in data:
        data["artifact_refs"] = _validate_artifact_refs(root, project_id, data.get("artifact_refs"))
    for key in ("encoder_state", "model_state", "request_spec", "feature_schema", "provenance"):
        if key in data and data[key] is not None:
            data[key] = canonical_jsonable(data[key], label=key)
    return data


class ProjectStore:
    """Immutable revisions under a local store root shared with JobStore."""

    def __init__(self, root: Optional[os.PathLike] = None) -> None:
        chosen = Path(root) if root is not None else None
        if chosen is None:
            from modules.job_store import JobStore

            self.root = JobStore.default().root
        else:
            self.root = init_store_root(chosen)
        self.db_path = self.root / "c11.sqlite"
        self._lock = lock_for_root(self.root)

    def save_revision(self, project_id: str, revision_payload: Mapping[str, Any]) -> str:
        """Persist an immutable revision and return ``revision_id``."""
        safe_project = safe_id_component(project_id, label="project_id")
        requested_id = None
        if isinstance(revision_payload, Mapping):
            requested_id = revision_payload.get("revision_id")
        if requested_id is not None:
            revision_id = safe_id_component(str(requested_id), label="revision_id")
        else:
            revision_id = new_id("rev")
        payload = validate_revision_payload(
            safe_project,
            revision_payload,
            root=self.root,
            revision_id=revision_id,
        )
        relpath = f"projects/{safe_project}/revisions/{revision_id}.json"
        dest = self.root / relpath
        now = utc_now()
        with transactional_connection(self.db_path, self._lock) as conn:
            existing = conn.execute(
                "SELECT 1 FROM revisions WHERE project_id = ? AND revision_id = ?",
                (safe_project, revision_id),
            ).fetchone()
            if existing is not None:
                raise RevisionImmutableError(
                    f"revision {revision_id} of project {safe_project} is immutable"
                )
            proj = conn.execute(
                "SELECT project_id FROM projects WHERE project_id = ?",
                (safe_project,),
            ).fetchone()
            if proj is None:
                conn.execute(
                    """
                    INSERT INTO projects(project_id, latest_revision_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (safe_project, revision_id, now, now),
                )
            else:
                conn.execute(
                    """
                    UPDATE projects SET latest_revision_id = ?, updated_at = ?
                    WHERE project_id = ?
                    """,
                    (revision_id, now, safe_project),
                )
            atomic_write_json(dest, payload)
            conn.execute(
                """
                INSERT INTO revisions(project_id, revision_id, schema_version, relpath, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (safe_project, revision_id, payload["schema_version"], relpath, now),
            )
        return revision_id

    def load_revision(
        self,
        project_id: str,
        revision_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return the immutable revision. ``revision_id=None`` loads latest."""
        safe_project = safe_id_component(project_id, label="project_id")
        with self._lock:
            conn = _connect(self.db_path)
            try:
                if revision_id is None:
                    proj = conn.execute(
                        "SELECT latest_revision_id FROM projects WHERE project_id = ?",
                        (safe_project,),
                    ).fetchone()
                    if proj is None or not proj["latest_revision_id"]:
                        return None
                    revision_id = proj["latest_revision_id"]
                else:
                    revision_id = safe_id_component(revision_id, label="revision_id")
                row = conn.execute(
                    """
                    SELECT relpath, schema_version FROM revisions
                    WHERE project_id = ? AND revision_id = ?
                    """,
                    (safe_project, revision_id),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            return None
        if row["schema_version"] not in KNOWN_CONTRACTS:
            raise SchemaVersionError(
                f"unknown revision schema_version: {row['schema_version']!r}"
            )
        relpath = row["relpath"]
        path = safe_relative_path(self.root, relpath, label="revision relpath")
        if not path.is_file():
            return None
        try:
            data = read_json_file(path)
        except json.JSONDecodeError as exc:
            raise UnsafePayloadError(
                f"revision {revision_id} is not valid JSON; refusing to deserialize"
            ) from exc
        if not isinstance(data, dict):
            raise UnsafePayloadError("revision payload must be a JSON object")
        schema = data.get("schema_version")
        if schema not in KNOWN_CONTRACTS:
            raise SchemaVersionError(f"unknown revision schema_version: {schema!r}")
        canonical_jsonable(data, label="revision")
        if "candidate_fit" in data:
            raise UnsafePayloadError("stored revision contains in-memory-only candidate_fit")
        return data

    def list(self) -> Sequence[Dict[str, Any]]:
        """C10 GET /projects adapter."""
        return self.list_projects()

    def list_projects(self) -> Sequence[Dict[str, Any]]:
        with self._lock:
            conn = _connect(self.db_path)
            try:
                rows = conn.execute(
                    """
                    SELECT project_id, latest_revision_id, created_at, updated_at
                    FROM projects ORDER BY created_at ASC
                    """
                ).fetchall()
            finally:
                conn.close()
        return [dict(r) for r in rows]

    def list_revisions(self, project_id: str) -> Sequence[Dict[str, Any]]:
        safe_project = safe_id_component(project_id, label="project_id")
        with self._lock:
            conn = _connect(self.db_path)
            try:
                rows = conn.execute(
                    """
                    SELECT project_id, revision_id, schema_version, relpath, created_at
                    FROM revisions WHERE project_id = ? ORDER BY created_at ASC
                    """,
                    (safe_project,),
                ).fetchall()
            finally:
                conn.close()
        return [dict(r) for r in rows]
