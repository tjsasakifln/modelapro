"""Local transactional persistence for jobs, snapshots and light status.

C11 owns this module. HTTP composition stays in C10. Storage is a SQLite
file plus JSON artifacts under an injectable root (never the source tree
by default). User-supplied pickle and path traversal are rejected; model
objects are not restored by executing unknown bytes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Set

CONTRACT_VERSION = "MP/1"
STORAGE_SCHEMA_VERSION = 1
STORE_DB_NAME = "c11.sqlite"

JOB_STATES = frozenset(
    {"queued", "running", "succeeded", "failed", "cancelled", "interrupted"}
)
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
VALID_TRANSITIONS = {
    "queued": frozenset({"running", "cancelled", "failed"}),
    "running": frozenset({"succeeded", "failed", "cancelled", "interrupted"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "interrupted": frozenset(),
}
ARTIFACT_STATES = frozenset({"pending", "running", "ready", "failed"})
ISSUE_SEVERITIES = frozenset({"info", "warning", "error"})

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_UNSAFE_MARKERS = frozenset(
    {
        "__pickle__",
        "__reduce__",
        "__reduce_ex__",
        "__setstate__",
        "py/object",
        "py/reduce",
        "py/function",
        "model_object",
        "base_frame",
        "raw_frame",
        "parsed_frame",
    }
)

_root_locks_guard = threading.Lock()
_root_locks: Dict[str, threading.RLock] = {}
_default_guard = threading.RLock()
_default_store: Optional["JobStore"] = None
_auto_recovered_roots: Set[str] = set()


class PersistenceError(Exception):
    """Base error for local job/project persistence."""


class JobNotFound(PersistenceError):
    pass


class InvalidTransition(PersistenceError):
    pass


class StaleState(PersistenceError):
    pass


class SchemaVersionError(PersistenceError):
    pass


class PathEscapeError(PersistenceError):
    pass


class UnsafePayloadError(PersistenceError):
    pass


class SnapshotAbsent:
    """Sentinel type documenting explicit snapshot absence.

    ``get_snapshot`` returns ``None`` (this absence). The class exists so
    C10 can import a named token for HTTP mapping without treating ``{}``
    as a successful empty snapshot.
    """

    def __bool__(self) -> bool:
        return False


SNAPSHOT_ABSENT = SnapshotAbsent()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def default_store_root() -> Path:
    env = os.environ.get("MODELA_STORE_ROOT")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "modelapro" / "store"
    return Path.home() / ".local" / "share" / "modelapro" / "store"


def lock_for_root(root: Path) -> threading.RLock:
    key = str(root.resolve())
    with _root_locks_guard:
        lock = _root_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _root_locks[key] = lock
        return lock


def _chmod_file(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def ensure_directory(path: Path, mode: int = 0o700) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _chmod_file(path, mode)
    return path


def safe_id_component(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_TOKEN.match(value):
        raise PathEscapeError(f"unsafe {label}: {value!r}")
    return value


def safe_relative_path(root: Path, user_path: str, *, label: str = "path") -> Path:
    if not isinstance(user_path, str) or not user_path.strip():
        raise PathEscapeError(f"empty {label}")
    if "\x00" in user_path:
        raise PathEscapeError(f"{label} contains a null byte")
    raw = user_path.replace("\\", "/")
    if raw.startswith("/") or raw.startswith("~") or "://" in raw:
        raise PathEscapeError(f"absolute {label} is not allowed")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise PathEscapeError(f"{label} escapes the store root")
    for part in parts:
        if part in (".", "..") or "\x00" in part:
            raise PathEscapeError(f"unsafe {label} segment")
    root_res = root.resolve()
    candidate = (root_res.joinpath(*parts)).resolve()
    try:
        candidate.relative_to(root_res)
    except ValueError as exc:
        raise PathEscapeError(f"{label} escapes the store root") from exc
    return candidate


def _reject_default(obj: Any) -> Any:
    raise UnsafePayloadError(
        f"refusing to persist non-JSON object of type {type(obj).__name__}"
    )


def _walk_reject_unsafe(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, inner in value.items():
            key_s = str(key)
            if key_s in _UNSAFE_MARKERS:
                raise UnsafePayloadError(
                    f"refusing to persist executable or in-memory key {key_s!r} at {path}"
                )
            _walk_reject_unsafe(inner, path=f"{path}.{key_s}")
        return
    if isinstance(value, (list, tuple)):
        for i, inner in enumerate(value):
            _walk_reject_unsafe(inner, path=f"{path}[{i}]")
        return
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise UnsafePayloadError(f"refusing to persist raw bytes at {path}")


def canonical_jsonable(value: Any, *, label: str = "payload") -> Any:
    """Validate a mapping/list as JSON (no NaN/Inf, no pickle, no bytes)."""
    if value is None:
        return None
    _walk_reject_unsafe(value)
    try:
        dumped = json.dumps(value, allow_nan=False, default=_reject_default)
        return json.loads(dumped)
    except (TypeError, ValueError) as exc:
        raise UnsafePayloadError(f"invalid JSON for {label}: {exc}") from exc


def atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    if not isinstance(data, (bytes, bytearray)):
        raise UnsafePayloadError("artifact payload must be bytes")
    ensure_directory(path.parent)
    fd, tmp_name = _mkstemp_in(path.parent, suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(bytes(data))
            handle.flush()
            os.fsync(handle.fileno())
        _chmod_file(tmp_path, mode)
        os.replace(str(tmp_path), str(path))
        _chmod_file(path, mode)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, value: Any, *, mode: int = 0o600) -> None:
    ensure_directory(path.parent)
    payload = canonical_jsonable(value, label=str(path.name))
    fd, tmp_name = _mkstemp_in(path.parent, suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, allow_nan=False, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        _chmod_file(tmp_path, mode)
        os.replace(str(tmp_path), str(path))
        _chmod_file(path, mode)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise


def _mkstemp_in(directory: Path, suffix: str) -> tuple:
    import tempfile

    return tempfile.mkstemp(prefix="c11-", suffix=suffix, dir=str(directory))


def read_json_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_issue(issue: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(issue, Mapping):
        raise UnsafePayloadError("issue must be a mapping")
    code = issue.get("code")
    severity = issue.get("severity")
    origin = issue.get("origin")
    message = issue.get("message")
    if not isinstance(code, str) or not code:
        raise UnsafePayloadError("issue.code is required")
    if severity not in ISSUE_SEVERITIES:
        raise UnsafePayloadError(f"invalid issue.severity: {severity!r}")
    if not isinstance(origin, str) or not origin:
        raise UnsafePayloadError("issue.origin is required")
    if not isinstance(message, str) or not message:
        raise UnsafePayloadError("issue.message is required")
    affected = issue.get("affected_ids", [])
    evidence = issue.get("evidence", {})
    if affected is None:
        affected = []
    if evidence is None:
        evidence = {}
    if not isinstance(affected, list) or not all(isinstance(x, str) for x in affected):
        raise UnsafePayloadError("issue.affected_ids must be a list of strings")
    if not isinstance(evidence, Mapping):
        raise UnsafePayloadError("issue.evidence must be a mapping")
    return {
        "code": code,
        "severity": severity,
        "origin": origin,
        "message": message,
        "affected_ids": list(affected),
        "evidence": canonical_jsonable(dict(evidence), label="issue.evidence"),
    }


def validate_artifact_states(states: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(states, Mapping):
        raise UnsafePayloadError("artifact_states must be a mapping")
    out: Dict[str, Any] = {}
    for name, entry in states.items():
        if not isinstance(name, str) or not _SAFE_TOKEN.match(name):
            raise PathEscapeError(f"unsafe artifact name: {name!r}")
        if not isinstance(entry, Mapping):
            raise UnsafePayloadError(f"artifact_states[{name!r}] must be a mapping")
        state = entry.get("state")
        if state not in ARTIFACT_STATES:
            raise UnsafePayloadError(f"invalid artifact state for {name!r}: {state!r}")
        error = entry.get("error")
        if error is not None:
            error = validate_issue(error)
        out[name] = {"state": state, "error": error}
    return out


def validate_progress(progress: Any) -> Optional[float]:
    if progress is None:
        return None
    try:
        value = float(progress)
    except (TypeError, ValueError) as exc:
        raise UnsafePayloadError("progress must be null or a number in [0, 1]") from exc
    if value != value or value in (float("inf"), float("-inf")):
        raise UnsafePayloadError("progress must be finite")
    if value < 0.0 or value > 1.0:
        raise UnsafePayloadError("progress must be null or in [0, 1]")
    return value


def compute_idempotency_key(
    *,
    revision_id: Optional[str],
    request_spec: Optional[Mapping[str, Any]],
    input_sha256: Optional[str],
    dataset_sha256: Optional[str],
    code_sha: Optional[str],
) -> Optional[str]:
    """Return a complete idempotency key, or None if any required part is missing."""
    if not revision_id or not input_sha256 or not dataset_sha256 or not code_sha:
        return None
    if not isinstance(request_spec, Mapping):
        return None
    canonical = canonical_jsonable(
        {
            "revision_id": revision_id,
            "request_spec": request_spec,
            "input_sha256": input_sha256,
            "dataset_sha256": dataset_sha256,
            "code_sha": code_sha,
        },
        label="idempotency_key",
    )
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def make_issue(
    *,
    code: str,
    message: str,
    severity: str = "info",
    origin: str = "c11.job_store",
    affected_ids: Optional[Sequence[str]] = None,
    evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    return validate_issue(
        {
            "code": code,
            "severity": severity,
            "origin": origin,
            "message": message,
            "affected_ids": list(affected_ids or []),
            "evidence": dict(evidence or {}),
        }
    )


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = FULL")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.Error:
        pass
    return conn


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            latest_revision_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS revisions (
            project_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            relpath TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id, revision_id),
            FOREIGN KEY (project_id) REFERENCES projects(project_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            schema_version TEXT NOT NULL,
            project_id TEXT,
            revision_id TEXT,
            state TEXT NOT NULL,
            stage TEXT,
            progress REAL,
            result_available INTEGER NOT NULL DEFAULT 0,
            artifact_states_json TEXT NOT NULL,
            issues_json TEXT NOT NULL,
            request_spec_json TEXT,
            input_sha256 TEXT,
            dataset_sha256 TEXT,
            code_sha TEXT,
            idempotency_key TEXT UNIQUE,
            snapshot_relpath TEXT,
            access_token TEXT NOT NULL,
            calculation_finished INTEGER NOT NULL DEFAULT 0,
            calculation_state TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN calculation_state TEXT")
    except sqlite3.OperationalError:
        pass


def backup_store_db(db_path: Path, from_version: int) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = db_path.with_name(f"{STORE_DB_NAME}.bak.v{from_version}.{stamp}")
    shutil.copy2(db_path, dest)
    _chmod_file(dest, 0o600)
    return dest


def ensure_schema(conn: sqlite3.Connection, db_path: Path) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'storage_schema_version'"
    ).fetchone()
    if row is None:
        _create_tables(conn)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('storage_schema_version', ?)",
            (str(STORAGE_SCHEMA_VERSION),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('contract_version', ?)",
            (CONTRACT_VERSION,),
        )
        return
    try:
        version = int(row["value"] if isinstance(row, sqlite3.Row) else row[0])
    except (TypeError, ValueError) as exc:
        raise SchemaVersionError("store schema version is not an integer") from exc
    if version > STORAGE_SCHEMA_VERSION:
        raise SchemaVersionError(
            f"store schema {version} is newer than supported {STORAGE_SCHEMA_VERSION}"
        )
    if version < STORAGE_SCHEMA_VERSION:
        backup_store_db(db_path, version)
        raise SchemaVersionError(
            f"store schema {version} requires a documented migration; "
            f"backup created, refusing to mutate in place"
        )
    _create_tables(conn)


def init_store_root(root: Path) -> Path:
    root = Path(root).expanduser().resolve()
    ensure_directory(root)
    db_path = root / STORE_DB_NAME
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_schema(conn, db_path)
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()
    _chmod_file(db_path, 0o600)
    return root


@contextmanager
def transactional_connection(db_path: Path, lock: threading.RLock):
    with lock:
        conn = _connect(db_path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()


def row_to_job(row: sqlite3.Row) -> Dict[str, Any]:
    request_spec = None
    if row["request_spec_json"]:
        request_spec = json.loads(row["request_spec_json"])
    progress = row["progress"]
    if progress is not None:
        progress = float(progress)
    return {
        "schema_version": row["schema_version"],
        "job_id": row["job_id"],
        "project_id": row["project_id"],
        "revision_id": row["revision_id"],
        "state": row["state"],
        "stage": row["stage"],
        "progress": progress,
        "result_available": bool(row["result_available"]),
        "artifact_states": json.loads(row["artifact_states_json"]),
        "issues": json.loads(row["issues_json"]),
        "request_spec": request_spec,
        "input_sha256": row["input_sha256"],
        "dataset_sha256": row["dataset_sha256"],
        "code_sha": row["code_sha"],
        "idempotency_key": row["idempotency_key"],
        "access_token": row["access_token"],
        "calculation_finished": bool(row["calculation_finished"]),
        "calculation_state": _row_value(row, "calculation_state"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_value(row: sqlite3.Row, key: str, default=None):
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


class JobStore:
    """SQLite + atomic JSON job store for a single local operator.

    Public methods required by MP/1 C11:
    ``create``, ``get``, ``update_transition``, ``save_snapshot``, ``get_snapshot``.
    """

    def __init__(
        self,
        root: Optional[os.PathLike] = None,
        *,
        recover_abandoned: bool = True,
    ) -> None:
        chosen = Path(root) if root is not None else default_store_root()
        self.root = init_store_root(chosen)
        self.db_path = self.root / STORE_DB_NAME
        self._lock = lock_for_root(self.root)
        self._adopt_as_process_default()
        if recover_abandoned:
            self.recover_on_open(live_job_ids=())

    def _adopt_as_process_default(self) -> None:
        """First live instance in the process becomes JobStore.default()."""
        global _default_store
        with _default_guard:
            if _default_store is None:
                _default_store = self

    def recover_on_open(
        self, live_job_ids: Optional[Iterable[str]] = None
    ) -> Sequence[str]:
        """Recover abandoned ``running`` jobs at most once per process/root.

        Explicit ``recover_abandoned`` / ``interrupt_stale_running`` still
        always run. ``/ws`` and extra ``JobStore()`` clones must not flip a
        live running job to ``interrupted``.
        """
        key = str(self.root.resolve())
        with _default_guard:
            if key in _auto_recovered_roots:
                return []
            _auto_recovered_roots.add(key)
        return self.recover_abandoned(live_job_ids=live_job_ids)

    @classmethod
    def configure_default(
        cls,
        root: os.PathLike,
        *,
        recover_abandoned: bool = True,
    ) -> "JobStore":
        global _default_store
        store = cls(root, recover_abandoned=recover_abandoned)
        with _default_guard:
            _default_store = store
        return store

    @classmethod
    def default(cls) -> "JobStore":
        """Reuse the process store. Does not open a recovering clone."""
        with _default_guard:
            existing = _default_store
        if existing is not None:
            return existing
        return cls(recover_abandoned=True)

    @classmethod
    def reset_default(cls) -> None:
        global _default_store
        with _default_guard:
            _default_store = None
            _auto_recovered_roots.clear()

    def create(
        self,
        payload: Optional[Mapping[str, Any]] = None,
        *,
        project_id: Optional[str] = None,
        revision_id: Optional[str] = None,
        request_spec: Optional[Mapping[str, Any]] = None,
        input_sha256: Optional[str] = None,
        dataset_sha256: Optional[str] = None,
        code_sha: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        job_id: Optional[str] = None,
        artifact_states: Optional[Mapping[str, Any]] = None,
        issues: Optional[Sequence[Mapping[str, Any]]] = None,
        stage: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist a queued job identity before any work starts.

        Reuses an existing job only when a *complete* idempotency key matches.
        Incomplete keys never reuse a prior result. ``payload`` is the C10
        adapter bag (filename, hashes, request_spec); it is not pickled.
        """
        if isinstance(payload, Mapping):
            project_id = project_id or payload.get("project_id")
            revision_id = revision_id or payload.get("revision_id")
            request_spec = request_spec or payload.get("request_spec")
            input_sha256 = input_sha256 or payload.get("input_sha256")
            dataset_sha256 = dataset_sha256 or payload.get("dataset_sha256")
            code_sha = code_sha or payload.get("code_sha")
            stage = stage or payload.get("stage")
        if project_id is not None:
            safe_id_component(project_id, label="project_id")
        if revision_id is not None:
            safe_id_component(revision_id, label="revision_id")
        if job_id is not None:
            safe_id_component(job_id, label="job_id")
        spec = canonical_jsonable(request_spec, label="request_spec") if request_spec is not None else None
        computed = compute_idempotency_key(
            revision_id=revision_id,
            request_spec=spec,
            input_sha256=input_sha256,
            dataset_sha256=dataset_sha256,
            code_sha=code_sha,
        )
        key = idempotency_key or computed
        artifacts = validate_artifact_states(artifact_states or {})
        issue_list = [validate_issue(i) for i in (issues or [])]
        now = utc_now()
        new_job_id = job_id or new_id("job")
        token = secrets.token_urlsafe(32)

        with transactional_connection(self.db_path, self._lock) as conn:
            if key:
                existing = conn.execute(
                    "SELECT * FROM jobs WHERE idempotency_key = ?",
                    (key,),
                ).fetchone()
                if existing is not None:
                    reused = row_to_job(existing)
                    reused["created"] = False
                    return reused
            if revision_id and project_id:
                rev = conn.execute(
                    "SELECT 1 FROM revisions WHERE project_id = ? AND revision_id = ?",
                    (project_id, revision_id),
                ).fetchone()
                if rev is None:
                    # Additive: jobs may point at a revision that C10 will
                    # persist in the same local root; missing revision is
                    # allowed at create so HTTP can record identity first.
                    pass
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, schema_version, project_id, revision_id, state, stage,
                    progress, result_available, artifact_states_json, issues_json,
                    request_spec_json, input_sha256, dataset_sha256, code_sha,
                    idempotency_key, snapshot_relpath, access_token,
                    calculation_finished, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'queued', ?, NULL, 0, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 0, ?, ?)
                """,
                (
                    new_job_id,
                    CONTRACT_VERSION,
                    project_id,
                    revision_id,
                    stage,
                    json.dumps(artifacts, allow_nan=False),
                    json.dumps(issue_list, allow_nan=False),
                    json.dumps(spec, allow_nan=False) if spec is not None else None,
                    input_sha256,
                    dataset_sha256,
                    code_sha,
                    key,
                    token,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (new_job_id,),
            ).fetchone()
        ensure_directory(self._job_dir(new_job_id))
        created = row_to_job(row)
        created["created"] = True
        return created

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        if not isinstance(job_id, str) or not job_id:
            return None
        with self._lock:
            conn = _connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            return None
        return row_to_job(row)

    def update_transition(
        self,
        job_id: str,
        expected_state: str,
        new_state: str,
        patch: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        if expected_state not in JOB_STATES or new_state not in JOB_STATES:
            raise InvalidTransition(
                f"unknown state in {expected_state!r} -> {new_state!r}"
            )
        patch = dict(patch or {})
        if expected_state == new_state:
            current = self.get(job_id)
            if current is None:
                raise JobNotFound(job_id)
            if current["state"] != expected_state:
                raise StaleState(
                    f"job {job_id} is {current['state']!r}, expected {expected_state!r}"
                )
            return self.patch_record(job_id, patch)
        allowed = VALID_TRANSITIONS.get(expected_state, frozenset())
        if new_state not in allowed:
            raise InvalidTransition(
                f"illegal transition {expected_state!r} -> {new_state!r}"
            )
        with transactional_connection(self.db_path, self._lock) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise JobNotFound(job_id)
            current = row_to_job(row)
            if current["state"] != expected_state:
                raise StaleState(
                    f"job {job_id} is {current['state']!r}, expected {expected_state!r}"
                )
            merged = self._apply_patch(current, patch, new_state=new_state)
            conn.execute(
                """
                UPDATE jobs SET
                    state = ?,
                    stage = ?,
                    progress = ?,
                    result_available = ?,
                    artifact_states_json = ?,
                    issues_json = ?,
                    calculation_finished = ?,
                    calculation_state = ?,
                    updated_at = ?
                WHERE job_id = ? AND state = ?
                """,
                (
                    new_state,
                    merged["stage"],
                    merged["progress"],
                    1 if merged["result_available"] else 0,
                    json.dumps(merged["artifact_states"], allow_nan=False),
                    json.dumps(merged["issues"], allow_nan=False),
                    1 if merged["calculation_finished"] else 0,
                    merged.get("calculation_state"),
                    utc_now(),
                    job_id,
                    expected_state,
                ),
            )
            updated = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if updated is None or updated["state"] != new_state:
                raise StaleState(f"concurrent update of job {job_id}")
            return row_to_job(updated)

    def save_snapshot(self, job_id: str, snapshot: Mapping[str, Any]) -> Dict[str, Any]:
        if not isinstance(snapshot, Mapping):
            raise UnsafePayloadError("snapshot must be a mapping")
        job = self.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        payload = canonical_jsonable(dict(snapshot), label="snapshot")
        relpath = f"jobs/{safe_id_component(job_id, label='job_id')}/snapshot.json"
        dest = self.root / relpath
        atomic_write_json(dest, payload)
        now = utc_now()
        with transactional_connection(self.db_path, self._lock) as conn:
            cur = conn.execute(
                """
                UPDATE jobs SET
                    result_available = 1,
                    calculation_finished = 1,
                    snapshot_relpath = ?,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (relpath, now, job_id),
            )
            if cur.rowcount != 1:
                raise JobNotFound(job_id)
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return row_to_job(row)

    def get_snapshot(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Return the stored snapshot mapping, or ``None`` if absent."""
        job = self.get(job_id)
        if job is None:
            return None
        path = self.root / "jobs" / job_id / "snapshot.json"
        if not path.is_file():
            return None
        try:
            data = read_json_file(path)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        return data

    def verify_access(self, job_id: str, token: Optional[str]) -> bool:
        if not token or not isinstance(token, str):
            return False
        job = self.get(job_id)
        if job is None:
            return False
        stored = job.get("access_token") or ""
        if not stored:
            return False
        try:
            return secrets.compare_digest(stored, token)
        except (TypeError, ValueError):
            return False

    def recover_abandoned(self, live_job_ids: Optional[Iterable[str]] = None) -> Sequence[str]:
        """Flip ``running`` jobs that have no live runner to ``interrupted``.

        Never fabricates ``succeeded``. Existing snapshots remain queryable.
        Mid-search resume is not implemented: there is no checkpoint.
        """
        live: Set[str] = set(live_job_ids or ())
        interrupted: list = []
        issue = make_issue(
            code="abandoned_running",
            message=(
                "Process restarted while this job was running; marked interrupted. "
                "No mid-search resume without a checkpoint."
            ),
            severity="warning",
            evidence={"resume": "not_implemented_without_checkpoint"},
        )
        with transactional_connection(self.db_path, self._lock) as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE state = 'running'"
            ).fetchall()
            now = utc_now()
            for row in rows:
                job_id = row["job_id"]
                if job_id in live:
                    continue
                issues = json.loads(row["issues_json"])
                issues.append(issue)
                conn.execute(
                    """
                    UPDATE jobs SET
                        state = 'interrupted',
                        issues_json = ?,
                        updated_at = ?
                    WHERE job_id = ? AND state = 'running'
                    """,
                    (json.dumps(issues, allow_nan=False), now, job_id),
                )
                interrupted.append(job_id)
        return interrupted

    def interrupt_stale_running(self) -> int:
        """C10 startup adapter: count of abandoned running jobs interrupted."""
        return len(self.recover_abandoned(live_job_ids=()))

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        if not idempotency_key:
            return None
        with self._lock:
            conn = _connect(self.db_path)
            try:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            return None
        return row_to_job(row)

    def list_by_state(self, state: str) -> Sequence[Dict[str, Any]]:
        with self._lock:
            conn = _connect(self.db_path)
            try:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE state = ? ORDER BY created_at ASC",
                    (state,),
                ).fetchall()
            finally:
                conn.close()
        return [row_to_job(r) for r in rows]

    def save_artifact(self, job_id: str, name: str, data: bytes) -> str:
        """Store a named artifact as bytes. Not a second canonical snapshot."""
        job = self.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        if not isinstance(name, str) or name != os.path.basename(name):
            raise PathEscapeError(f"unsafe artifact name: {name!r}")
        if ".." in name or "/" in name or "\\" in name or name.startswith("."):
            raise PathEscapeError(f"unsafe artifact name: {name!r}")
        token = name.replace(".", "_")
        if not _SAFE_TOKEN.match(token):
            raise PathEscapeError(f"unsafe artifact name: {name!r}")
        relpath = f"jobs/{safe_id_component(job_id, label='job_id')}/artifacts/{name}"
        dest = self.root / relpath
        atomic_write_bytes(dest, bytes(data))
        self.patch_record(
            job_id,
            {
                "artifact_states": {
                    name: {"state": "ready", "error": None},
                }
            },
        )
        return relpath

    def get_artifact(self, job_id: str, name: str) -> Optional[bytes]:
        job = self.get(job_id)
        if job is None:
            return None
        if not isinstance(name, str) or name != os.path.basename(name):
            raise PathEscapeError(f"unsafe artifact name: {name!r}")
        if ".." in name or "/" in name or "\\" in name:
            raise PathEscapeError(f"unsafe artifact name: {name!r}")
        path = self.root / "jobs" / safe_id_component(job_id, label="job_id") / "artifacts" / name
        if not path.is_file():
            return None
        try:
            path.resolve().relative_to((self.root / "jobs" / job_id).resolve())
        except ValueError as exc:
            raise PathEscapeError("artifact path escapes job directory") from exc
        return path.read_bytes()

    def patch_record(
        self,
        job_id: str,
        patch: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Update stage/progress/artifact_states/issues without changing ``state``.

        Calculation success and PDF/dossiê generation are independent. C10
        uses this after ``succeeded`` to record artifact_states.
        """
        patch = dict(patch or {})
        with transactional_connection(self.db_path, self._lock) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise JobNotFound(job_id)
            current = row_to_job(row)
            merged = self._apply_patch(current, patch, new_state=current["state"])
            conn.execute(
                """
                UPDATE jobs SET
                    stage = ?,
                    progress = ?,
                    result_available = ?,
                    artifact_states_json = ?,
                    issues_json = ?,
                    calculation_finished = ?,
                    calculation_state = ?,
                    updated_at = ?
                WHERE job_id = ?
                """,
                (
                    merged["stage"],
                    merged["progress"],
                    1 if merged["result_available"] else 0,
                    json.dumps(merged["artifact_states"], allow_nan=False),
                    json.dumps(merged["issues"], allow_nan=False),
                    1 if merged["calculation_finished"] else 0,
                    merged.get("calculation_state"),
                    utc_now(),
                    job_id,
                ),
            )
            updated = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return row_to_job(updated)

    def append_issues(
        self,
        job_id: str,
        issues: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Append issues without changing job state (terminal-safe)."""
        extra = [validate_issue(i) for i in issues]
        with transactional_connection(self.db_path, self._lock) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise JobNotFound(job_id)
            current = json.loads(row["issues_json"])
            for item in extra:
                if item not in current:
                    current.append(item)
            conn.execute(
                "UPDATE jobs SET issues_json = ?, updated_at = ? WHERE job_id = ?",
                (json.dumps(current, allow_nan=False), utc_now(), job_id),
            )
            updated = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return row_to_job(updated)

    def list_jobs(self) -> Sequence[Dict[str, Any]]:
        with self._lock:
            conn = _connect(self.db_path)
            try:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at ASC"
                ).fetchall()
            finally:
                conn.close()
        return [row_to_job(r) for r in rows]

    def _job_dir(self, job_id: str) -> Path:
        safe = safe_id_component(job_id, label="job_id")
        return ensure_directory(self.root / "jobs" / safe)

    def _apply_patch(
        self,
        current: Dict[str, Any],
        patch: Mapping[str, Any],
        *,
        new_state: str,
    ) -> Dict[str, Any]:
        unknown = set(patch) - {
            "stage",
            "progress",
            "artifact_states",
            "issues",
            "result_available",
            "calculation_finished",
            "calculation_state",
        }
        # Additive consumers (C10) may send extra keys; ignore rather than
        # abort a valid state transition.
        _ = unknown
        stage = current.get("stage")
        if "stage" in patch:
            stage = patch["stage"]
            if stage is not None and not isinstance(stage, str):
                raise UnsafePayloadError("stage must be a string or null")
        progress = current.get("progress")
        if "progress" in patch:
            progress = validate_progress(patch["progress"])
        artifacts = dict(current.get("artifact_states") or {})
        if "artifact_states" in patch:
            incoming = validate_artifact_states(patch["artifact_states"] or {})
            artifacts.update(incoming)
        issues = list(current.get("issues") or [])
        if "issues" in patch:
            extra = patch["issues"] or []
            if not isinstance(extra, list):
                raise UnsafePayloadError("patch.issues must be a list")
            issues.extend(validate_issue(i) for i in extra)
        result_available = current.get("result_available", False)
        if "result_available" in patch:
            result_available = bool(patch["result_available"])
        calculation_finished = current.get("calculation_finished", False)
        if "calculation_finished" in patch:
            calculation_finished = bool(patch["calculation_finished"])
        if new_state == "succeeded":
            calculation_finished = True
        calculation_state = current.get("calculation_state")
        if "calculation_state" in patch:
            calculation_state = patch["calculation_state"]
            if calculation_state is not None and not isinstance(calculation_state, str):
                raise UnsafePayloadError("calculation_state must be a string or null")
        if new_state == "succeeded" and calculation_state is None:
            calculation_state = "succeeded"
        if new_state == "failed" and calculation_state is None:
            calculation_state = "failed"
        if calculation_state == "succeeded":
            calculation_finished = True
        return {
            "stage": stage,
            "progress": progress,
            "artifact_states": artifacts,
            "issues": issues,
            "result_available": result_available,
            "calculation_finished": calculation_finished,
            "calculation_state": calculation_state,
        }
