"""Exercise an installed MODELA PRO Windows bundle and preserve fail-closed evidence.

All data, documentary declarations, credentials and entitlement used here are
ephemeral TEST fixtures.  The result is product/installer evidence only; it is
not professional review, institutional acceptance or a commercial release.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import platform
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any


TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BUILD_IDENTITY_FILENAME = "build-source-identity.json"
_INNO_RUNTIME_FILE_RE = re.compile(
    r"^unins[0-9]{3}\.(?:exe|dat|log)$", re.IGNORECASE
)
PROFILE = {
    "id": "abnt-14653-2-regressao-mercado",
    "version": "1.0.0",
    "source_set_sha256": "48b82b024c2e7da2137978d521442ef4091f61c8031d1825858af30c367c4209",
    "purpose": "garantia",
    "value_basis": "valor_de_mercado",
    "method": "metodo_comparativo_direto_regressao",
    "asset_scope": "imovel_urbano",
}
REQUIRED_ARTIFACTS = ("frozen_project.json", "report.pdf", "report.docx", "evidence_bundle.zip")
VOLATILE_RESULT_PATHS = frozenset(
    {
        ("code_sha",),
        ("generated_at",),
        ("job_id",),
        ("provenance", "qualification_context", "report_content_fingerprint"),
        ("provenance", "qualification_context", "result_fingerprint"),
        ("search", "audit", "profile", "elapsed_s"),
        ("search", "audit", "profile", "rss_bytes_after"),
        ("search", "audit", "profile", "rss_bytes_before"),
    }
)


class VerificationError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _host_identity() -> dict[str, Any]:
    """Record non-identifying OS/build facts for the scope of this evidence."""
    identity: dict[str, Any] = {
        "system": platform.system(),
        "machine": platform.machine(),
        "python_architecture": platform.architecture()[0],
    }
    if os.name == "nt":
        release, version, service_pack, product_type = platform.win32_ver()
        windows = sys.getwindowsversion()
        identity.update(
            {
                "windows_release": release,
                "windows_version": version,
                "windows_edition": platform.win32_edition(),
                "windows_build": windows.build,
                "windows_platform_version": windows.platform_version,
                "windows_service_pack": service_pack,
                "windows_product_type": product_type,
            }
        )
    return identity


def _verify_installed_bundle(
    install_dir: Path, inventory_path: Path, evidence_path: Path
) -> dict[str, Any]:
    """Match the complete installed file tree to its pre-installer inventory."""
    result: dict[str, Any] = {
        "schema_version": "MP-COM-WINDOWS-INSTALLED-BUNDLE/1",
        "status": "RUNNING",
        "install_dir": str(install_dir),
        "inventory": str(inventory_path),
        "host": _host_identity(),
    }
    try:
        payload = json.loads(inventory_path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise VerificationError("bundle inventory must be a JSON object")
        if payload.get("schema_version") != "MP-COM-WINDOWS-BUNDLE-INVENTORY/1":
            raise VerificationError("bundle inventory schema is unsupported")
        files = payload.get("files")
        if not isinstance(files, list) or not files:
            raise VerificationError("bundle inventory files must be a non-empty list")

        install_root = install_dir.resolve(strict=True)
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(files):
            if not isinstance(item, dict):
                raise VerificationError(f"bundle inventory file {index} is not an object")
            raw_path = item.get("path")
            size = item.get("size")
            digest = item.get("sha256")
            if not isinstance(raw_path, str):
                raise VerificationError(f"bundle inventory file {index} has no path")
            relative = PurePosixPath(raw_path)
            if (
                relative.is_absolute()
                or ":" in raw_path
                or "\\" in raw_path
                or raw_path != relative.as_posix()
                or not relative.parts
                or any(part in {"", ".", ".."} for part in relative.parts)
            ):
                raise VerificationError(f"bundle inventory path is unsafe: {raw_path!r}")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise VerificationError(f"bundle inventory size is invalid: {raw_path}")
            if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
                raise VerificationError(f"bundle inventory hash is invalid: {raw_path}")
            normalized.append({"path": raw_path, "size": size, "sha256": digest})

        paths = [item["path"] for item in normalized]
        if paths != sorted(paths) or len(paths) != len({path.casefold() for path in paths}):
            raise VerificationError(
                "bundle inventory paths must be case-insensitively unique and sorted"
            )
        encoded = json.dumps(
            normalized, sort_keys=True, separators=(",", ":")
        ).encode()
        inventory_digest = hashlib.sha256(encoded).hexdigest()
        if payload.get("file_count") != len(normalized):
            raise VerificationError("bundle inventory file_count does not match files")
        if payload.get("total_size") != sum(item["size"] for item in normalized):
            raise VerificationError("bundle inventory total_size does not match files")
        if payload.get("inventory_sha256") != inventory_digest:
            raise VerificationError("bundle inventory digest does not match files")
        source_sha = str(payload.get("source_sha") or "")
        tree_sha = str(payload.get("tree_sha") or "")
        if not _GIT_SHA_RE.fullmatch(source_sha) or not _GIT_SHA_RE.fullmatch(tree_sha):
            raise VerificationError("bundle inventory has no verified source identity")

        missing: list[str] = []
        mismatched: list[dict[str, Any]] = []
        expected_paths = set(paths)
        for item in normalized:
            target = install_root.joinpath(*PurePosixPath(item["path"]).parts)
            if not target.is_file():
                missing.append(item["path"])
                continue
            try:
                resolved_target = target.resolve(strict=True)
            except OSError:
                missing.append(item["path"])
                continue
            if not resolved_target.is_relative_to(install_root):
                raise VerificationError(
                    f"installed bundle path escapes its root: {item['path']}"
                )
            actual_size = target.stat().st_size
            actual_digest = _sha256_file(target)
            if actual_size != item["size"] or actual_digest != item["sha256"]:
                mismatched.append(
                    {
                        "path": item["path"],
                        "expected_size": item["size"],
                        "actual_size": actual_size,
                        "expected_sha256": item["sha256"],
                        "actual_sha256": actual_digest,
                    }
                )
        actual_paths: set[str] = set()
        escaped_entries: list[str] = []
        for path in install_root.rglob("*"):
            relative_path = path.relative_to(install_root).as_posix()
            is_reparse = path.is_symlink() or (
                hasattr(path, "is_junction") and path.is_junction()
            )
            if is_reparse:
                try:
                    resolved = path.resolve(strict=True)
                except OSError:
                    escaped_entries.append(relative_path)
                    continue
                if not resolved.is_relative_to(install_root):
                    escaped_entries.append(relative_path)
                    continue
            if path.is_file():
                actual_paths.add(relative_path)
        if escaped_entries:
            raise VerificationError(
                f"installed bundle contains escaping reparse entries: {escaped_entries}"
            )
        allowed_inno_paths = sorted(
            path
            for path in actual_paths - expected_paths
            if "/" not in path and _INNO_RUNTIME_FILE_RE.fullmatch(path)
        )
        allowed_inno_files = [
            {
                "path": path,
                "size": (install_root / path).stat().st_size,
                "sha256": _sha256_file(install_root / path),
            }
            for path in allowed_inno_paths
        ]
        unexpected = sorted(actual_paths - expected_paths - set(allowed_inno_paths))
        result.update(
            {
                "declared_file_count": len(normalized),
                "declared_total_size": payload["total_size"],
                "inventory_sha256": inventory_digest,
                "source_sha": source_sha,
                "tree_sha": tree_sha,
                "missing": missing,
                "mismatched": mismatched,
                "unexpected": unexpected,
                "allowed_inno_runtime_files": allowed_inno_files,
            }
        )
        if missing or mismatched or unexpected:
            raise VerificationError(
                "installed bundle differs from inventory: "
                f"missing={len(missing)}, mismatched={len(mismatched)}, "
                f"unexpected={len(unexpected)}"
            )
        identity_path = install_root / BUILD_IDENTITY_FILENAME
        try:
            build_identity = json.loads(identity_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise VerificationError("installed build source identity is absent or invalid") from exc
        if (
            build_identity.get("schema_version") != "MP-COM-BUILD-IDENTITY/1"
            or build_identity.get("source_sha") != source_sha
            or build_identity.get("tree_sha") != tree_sha
        ):
            raise VerificationError(
                "installed build source identity differs from bundle inventory"
            )
        result["status"] = "PASSED"
        return result
    except BaseException as exc:
        result["status"] = "FAILED"
        result["error"] = {"type": type(exc).__name__, "detail": str(exc)}
        raise
    finally:
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _csrf_token(secret_text: str, bearer: str) -> str:
    secret = base64.urlsafe_b64decode(secret_text + "=" * (-len(secret_text) % 4))
    return _b64url(hmac.new(secret, bearer.encode("utf-8"), hashlib.sha256).digest())


def _provision_ephemeral_test_controls(evidence_dir: Path) -> None:
    """Create process-local HTTP controls and require a build-pinned TEST entitlement."""
    os.environ.setdefault("LOCAL_AUTH_TOKEN", _b64url(secrets.token_bytes(32)))
    os.environ.setdefault("LOCAL_CSRF_SECRET", _b64url(secrets.token_bytes(32)))
    license_value = os.environ.get("MODELA_LICENSE_PATH", "").strip()
    if not license_value or not Path(license_value).is_file():
        raise VerificationError("MODELA_LICENSE_PATH must identify the CI TEST entitlement")
    if os.environ.get("MODELA_LICENSE_PUBLIC_KEY"):
        raise VerificationError("runtime public-key environment override must not be present")


def _headers(
    *,
    mutate: bool = False,
    content_type: str | None = None,
    job_token: str | None = None,
) -> dict[str, str]:
    bearer = os.environ["LOCAL_AUTH_TOKEN"]
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Origin": f"http://{os.environ.get('FRONTEND_HOST', '127.0.0.1')}:{os.environ.get('FRONTEND_PORT', '8501')}",
        "X-Workspace-ID": "local",
    }
    if mutate:
        headers["X-CSRF-Token"] = os.environ.get("LOCAL_CSRF_TOKEN") or _csrf_token(
            os.environ["LOCAL_CSRF_SECRET"], bearer
        )
    if content_type:
        headers["Content-Type"] = content_type
    if job_token:
        headers["X-Job-Token"] = job_token
    return headers


def _request(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    mutate: bool = False,
    content_type: str | None = None,
    expected: int = 200,
    job_token: str | None = None,
    timeout: float = 30,
) -> bytes:
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers=_headers(
            mutate=mutate, content_type=content_type, job_token=job_token
        ),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            if response.status != expected:
                raise VerificationError(f"{method} {url} returned HTTP {response.status}")
            return payload
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise VerificationError(f"{method} {url} returned HTTP {exc.code}: {detail}") from exc


def _json_request(
    url: str,
    *,
    method: str = "GET",
    payload: Any = None,
    expected: int = 200,
    job_token: str | None = None,
    timeout: float = 30,
) -> dict:
    body = None
    content_type = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        content_type = "application/json"
    raw = _request(
        url,
        method=method,
        body=body,
        mutate=method not in {"GET", "HEAD", "OPTIONS"},
        content_type=content_type,
        expected=expected,
        job_token=job_token,
        timeout=timeout,
    )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VerificationError(f"{method} {url} did not return JSON") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{method} {url} did not return a JSON object")
    return value


def _multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "modelapro-c06-" + secrets.token_hex(16)
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    for name, (filename, payload, media_type) in files.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode(),
                f"Content-Type: {media_type}\r\n\r\n".encode(),
                payload,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _synthetic_case(*, variant: int = 0) -> tuple[bytes, dict, dict]:
    lines = ["id;bairro;area;preco"]
    for index in range(36):
        area = 50.0 + index * 3.5
        bairro = "Sul" if index % 2 else "Centro"
        error = ((index % 7) - 3) * 713.0
        price = 200000.0 + 3500.0 * area + (40000.0 if bairro == "Sul" else 0.0) + error
        lines.append(f"TESTE-{variant}-{index + 1:03d};{bairro};{area:.6f};{price:.6f}")
    provenance = {
        "professional_id": "TESTE-C06-SEM-VALIDADE-PROFISSIONAL",
        "source": "registro-sintetico-de-teste",
        "recorded_at": "2026-09-12",
        "synthetic": True,
    }
    spec = {
        "schema_version": "MP/1",
        "target_col": "preco",
        "candidate_cols": ["area", "bairro"],
        "roles": {"preco": "target", "area": "predictor", "bairro": "predictor", "id": "identifier"},
        "units": {"area": "m2", "preco": "BRL"},
        "import_options": {"locale": "en-US", "delimiter": ";", "encoding": "utf-8"},
        "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
        "outlier_policy": {"mode": "report_only", "reviewed_exclusions": []},
        "search_policy": {
            "mode": "exact", "budget": 32, "objective": "original_scale_error", "seed": 20260912,
            "y_transformations": ["identity"], "minimum_fundamentacao_grade": None,
            "model_scope": "population_model",
        },
        "evaluation_policy": {"method": "none", "partitions": None, "groups": None, "seed": 20260912},
        "declared_documentary": {
            "item1_grade": 1, "item3_grade": 1,
            "item1": {"grade": 1, "provenance": provenance},
            "item3": {"grade": 1, "provenance": provenance},
            "item1_provenance": provenance, "item3_provenance": provenance,
        },
        "qualification_profile": PROFILE,
        "reference_date": "2026-09-01",
        "inspection_date": "2026-09-02",
        "target_unit": "BRL",
        "applicant": "CASO SINTÉTICO C06 — SEM VALIDADE EXTERNA",
        "purpose": "garantia",
    }
    return ("\n".join(lines) + "\n").encode("utf-8"), spec, {"area": 73.5 + variant, "bairro": "Centro"}


def _wait_ready(api: str, ui: str, timeout: float = 120.0) -> tuple[dict, int]:
    deadline = time.time() + timeout
    last = "not contacted"
    while time.time() < deadline:
        try:
            health = _json_request(api + "/health")
            request = urllib.request.Request(ui, headers={"Origin": ui})
            with urllib.request.urlopen(request, timeout=10) as response:
                ui_bytes = response.read()
                if response.status == 200 and ui_bytes:
                    return health, len(ui_bytes)
                last = f"UI HTTP {response.status}, {len(ui_bytes)} bytes"
        except Exception as exc:  # readiness loop records the final concrete error
            last = str(exc)
        time.sleep(1)
    raise VerificationError(f"backend/UI did not become ready: {last}")


def _start(executable: Path, log_path: Path) -> tuple[subprocess.Popen, Any]:
    if not executable.is_file():
        raise VerificationError(f"installed executable is absent: {executable}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("wb")
    try:
        process = subprocess.Popen(
            [str(executable), "--health-timeout", "120"],
            env=os.environ.copy(),
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=(
                subprocess.CREATE_NEW_PROCESS_GROUP
                if os.name == "nt"
                else 0
            ),
        )
    except BaseException:
        log.close()
        raise
    return process, log


def _open_product_ports() -> list[str]:
    endpoints = [
        (
            os.environ.get("API_HOST", "127.0.0.1"),
            int(os.environ.get("API_PORT", "8000")),
        ),
        (
            os.environ.get("FRONTEND_HOST", "127.0.0.1"),
            int(os.environ.get("FRONTEND_PORT", "8501")),
        ),
    ]
    open_ports = []
    for host, port in endpoints:
        try:
            with socket.create_connection((host, port), timeout=0.25):
                open_ports.append(f"{host}:{port}")
        except OSError:
            pass
    return open_ports


def _wait_for_product_ports_closed(timeout: float = 15.0) -> list[str]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        open_ports = _open_product_ports()
        if not open_ports:
            return []
        time.sleep(0.25)
    return _open_product_ports()


def _windows_descendant_pids(parent_pid: int) -> list[int]:
    """Snapshot descendants before terminating a windowless launcher."""
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    parents: dict[int, int] = {}
    enumeration_error: BaseException | None = None
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        ctypes.set_last_error(0)
        present = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        if not present:
            raise ctypes.WinError(ctypes.get_last_error())
        while present:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            ctypes.set_last_error(0)
            present = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        error = ctypes.get_last_error()
        if error != 18:  # ERROR_NO_MORE_FILES is the sole normal terminator.
            raise ctypes.WinError(error)
    except BaseException as exc:
        enumeration_error = exc
    finally:
        closed = kernel32.CloseHandle(snapshot)
    if enumeration_error is not None:
        raise enumeration_error
    if not closed:
        raise ctypes.WinError(ctypes.get_last_error())
    descendants: set[int] = set()
    changed = True
    while changed:
        changed = False
        for pid, direct_parent in parents.items():
            if pid not in descendants and (
                direct_parent == parent_pid or direct_parent in descendants
            ):
                descendants.add(pid)
                changed = True
    return sorted(descendants)


def _windows_open_process_handles(child_pids: list[int]) -> list[tuple[int, int]]:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    observed: list[tuple[int, int]] = []
    try:
        for pid in child_pids:
            ctypes.set_last_error(0)
            handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
            if not handle:
                error = ctypes.get_last_error()
                if error == 87:  # Process exited between snapshot and OpenProcess.
                    continue
                raise ctypes.WinError(error)
            observed.append((pid, handle))
        return observed
    except BaseException:
        for _pid, handle in observed:
            kernel32.CloseHandle(handle)
        raise


def _wait_for_windows_children_stopped(
    observed: list[tuple[int, int]], timeout: float = 15.0
) -> list[int]:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD

    def alive() -> list[int]:
        running = []
        for pid, handle in observed:
            state = kernel32.WaitForSingleObject(handle, 0)
            if state == 258:  # WAIT_TIMEOUT: the original process still runs.
                running.append(pid)
            elif state != 0:  # WAIT_OBJECT_0: the original process exited.
                raise ctypes.WinError(ctypes.get_last_error())
        return running

    deadline = time.time() + timeout
    while time.time() < deadline:
        running = alive()
        if not running:
            return []
        time.sleep(0.25)
    return alive()


def _windows_close_process_handles(observed: list[tuple[int, int]]) -> list[int]:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return [pid for pid, handle in observed if not kernel32.CloseHandle(handle)]


def _stop(process: subprocess.Popen, log: Any) -> dict[str, Any]:
    shutdown: dict[str, Any] = {"status": "PASSED", "parent_pid": process.pid}
    child_pids: list[int] = []
    observed_children: list[tuple[int, int]] = []
    observation_error = None
    if os.name == "nt":
        try:
            child_pids = _windows_descendant_pids(process.pid)
            observed_children = _windows_open_process_handles(child_pids)
        except BaseException as exc:
            observation_error = f"{type(exc).__name__}: {exc}"
        shutdown["observed_child_pids"] = child_pids
        shutdown["observed_child_handle_count"] = len(observed_children)
    if process.poll() is None:
        if os.name == "nt":
            # Abrupt parent termination is deliberate: the frozen launcher
            # owns both services in a kill-on-close Job Object.  Closed ports
            # prove that containment worked before update or uninstall.
            shutdown["method"] = "parent_termination_with_job_containment"
            process.terminate()
        else:
            process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
            shutdown["forced_parent_kill"] = True
    else:
        shutdown["process_already_exited"] = True
    shutdown["parent_returncode"] = process.returncode
    if os.name == "nt":
        wait_error = None
        try:
            alive_children = _wait_for_windows_children_stopped(observed_children)
        except BaseException as exc:
            alive_children = child_pids
            wait_error = f"{type(exc).__name__}: {exc}"
        close_failures = _windows_close_process_handles(observed_children)
        open_ports = _wait_for_product_ports_closed()
        shutdown["child_processes_exited"] = not alive_children
        shutdown["remaining_child_pids_before_fallback"] = alive_children
        shutdown["service_ports_closed"] = not open_ports
        shutdown["child_observation_error"] = observation_error or wait_error
        shutdown["child_handle_close_failures"] = close_failures
        if observation_error or wait_error or close_failures or alive_children or open_ports:
            # Cleanup is best effort after recording a failed containment
            # check; it must never turn that failure into passing evidence.
            system_root = os.environ.get("SystemRoot", r"C:\Windows").rstrip("\\/")
            taskkill = system_root + r"\System32\taskkill.exe"
            completed = subprocess.run(
                [taskkill, "/IM", "MODELA-PRO.exe", "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=30,
            )
            shutdown["fallback_taskkill_exit_code"] = completed.returncode
            shutdown["status"] = "FAILED"
            shutdown["error"] = {
                "type": "VerificationError",
                "detail": (
                    "launcher termination left installed child processes or service "
                    "observation unresolved: "
                    f"child_pids={alive_children}, ports={open_ports}, "
                    f"observation_error={observation_error or wait_error}, "
                    f"close_failures={close_failures}"
                ),
            }
    return shutdown


def _stable_semantic_result(value: Any, path: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        return {
            key: _stable_semantic_result(item, path + (str(key),))
            for key, item in sorted(value.items())
            if path + (str(key),) not in VOLATILE_RESULT_PATHS
        }
    if isinstance(value, list):
        return [_stable_semantic_result(item, path + (str(index),)) for index, item in enumerate(value)]
    return value


def _document_binding_evidence(generated: dict, snapshot: dict, job_id: str) -> dict:
    document_state = generated.get("document_state") or {}
    qualification = ((snapshot.get("provenance") or {}).get("qualification_context") or {})
    result_fingerprint = generated.get("result_fingerprint")
    report_fingerprint = generated.get("report_content_fingerprint")
    if generated.get("job_id") != job_id:
        raise VerificationError("document response is bound to a different job")
    if not _SHA256_RE.fullmatch(str(result_fingerprint or "")):
        raise VerificationError("document response has no valid result fingerprint")
    if not _SHA256_RE.fullmatch(str(report_fingerprint or "")):
        raise VerificationError("document response has no valid report-content fingerprint")
    if qualification.get("result_fingerprint") != result_fingerprint:
        raise VerificationError("document result fingerprint differs from final snapshot")
    if document_state.get("result_fingerprint") != result_fingerprint:
        raise VerificationError("document-state result fingerprint is inconsistent")
    if document_state.get("report_content_fingerprint") != report_fingerprint:
        raise VerificationError("document-state report-content fingerprint is inconsistent")
    return {
        "job_id": job_id,
        "result_fingerprint": result_fingerprint,
        "report_content_fingerprint": report_fingerprint,
    }


def _validated_document_artifacts(generated: dict) -> dict[str, dict]:
    artifacts = generated.get("artifacts") or {}
    if not isinstance(artifacts, dict) or not set(REQUIRED_ARTIFACTS[1:]).issubset(
        artifacts
    ):
        raise VerificationError(
            f"explicit document generation did not emit required artifacts: {artifacts}"
        )
    for name in REQUIRED_ARTIFACTS[1:]:
        declared = artifacts[name]
        if (
            not isinstance(declared, dict)
            or not isinstance(declared.get("size"), int)
            or isinstance(declared.get("size"), bool)
            or declared["size"] <= 0
            or not _SHA256_RE.fullmatch(str(declared.get("sha256") or ""))
        ):
            raise VerificationError(
                f"document response has invalid hash/size for {name}"
            )
    return artifacts


def _semantic_result_evidence(snapshot: dict, destination: Path) -> str:
    stable = _stable_semantic_result(snapshot)
    encoded = json.dumps(
        stable,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    destination.write_bytes(encoded + b"\n")
    return hashlib.sha256(encoded).hexdigest()


def _browser_probe(browser_python: Path, ui: str, evidence_dir: Path, phase: str) -> dict:
    script = Path(__file__).resolve().with_name("verify_installed_ui.py")
    if not browser_python.is_file() or not script.is_file():
        raise VerificationError("installed-UI browser controller is absent")
    completed = subprocess.run(
        [
            str(browser_python),
            str(script),
            "--url",
            ui,
            "--evidence",
            str(evidence_dir),
            "--phase",
            phase,
        ],
        cwd=Path(__file__).resolve().parents[3],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
        timeout=360,
    )
    evidence_path = evidence_dir / f"{phase}-installed-ui.json"
    if not evidence_path.is_file():
        raise VerificationError(
            "installed-UI browser probe produced no evidence; "
            f"exit={completed.returncode}; stderr={completed.stderr[-1000:]}"
        )
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    if completed.returncode != 0 or payload.get("status") != "PASSED":
        raise VerificationError(
            "installed-UI browser probe failed: "
            f"exit={completed.returncode}; evidence={payload.get('error')}; "
            f"stderr={completed.stderr[-1000:]}"
        )
    return payload


def _run_job(
    api: str,
    evidence_dir: Path,
    variant: int,
    namespace: str,
    expected_code_sha: str,
    *,
    allow_idempotent_replay: bool = False,
) -> tuple[str, dict, dict, str, dict]:
    csv_bytes, spec, subject = _synthetic_case(variant=variant)
    body, media = _multipart(
        {"request_json": json.dumps(spec), "subject_json": json.dumps(subject), "project_id": "TESTE-C06-PROJETO"},
        {"file": ("caso-sintetico-c06.csv", csv_bytes, "text/csv")},
    )
    created_raw = _request(api + "/jobs", method="POST", body=body, mutate=True, content_type=media, expected=202)
    created = json.loads(created_raw)
    job_id = created.get("job_id")
    job_token = created.get("access_token")
    if not job_id:
        raise VerificationError("POST /jobs did not return job_id")
    replayed = created.get("idempotent_replay")
    if type(replayed) is not bool:
        raise VerificationError("POST /jobs did not report idempotent_replay state")
    if replayed and not allow_idempotent_replay:
        raise VerificationError(
            "installed calculation reused an existing job; recalculation was not exercised"
        )
    if not job_token:
        if replayed is not True:
            raise VerificationError("new POST /jobs response did not return access_token")
        recovered = _json_request(
            f"{api}/jobs/{job_id}/access-token",
            method="POST",
            payload={},
        )
        job_token = recovered.get("access_token")
        if not job_token:
            raise VerificationError(
                "authenticated idempotent replay did not recover access_token"
            )
    deadline = time.time() + 300
    status = {}
    while time.time() < deadline:
        status = _json_request(f"{api}/jobs/{job_id}")
        if status.get("state") in TERMINAL:
            break
        time.sleep(0.5)
    if status.get("state") != "succeeded":
        raise VerificationError(f"synthetic job did not succeed: {status}")
    snapshot = _json_request(f"{api}/jobs/{job_id}/result")
    if snapshot.get("code_sha") != expected_code_sha:
        raise VerificationError(
            "calculation snapshot is not bound to the installed build source identity"
        )
    if snapshot.get("job_id") != job_id:
        raise VerificationError("calculation snapshot is bound to a different job")
    qualification = ((snapshot.get("provenance") or {}).get("qualification_context") or {})
    profile = qualification.get("profile") or qualification.get("qualification_profile") or {}
    if profile.get("id") != PROFILE["id"] and qualification.get("profile_id") != PROFILE["id"]:
        raise VerificationError("installed calculation did not preserve the requested packaged profile")
    report_context = {
        "synthetic_test_only": True,
        "applicant": "CASO SINTÉTICO C06 — SEM VALIDADE EXTERNA",
        "rights": "TESTE — plena propriedade sintética",
        "inspection_date": "2026-09-02",
        "asset_identification": {
            "address": "Rua de Teste, 1",
            "registration": "TESTE-C06-001",
        },
        "region_characterization": "TESTE: região urbana sintética",
        "property_characterization": "TESTE: imóvel sintético com 73,5 m²",
        "methodology_justification": "TESTE: método comparativo por regressão",
        "assumptions": ["TESTE: dados exclusivamente sintéticos"],
        "professional_identity": {
            "name": "PROFISSIONAL TESTE",
            "registration": "CREA-TESTE-000",
            "responsibility_document": "ART-TESTE-000",
        },
    }
    generated = _json_request(
        f"{api}/jobs/{job_id}/documents",
        method="POST",
        payload={"report_context": report_context},
        job_token=str(job_token),
        timeout=240,
    )
    generated_artifacts = _validated_document_artifacts(generated)
    (evidence_dir / f"{namespace}-job-{variant}-documents.json").write_text(
        json.dumps(generated, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    # Document composition reassesses and persists qualification/document state.
    snapshot = _json_request(f"{api}/jobs/{job_id}/result")
    if snapshot.get("code_sha") != expected_code_sha or snapshot.get("job_id") != job_id:
        raise VerificationError("final snapshot lost its job/build identity binding")
    document_bindings = _document_binding_evidence(generated, snapshot, job_id)
    for name in REQUIRED_ARTIFACTS:
        artifact_bytes = _request(f"{api}/jobs/{job_id}/artifacts/{name}")
        if not artifact_bytes:
            raise VerificationError(f"installed product returned empty artifact {name}")
        if name.endswith(".pdf") and not artifact_bytes.startswith(b"%PDF"):
            raise VerificationError(f"{name} is not a PDF")
        if name.endswith((".docx", ".zip")) and not artifact_bytes.startswith(b"PK"):
            raise VerificationError(f"{name} is not a ZIP/OOXML container")
        declared_artifact = generated_artifacts.get(name)
        if name in REQUIRED_ARTIFACTS[1:] and (
            declared_artifact.get("size") != len(artifact_bytes)
            or declared_artifact.get("sha256")
            != hashlib.sha256(artifact_bytes).hexdigest()
        ):
            raise VerificationError(
                f"downloaded {name} differs from document response hash/size"
            )
        target = evidence_dir / f"{namespace}-job-{variant}-{name}"
        target.write_bytes(artifact_bytes)
    frozen_path = evidence_dir / f"{namespace}-job-{variant}-frozen_project.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    if (frozen.get("provenance") or {}).get("code_sha") != expected_code_sha:
        raise VerificationError(
            "frozen project is not bound to the installed build source identity"
        )
    saved = _json_request(
        f"{api}/projects/TESTE-C06-PROJETO/revisions",
        method="POST",
        payload=frozen,
        expected=201,
    )
    reopened = _json_request(f"{api}/projects/TESTE-C06-PROJETO")
    if reopened.get("revision", {}).get("revision_id") != saved.get("revision_id"):
        raise VerificationError("saved project revision could not be reopened")
    semantic_hash = _semantic_result_evidence(
        snapshot,
        evidence_dir / f"{namespace}-semantic-result.json",
    )
    return job_id, snapshot, saved, semantic_hash, {
        "idempotent_replay": replayed,
        "recalculation_performed": not replayed,
        "snapshot_code_sha": snapshot.get("code_sha"),
        "frozen_project_code_sha": (frozen.get("provenance") or {}).get("code_sha"),
        "document_bindings": document_bindings,
    }


def _verify_existing_project(api: str) -> dict:
    reopened = _json_request(f"{api}/projects/TESTE-C06-PROJETO")
    revision = reopened.get("revision") or {}
    if not revision.get("revision_id") or not revision.get("model_state"):
        raise VerificationError("existing project did not survive install/version transition")
    return reopened


def _transition_scope(
    previous_source_sha: str,
    previous_tree_sha: str,
    current_source_sha: str,
    current_tree_sha: str,
) -> str:
    if (
        previous_source_sha == current_source_sha
        and previous_tree_sha == current_tree_sha
    ):
        return "OPERATIONAL_SAME_TREE_ONLY"
    if (
        previous_source_sha != current_source_sha
        and previous_tree_sha != current_tree_sha
    ):
        return "DISTINCT_SOURCE_RECALCULATION"
    raise VerificationError("upgrade source/tree identities are only partially distinct")


def _backup(api: str, destination: Path) -> str:
    payload = _request(api + "/operations/backup")
    if not payload.startswith(b"PK"):
        raise VerificationError("backup endpoint did not return a ZIP archive")
    destination.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _restore(api: str, source: Path) -> dict:
    payload = source.read_bytes()
    body, media = _multipart({}, {"file": ("modelapro-backup.zip", payload, "application/zip")})
    restored_raw = _request(
        api + "/operations/restore",
        method="POST",
        body=body,
        mutate=True,
        content_type=media,
        expected=200,
    )
    restored = json.loads(restored_raw)
    if restored.get("status") != "restored":
        raise VerificationError(f"restore endpoint did not confirm restore: {restored}")
    return restored


def verify(args: argparse.Namespace) -> dict:
    evidence_dir = args.evidence.resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _provision_ephemeral_test_controls(evidence_dir)
    api = f"http://{os.environ.get('API_HOST', '127.0.0.1')}:{os.environ.get('API_PORT', '8000')}"
    ui = f"http://{os.environ.get('FRONTEND_HOST', '127.0.0.1')}:{os.environ.get('FRONTEND_PORT', '8501')}"
    result: dict[str, Any] = {
        "schema_version": "MP-COM-WINDOWS-INSTALL/1",
        "phase": args.phase,
        "synthetic_test_data": True,
        "external_acceptance": False,
        "host": _host_identity(),
        "status": "RUNNING",
        "checks": {},
    }
    process = None
    log = None
    try:
        executable = args.executable.resolve()
        if not executable.is_file():
            raise VerificationError(f"installed executable is absent: {executable}")
        executable_bytes = executable.read_bytes()
        result["checks"]["installed_executable"] = {
            "status": "PASSED",
            "path": str(executable),
            "size": len(executable_bytes),
            "sha256": hashlib.sha256(executable_bytes).hexdigest(),
        }
        result["checks"]["installed_bundle_verification"] = _verify_installed_bundle(
            executable.parent,
            args.bundle_inventory.resolve(),
            evidence_dir / f"{args.phase}-installed-bundle.json",
        )
        installed_source_sha = result["checks"]["installed_bundle_verification"][
            "source_sha"
        ]
        installed_tree_sha = result["checks"]["installed_bundle_verification"][
            "tree_sha"
        ]
        stale_ports = _open_product_ports()
        if stale_ports:
            raise VerificationError(
                "installed-product ports were already occupied before launch: "
                + ", ".join(stale_ports)
            )
        process, log = _start(executable, evidence_dir / f"{args.phase}-product.log")
        health, ui_size = _wait_ready(api, ui)
        result["checks"]["backend_and_ui"] = {"status": "PASSED", "health": health, "ui_bytes": ui_size}
        browser_result = _browser_probe(args.browser_python.resolve(), ui, evidence_dir, args.phase)
        result["checks"]["installed_ui_catalog_and_preview"] = {
            "status": "PASSED",
            "scope": browser_result["scope"],
            "playwright_version": browser_result["playwright_version"],
            "browser_version": browser_result["browser_version"],
            "profile_labels": browser_result["profile_labels"],
            "preview_visible": browser_result["preview_visible"],
            "screenshot": browser_result["screenshot"],
        }
        if args.phase == "initial":
            job_id, snapshot, saved, semantic_hash, submission = _run_job(
                api,
                evidence_dir,
                0,
                "initial",
                installed_source_sha,
                allow_idempotent_replay=getattr(
                    args, "allow_idempotent_replay", False
                ),
            )
            result["checks"]["calculate_documents_save_reopen"] = {
                "status": "PASSED", "job_id": job_id, "revision_id": saved["revision_id"],
                "point": (snapshot.get("value") or {}).get("point"),
                "semantic_result_sha256": semantic_hash,
                "source_sha": installed_source_sha,
                "tree_sha": installed_tree_sha,
                **submission,
            }
            result["checks"]["backup"] = {"status": "PASSED", "sha256": _backup(api, args.backup)}
        elif args.phase == "upgrade":
            existing = _verify_existing_project(api)
            initial = json.loads((evidence_dir / "initial.json").read_text(encoding="utf-8"))
            initial_source_sha = initial["checks"]["calculate_documents_save_reopen"][
                "source_sha"
            ]
            initial_job_id = initial["checks"]["calculate_documents_save_reopen"][
                "job_id"
            ]
            initial_tree_sha = initial["checks"]["calculate_documents_save_reopen"][
                "tree_sha"
            ]
            transition_scope = _transition_scope(
                initial_source_sha,
                initial_tree_sha,
                installed_source_sha,
                installed_tree_sha,
            )
            same_identity = transition_scope == "OPERATIONAL_SAME_TREE_ONLY"
            distinct_identity = transition_scope == "DISTINCT_SOURCE_RECALCULATION"
            allow_replay = same_identity
            job_id, snapshot, saved, semantic_hash, submission = _run_job(
                api,
                evidence_dir,
                0,
                "upgrade",
                installed_source_sha,
                allow_idempotent_replay=allow_replay,
            )
            if distinct_identity and job_id == initial_job_id:
                raise VerificationError(
                    "upgrade reused the initial job instead of recalculating"
                )
            expected_hash = initial["checks"]["calculate_documents_save_reopen"][
                "semantic_result_sha256"
            ]
            if semantic_hash != expected_hash:
                raise VerificationError(
                    "recalculation after update changed values, intervals, policies or qualification content"
                )
            result["checks"]["upgrade_reopen_and_recalculate"] = {
                "status": "PASSED", "previous_revision_id": existing["revision"]["revision_id"],
                "new_revision_id": saved["revision_id"], "job_id": job_id,
                "point": (snapshot.get("value") or {}).get("point"),
                "semantic_result_sha256": semantic_hash,
                "matches_initial_result": True,
                "source_sha": installed_source_sha,
                "previous_source_sha": initial_source_sha,
                "tree_sha": installed_tree_sha,
                "previous_tree_sha": initial_tree_sha,
                "verification_scope": transition_scope,
                **submission,
            }
            result["verification_scope"] = result["checks"][
                "upgrade_reopen_and_recalculate"
            ]["verification_scope"]
        elif args.phase == "restore":
            result["checks"]["restore"] = {"status": "PASSED", "response": _restore(api, args.backup)}
            existing = _verify_existing_project(api)
            result["checks"]["rollback_reopen"] = {
                "status": "PASSED", "revision_id": existing["revision"]["revision_id"]
            }
        else:  # argparse prevents this
            raise VerificationError(f"unknown phase {args.phase}")
        result["status"] = "PASSED"
        return result
    except BaseException as exc:
        result["status"] = "FAILED"
        result["error"] = {"type": type(exc).__name__, "detail": str(exc)}
        raise
    finally:
        cleanup_error = None
        raise_cleanup_error = False
        if process is not None and log is not None:
            try:
                shutdown = _stop(process, log)
                result["checks"]["installed_process_shutdown"] = shutdown
                if shutdown.get("status") != "PASSED":
                    raise VerificationError(shutdown["error"]["detail"])
            except BaseException as exc:
                cleanup_error = exc
                if (
                    result["checks"].get("installed_process_shutdown", {}).get(
                        "status"
                    )
                    != "FAILED"
                ):
                    result["checks"]["installed_process_shutdown"] = {
                        "status": "FAILED",
                        "error": {"type": type(exc).__name__, "detail": str(exc)},
                    }
                if result.get("status") == "PASSED":
                    raise_cleanup_error = True
                    result["status"] = "FAILED"
                    result["error"] = {
                        "type": type(exc).__name__,
                        "detail": str(exc),
                    }
            finally:
                log.close()
        (evidence_dir / f"{args.phase}.json").write_text(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        if cleanup_error is not None and raise_cleanup_error:
            raise cleanup_error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--browser-python", type=Path, required=True)
    parser.add_argument("--bundle-inventory", type=Path, required=True)
    parser.add_argument("--phase", choices=("initial", "upgrade", "restore"), required=True)
    parser.add_argument(
        "--allow-idempotent-replay",
        action="store_true",
        help=(
            "permit a same-source local retry while recording that no recalculation "
            "was proved; hosted distinct-source verification must omit this option"
        ),
    )
    args = parser.parse_args(argv)
    verify(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
