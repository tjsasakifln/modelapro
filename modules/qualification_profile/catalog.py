"""Loader for the qualification-profile catalog (profiles/ on disk).

C05 owns the catalog and the rule; C01 validates/resolves the profile and
composes the context; C02 only CHOOSES a known profile; C03 presents the
qualified result. No consumer writes rules here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .schema import (
    INSTITUTIONAL_ACTS,
    PROFILE_STATES,
    PROFILE_UNKNOWN,
    REQUIRED_PROFILE_FIELDS,
)

#: Repository root, resolved from this file (modules/qualification_profile/).
_ROOT = Path(__file__).resolve().parents[2]
NORMATIVE_DIR = _ROOT / "profiles" / "normative"
INSTITUTIONS_DIR = _ROOT / "profiles" / "institutions"


class ProfileError(ValueError):
    """Structured error for a malformed or unknown profile."""


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def source_set_sha256(sources: List[Mapping[str, Any]]) -> str:
    """Stable digest over the identified source set of a profile.

    Digests the (id, edition_or_version, sha256|url) triples in sorted order,
    so that changing an edition or swapping a source changes the profile's
    source_set_sha256 and therefore invalidates dependent decisions.
    """
    items = sorted(
        (
            str(s.get("id", "")),
            str(s.get("edition_or_version", "")),
            str(s.get("sha256") or s.get("url") or ""),
        )
        for s in sources
    )
    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_catalog() -> Dict[str, Dict[str, Any]]:
    """Every profile on disk, keyed by id. Missing directories yield {}."""
    catalog: Dict[str, Dict[str, Any]] = {}
    for directory in (NORMATIVE_DIR, INSTITUTIONS_DIR):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            data = _read_json(path)
            pid = data.get("id")
            if not pid:
                raise ProfileError(f"perfil sem id: {path}")
            if pid in catalog:
                raise ProfileError(f"id de perfil duplicado: {pid!r}")
            data["_path"] = str(path.relative_to(_ROOT))
            catalog[pid] = data
    return catalog


def known_profile_ids() -> List[str]:
    return sorted(load_catalog())


def resolve_profile(profile: Mapping[str, Any]) -> Dict[str, Any]:
    """Resolve a requested profile against the catalog.

    An unknown id is an ERROR, never a permissive default: a profile that the
    catalog does not know cannot reach ready_for_professional_signoff.
    """
    if not isinstance(profile, Mapping):
        raise ProfileError("qualification_profile deve ser um mapeamento")
    pid = profile.get("id")
    if not pid:
        raise ProfileError("qualification_profile.id ausente")

    catalog = load_catalog()
    known = catalog.get(pid)
    if known is None:
        return {
            "id": pid,
            "state": PROFILE_UNKNOWN,
            "resolved": False,
            "detail": (
                f"Perfil {pid!r} não consta do catálogo. Perfis conhecidos: "
                f"{sorted(catalog)}. Perfil desconhecido impede emissão qualificada."
            ),
        }

    requested_version = profile.get("version")
    catalog_version = known.get("version")
    if requested_version is not None and str(requested_version) != str(catalog_version):
        return {
            "id": pid,
            "state": PROFILE_UNKNOWN,
            "resolved": False,
            "requested_version": requested_version,
            "catalog_version": catalog_version,
            "detail": (
                f"Perfil {pid!r} versão {requested_version!r} solicitada, mas o catálogo "
                f"tem {catalog_version!r}. Versões de perfil não são intercambiáveis."
            ),
        }

    missing = [f for f in REQUIRED_PROFILE_FIELDS if not known.get(f)]
    if missing:
        raise ProfileError(f"perfil {pid!r} incompleto no catálogo: faltam {missing}")

    state = known.get("state", PROFILE_UNKNOWN)
    if state not in PROFILE_STATES:
        raise ProfileError(f"perfil {pid!r} com state inválido: {state!r}")

    act = known.get("act_type_established")
    if act is not None and act not in INSTITUTIONAL_ACTS:
        raise ProfileError(f"perfil {pid!r} com act_type_established inválido: {act!r}")

    declared = known.get("source_set_sha256")
    computed = source_set_sha256(known.get("sources") or [])
    if declared and declared != computed:
        raise ProfileError(
            f"perfil {pid!r}: source_set_sha256 declarado {declared!r} != "
            f"calculado {computed!r}; o conjunto de fontes mudou sem atualizar o perfil."
        )

    resolved = dict(known)
    resolved["resolved"] = True
    resolved["state"] = state
    resolved["source_set_sha256"] = computed
    resolved["recipient_id"] = profile.get("recipient_id") or known.get("recipient_id")
    return resolved
