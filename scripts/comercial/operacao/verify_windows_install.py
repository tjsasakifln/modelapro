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
import signal
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
VOLATILE_RESULT_KEYS = frozenset(
    {
        "code_sha",
        "completed_at",
        "created_at",
        "duration_seconds",
        "elapsed_seconds",
        "generated_at",
        "job_id",
        "result_snapshot_id",
        "started_at",
        "updated_at",
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


def _stop(process: subprocess.Popen, log: Any) -> None:
    if process.poll() is None:
        if os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    log.close()


def _stable_semantic_result(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _stable_semantic_result(item)
            for key, item in sorted(value.items())
            if key not in VOLATILE_RESULT_KEYS
        }
    if isinstance(value, list):
        return [_stable_semantic_result(item) for item in value]
    return value


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
) -> tuple[str, dict, dict, str]:
    csv_bytes, spec, subject = _synthetic_case(variant=variant)
    body, media = _multipart(
        {"request_json": json.dumps(spec), "subject_json": json.dumps(subject), "project_id": "TESTE-C06-PROJETO"},
        {"file": ("caso-sintetico-c06.csv", csv_bytes, "text/csv")},
    )
    created_raw = _request(api + "/jobs", method="POST", body=body, mutate=True, content_type=media, expected=202)
    created = json.loads(created_raw)
    job_id = created.get("job_id")
    job_token = created.get("access_token")
    if not job_id or not job_token:
        raise VerificationError("POST /jobs did not return job_id and access_token")
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
    generated_artifacts = generated.get("artifacts") or {}
    if not set(REQUIRED_ARTIFACTS[1:]).issubset(generated_artifacts):
        raise VerificationError(
            f"explicit document generation did not emit required artifacts: {generated_artifacts}"
        )
    (evidence_dir / f"{namespace}-job-{variant}-documents.json").write_text(
        json.dumps(generated, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    # Document composition reassesses and persists qualification/document state.
    snapshot = _json_request(f"{api}/jobs/{job_id}/result")
    for name in REQUIRED_ARTIFACTS:
        payload = _request(f"{api}/jobs/{job_id}/artifacts/{name}")
        if not payload:
            raise VerificationError(f"installed product returned empty artifact {name}")
        if name.endswith(".pdf") and not payload.startswith(b"%PDF"):
            raise VerificationError(f"{name} is not a PDF")
        if name.endswith((".docx", ".zip")) and not payload.startswith(b"PK"):
            raise VerificationError(f"{name} is not a ZIP/OOXML container")
        target = evidence_dir / f"{namespace}-job-{variant}-{name}"
        target.write_bytes(payload)
    frozen_path = evidence_dir / f"{namespace}-job-{variant}-frozen_project.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
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
    return job_id, snapshot, saved, semantic_hash


def _verify_existing_project(api: str) -> dict:
    reopened = _json_request(f"{api}/projects/TESTE-C06-PROJETO")
    revision = reopened.get("revision") or {}
    if not revision.get("revision_id") or not revision.get("model_state"):
        raise VerificationError("existing project did not survive install/version transition")
    return reopened


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
            job_id, snapshot, saved, semantic_hash = _run_job(api, evidence_dir, 0, "initial")
            result["checks"]["calculate_documents_save_reopen"] = {
                "status": "PASSED", "job_id": job_id, "revision_id": saved["revision_id"],
                "point": (snapshot.get("value") or {}).get("point"),
                "semantic_result_sha256": semantic_hash,
            }
            result["checks"]["backup"] = {"status": "PASSED", "sha256": _backup(api, args.backup)}
        elif args.phase == "upgrade":
            existing = _verify_existing_project(api)
            job_id, snapshot, saved, semantic_hash = _run_job(api, evidence_dir, 0, "upgrade")
            initial = json.loads((evidence_dir / "initial.json").read_text(encoding="utf-8"))
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
            }
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
        if process is not None and log is not None:
            _stop(process, log)
        (evidence_dir / f"{args.phase}.json").write_text(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--browser-python", type=Path, required=True)
    parser.add_argument("--bundle-inventory", type=Path, required=True)
    parser.add_argument("--phase", choices=("initial", "upgrade", "restore"), required=True)
    args = parser.parse_args(argv)
    verify(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
