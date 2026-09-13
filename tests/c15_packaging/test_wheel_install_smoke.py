"""Install the built wheel outside the checkout and import packaged resources.

This is skipped unless C15_INSTALL_SMOKE=1 so the default suite stays cheap.
CI runs it in the dedicated install-smoke job; local verification also sets the flag.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import venv
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_PROFILE_IDS = {
    "abnt-14653-2-custo-reedicao",
    "abnt-14653-2-regressao-mercado",
    "bb-meci-avaliacao-imovel-pf",
    "bcb-res-4676-garantia-imobiliaria",
    "caixa-cr-012-2026-avm-precificacao",
    "susep-seguro-habitacional-dfi",
}

pytestmark = pytest.mark.skipif(
    os.environ.get("C15_INSTALL_SMOKE", "") not in {"1", "true", "yes"},
    reason="Set C15_INSTALL_SMOKE=1 to run the clean-venv wheel install smoke",
)


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _source_catalog() -> dict[str, dict]:
    catalog = {}
    for group in ("normative", "institutions"):
        resources = sorted((REPO_ROOT / "profiles" / group).glob("*.json"))
        assert resources, f"source catalog group is empty: {group}"
        for resource in resources:
            payload = json.loads(resource.read_text(encoding="utf-8"))
            assert payload["id"] not in catalog
            catalog[payload["id"]] = payload
    assert set(catalog) == EXPECTED_PROFILE_IDS
    return catalog


def test_clean_venv_install_imports_resources_and_health(tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    supplied = os.environ.get("C15_WHEEL_PATH")
    build = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(dist)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    ) if not supplied else None
    if build is not None:
        assert build.returncode == 0, build.stderr[-4000:]
    wheels = [Path(supplied).resolve()] if supplied else list(dist.glob("modelapro-*.whl"))
    assert len(wheels) == 1 and wheels[0].is_file()

    venv_dir = tmp_path / "venv"
    venv.create(venv_dir, with_pip=True)
    python = _venv_python(venv_dir)
    constraint = REPO_ROOT / "constraints" / "linux-py3.txt"
    install_cmd = [str(python), "-m", "pip", "install", str(wheels[0])]
    if constraint.is_file():
        install_cmd = [
            str(python),
            "-m",
            "pip",
            "install",
            "-c",
            str(constraint),
            str(wheels[0]),
        ]
    installed = subprocess.run(install_cmd, capture_output=True, text=True, check=False)
    assert installed.returncode == 0, installed.stderr[-4000:]
    checked = subprocess.run(
        [str(python), "-m", "pip", "check"], capture_output=True, text=True, check=False
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr

    probe = r"""
import hashlib, json, os, sys
from pathlib import Path
from importlib.resources import files
import backend, modules, frontend, c15_local
from pyhanko.pdf_utils import reader as pyhanko_reader
from c15_local.launcher import frontend_app_path, frontend_command
from modules.commercial_license import trust_anchor_metadata, trusted_vendor_public_key
from modules import cost_valuation
from modules.qualification_profile import load_catalog, resolve_profile
from modules.digital_signatures import pdf as digital_signature_pdf
from modules.pro_workflow import report_context as pro_report_context
from modules.report_export import docx as report_docx, pdfa as report_pdfa
from modules.valuation_policy import qualification as valuation_qualification

assert not os.environ.get("PYTHONPATH"), os.environ.get("PYTHONPATH")
template = files("modules") / "templates" / "report.html"
css = files("frontend") / "assets" / "styles.css"
manual = files("frontend") / "assets" / "manual.md"
for resource in (template, css, manual):
    assert resource.is_file() and resource.read_bytes(), resource
app = frontend_app_path()
assert app.is_file()
cmd = frontend_command(app, "127.0.0.1", 8501)
assert cmd[1:4] == ["-m", "streamlit", "run"]

