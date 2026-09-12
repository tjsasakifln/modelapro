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
import secrets
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
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


class VerificationError(RuntimeError):
    pass


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _csrf_token(secret_text: str, bearer: str) -> str:
    secret = base64.urlsafe_b64decode(secret_text + "=" * (-len(secret_text) % 4))
    return _b64url(hmac.new(secret, bearer.encode("utf-8"), hashlib.sha256).digest())


def _provision_ephemeral_test_controls(evidence_dir: Path) -> None:
    """Create process-local security values and a TEST entitlement, never a release key."""
    os.environ.setdefault("LOCAL_AUTH_TOKEN", _b64url(secrets.token_bytes(32)))
    os.environ.setdefault("LOCAL_CSRF_SECRET", _b64url(secrets.token_bytes(32)))
    if os.environ.get("MODELA_LICENSE_PATH") and os.environ.get("MODELA_LICENSE_PUBLIC_KEY"):
        return
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from modules.commercial_license import make_signed_envelope

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    envelope = make_signed_envelope(
        {
            "license_id": "TESTE-C06-WINDOWS-SEM-VALIDADE-COMERCIAL",
            "expires_on": "2099-12-31",
            "rights": ["calculate", "read", "export"],
            "synthetic": True,
        },
        private_key,
    )
    license_path = evidence_dir / "synthetic-test-entitlement.json"
    license_path.write_text(json.dumps(envelope, sort_keys=True) + "\n", encoding="utf-8")
    os.environ["MODELA_LICENSE_PATH"] = str(license_path)
    os.environ["MODELA_LICENSE_PUBLIC_KEY"] = _b64url(public_key)


def _headers(*, mutate: bool = False, content_type: str | None = None) -> dict[str, str]:
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
    return headers


def _request(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    mutate: bool = False,
    content_type: str | None = None,
    expected: int = 200,
) -> bytes:
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers=_headers(mutate=mutate, content_type=content_type),
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
            if response.status != expected:
                raise VerificationError(f"{method} {url} returned HTTP {response.status}")
            return payload
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise VerificationError(f"{method} {url} returned HTTP {exc.code}: {detail}") from exc


def _json_request(url: str, *, method: str = "GET", payload: Any = None, expected: int = 200) -> dict:
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
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("wb")
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


def _run_job(api: str, evidence_dir: Path, variant: int) -> tuple[str, dict, dict]:
    csv_bytes, spec, subject = _synthetic_case(variant=variant)
    body, media = _multipart(
        {"request_json": json.dumps(spec), "subject_json": json.dumps(subject), "project_id": "TESTE-C06-PROJETO"},
        {"file": ("caso-sintetico-c06.csv", csv_bytes, "text/csv")},
    )
    created_raw = _request(api + "/jobs", method="POST", body=body, mutate=True, content_type=media, expected=202)
    created = json.loads(created_raw)
    job_id = created.get("job_id")
    if not job_id:
        raise VerificationError("POST /jobs did not return job_id")
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
    for name in REQUIRED_ARTIFACTS:
        payload = _request(f"{api}/jobs/{job_id}/artifacts/{name}")
        if not payload:
            raise VerificationError(f"installed product returned empty artifact {name}")
        if name.endswith(".pdf") and not payload.startswith(b"%PDF"):
            raise VerificationError(f"{name} is not a PDF")
        if name.endswith((".docx", ".zip")) and not payload.startswith(b"PK"):
            raise VerificationError(f"{name} is not a ZIP/OOXML container")
        target = evidence_dir / f"job-{variant}-{name}"
        target.write_bytes(payload)
    frozen = json.loads((evidence_dir / f"job-{variant}-frozen_project.json").read_text(encoding="utf-8"))
    saved = _json_request(
        f"{api}/projects/TESTE-C06-PROJETO/revisions",
        method="POST",
        payload=frozen,
        expected=201,
    )
    reopened = _json_request(f"{api}/projects/TESTE-C06-PROJETO")
    if reopened.get("revision", {}).get("revision_id") != saved.get("revision_id"):
        raise VerificationError("saved project revision could not be reopened")
    return job_id, snapshot, saved


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
        "status": "RUNNING",
        "checks": {},
    }
    process, log = _start(args.executable.resolve(), evidence_dir / f"{args.phase}-product.log")
    try:
        health, ui_size = _wait_ready(api, ui)
        result["checks"]["backend_and_ui"] = {"status": "PASSED", "health": health, "ui_bytes": ui_size}
        if args.phase == "initial":
            job_id, snapshot, saved = _run_job(api, evidence_dir, 0)
            result["checks"]["calculate_documents_save_reopen"] = {
                "status": "PASSED", "job_id": job_id, "revision_id": saved["revision_id"],
                "point": (snapshot.get("value") or {}).get("point"),
            }
            result["checks"]["backup"] = {"status": "PASSED", "sha256": _backup(api, args.backup)}
        elif args.phase == "upgrade":
            existing = _verify_existing_project(api)
            job_id, snapshot, saved = _run_job(api, evidence_dir, 1)
            result["checks"]["upgrade_reopen_and_recalculate"] = {
                "status": "PASSED", "previous_revision_id": existing["revision"]["revision_id"],
                "new_revision_id": saved["revision_id"], "job_id": job_id,
                "point": (snapshot.get("value") or {}).get("point"),
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
    parser.add_argument("--phase", choices=("initial", "upgrade", "restore"), required=True)
    args = parser.parse_args(argv)
    verify(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
