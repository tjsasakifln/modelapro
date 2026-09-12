"""C06 regressions for the installed qualification-profile catalog."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from modules.qualification_profile import ProfileError, load_catalog, resolve_profile
from modules.qualification_profile import catalog as catalog_module


ROOT = Path(__file__).resolve().parents[3]
EXPECTED_IDS = {
    "abnt-14653-2-custo-reedicao",
    "abnt-14653-2-regressao-mercado",
    "bb-meci-avaliacao-imovel-pf",
    "bcb-res-4676-garantia-imobiliaria",
    "caixa-cr-012-2026-avm-precificacao",
    "susep-seguro-habitacional-dfi",
}
SEMANTIC_FIELDS = ("purpose", "value_basis", "method", "asset_scope", "recipient_id")


def _catalog_identity(catalog: dict) -> dict:
    return {
        profile_id: {
            key: value
            for key, value in profile.items()
            if key != "_path"
        }
        for profile_id, profile in catalog.items()
    }


def test_catalog_has_the_six_announced_versioned_resources() -> None:
    catalog = load_catalog()
    assert set(catalog) == EXPECTED_IDS
    assert all(profile["version"] for profile in catalog.values())
    assert all(profile["source_set_sha256"] for profile in catalog.values())


@pytest.mark.parametrize("field", ("source_set_sha256", *SEMANTIC_FIELDS))
def test_requested_catalog_identity_mismatch_is_refused(field: str) -> None:
    known = load_catalog()["bb-meci-avaliacao-imovel-pf"]
    request = {
        key: known.get(key)
        for key in ("id", "version", "source_set_sha256", *SEMANTIC_FIELDS)
    }
    request[field] = "unexpected-catalog-identity"
    result = resolve_profile(request)
    assert result["resolved"] is False
    assert result["state"] == "unknown"
    assert field in result["mismatches"]


def test_missing_catalog_group_is_a_hard_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    empty_package = tmp_path / "profiles"
    empty_package.mkdir()
    monkeypatch.setattr(catalog_module, "_resource_root", lambda: empty_package)
    with pytest.raises(ProfileError, match="grupo obrigatório.*ausente"):
        load_catalog()


def test_wheel_and_sdist_carry_the_exact_source_catalog_and_work_from_arbitrary_cwd(
    tmp_path: Path,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-build-isolation", "--no-deps", "-w", str(dist), str(ROOT)],
        check=True,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [sys.executable, "setup.py", "sdist", "--dist-dir", str(dist)],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    wheel = next(dist.glob("modelapro-*.whl"))
    sdist = next(dist.glob("modelapro-*.tar.gz"))
    expected_members = {
        f"profiles/{group}/{path.name}"
        for group in ("normative", "institutions")
        for path in (ROOT / "profiles" / group).glob("*.json")
    }
    with zipfile.ZipFile(wheel) as archive:
        assert expected_members <= set(archive.namelist())
    with tarfile.open(sdist, "r:gz") as archive:
        names = {"/".join(name.split("/")[1:]) for name in archive.getnames()}
        assert expected_members <= names

    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )
    arbitrary_cwd = tmp_path / "outside-checkout" / "nested"
    arbitrary_cwd.mkdir(parents=True)
    command = (
        "import json; from modules.qualification_profile import load_catalog; "
        "print(json.dumps(load_catalog(), sort_keys=True, ensure_ascii=False))"
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    installed = subprocess.run(
        [str(python), "-I", "-c", command],
        check=True,
        cwd=arbitrary_cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    assert _catalog_identity(json.loads(installed.stdout)) == _catalog_identity(load_catalog())