catalog = load_catalog()
assert set(catalog) == {
    "abnt-14653-2-custo-reedicao",
    "abnt-14653-2-regressao-mercado",
    "bb-meci-avaliacao-imovel-pf",
    "bcb-res-4676-garantia-imobiliaria",
    "caixa-cr-012-2026-avm-precificacao",
    "susep-seguro-habitacional-dfi",
}
unknown = resolve_profile({"id": "not-in-the-installed-catalog"})
assert unknown["resolved"] is False and unknown["state"] == "unknown", unknown
identity_fields = (
    "id", "version", "source_set_sha256", "purpose", "value_basis", "method",
    "asset_scope", "recipient_id",
)
for profile_id, profile in catalog.items():
    requested = {key: profile.get(key) for key in identity_fields}
    resolved = resolve_profile(requested)
    assert resolved["resolved"] is True, (profile_id, resolved)
    assert resolved["id"] == profile_id
    for field in ("version", "source_set_sha256", "purpose", "value_basis", "method", "asset_scope", "recipient_id"):
        assert resolved.get(field) == profile.get(field), (profile_id, field)
    for field in ("version", "source_set_sha256", "purpose", "value_basis", "method", "asset_scope", "recipient_id"):
        divergent = dict(requested)
        divergent[field] = "installed-artifact-divergence"
        refused = resolve_profile(divergent)
        assert refused["resolved"] is False, (profile_id, field, refused)
        if field == "version":
            assert refused["requested_version"] == "installed-artifact-divergence"
        else:
            assert field in refused["mismatches"], (profile_id, field, refused)

anchor = trust_anchor_metadata()
assert anchor["schema"] == "MP-COM-TRUSTED-VENDOR/1"
assert anchor["state"] == "UNCONFIGURED"
assert anchor["environment"] == "production"
assert anchor["algorithm"] == "Ed25519"
assert anchor["purpose"] == "buyer_entitlement"
os.environ["MODELA_TEST_CONTEXT"] = "1"
os.environ["MODELA_LICENSE_PUBLIC_KEY"] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
try:
    trusted_vendor_public_key()
except ValueError as exc:
    assert "not configured" in str(exc)
else:
    raise AssertionError("ordinary installed wheel unexpectedly has a buyer-entitlement key")

module_paths = {
    "backend": backend.__file__,
    "modules": modules.__file__,
    "frontend": frontend.__file__,
    "c15_local": c15_local.__file__,
    "pyhanko_reader": pyhanko_reader.__file__,
    "digital_signatures": digital_signature_pdf.__file__,
    "cost_valuation": cost_valuation.__file__,
    "pro_workflow": pro_report_context.__file__,
    "report_docx": report_docx.__file__,
    "report_pdfa": report_pdfa.__file__,
    "valuation_policy": valuation_qualification.__file__,
}
for name, module_path in module_paths.items():
    assert module_path, name
    assert Path(module_path).resolve().is_relative_to(Path(sys.prefix).resolve()), (name, module_path, sys.prefix)
print(json.dumps({
    "module_paths": module_paths,
    "template": str(template),
    "css": str(css),
    "manual": str(manual),
    "resource_sha256": {
        "template": hashlib.sha256(template.read_bytes()).hexdigest(),
        "css": hashlib.sha256(css.read_bytes()).hexdigest(),
        "manual": hashlib.sha256(manual.read_bytes()).hexdigest(),
    },
    "catalog": {profile_id: {key: value for key, value in profile.items() if key != "_path"}
                for profile_id, profile in catalog.items()},
    "trust_anchor": anchor,
    "app": str(app),
    "frontend_cmd": cmd,
}, sort_keys=True))
"""
    env = os.environ.copy()
    for variable in (
        "PYTHONPATH",
        "PYTHONHOME",
        "MODELA_TEST_CONTEXT",
        "MODELA_LICENSE_PUBLIC_KEY",
        "MODELA_BUILD_TRUSTED_ANCHOR",
    ):
        env.pop(variable, None)
    env["MODELA_SKIP_DOTENV"] = "1"
    env["MODELA_RUNTIME_ROOT"] = str(tmp_path / "runtime")
    env["MODELA_STORE_ROOT"] = str(tmp_path / "runtime" / "store")
    ran = subprocess.run(
        [str(python), "-c", probe],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stdout + ran.stderr
    payload = json.loads(ran.stdout.splitlines()[-1])
    assert all(
        "site-packages" in module_path.replace("\\", "/")
        for module_path in payload["module_paths"].values()
    )
    assert "modela-pro-c15" not in payload["template"]
    assert payload["catalog"] == _source_catalog()
    assert payload["resource_sha256"]["manual"] == hashlib.sha256(
        (REPO_ROOT / "frontend" / "assets" / "manual.md").read_bytes()
    ).hexdigest()

    port = _free_port()
    env["API_HOST"] = "127.0.0.1"
    env["API_PORT"] = str(port)
    env["API_PUBLIC_URL"] = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [str(python), "-m", "uvicorn", "backend.api:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(tmp_path),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        from c15_local.launcher import wait_for_health

        body = wait_for_health(f"http://127.0.0.1:{port}/health", timeout=40)
        assert body.get("status") == "healthy"
    finally:
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()
