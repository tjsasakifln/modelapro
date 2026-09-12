"""Loader for the qualification-profile catalog shipped with the product.

C05 owns the catalog and the rule; C01 validates/resolves the profile and
composes the context; C02 only CHOOSES a known profile; C03 presents the
qualified result. No consumer writes rules here.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import json
from importlib.resources.abc import Traversable
from typing import Any, Dict, List, Mapping

from .schema import (
    INSTITUTIONAL_ACTS,
    PROFILE_STATES,
    PROFILE_UNKNOWN,
    REQUIRED_PROFILE_FIELDS,
)

CATALOG_PACKAGE = "profiles"
CATALOG_GROUPS = ("normative", "institutions")
REQUEST_IDENTITY_FIELDS = (
    "version",
    "source_set_sha256",
    "purpose",
    "value_basis",
    "method",
    "asset_scope",
    "recipient_id",
)


class ProfileError(ValueError):
    """Structured error for a malformed or unknown profile."""


def _resource_root() -> Traversable:
    """Return the installed catalog root, failing closed when it is absent."""
    try:
        root = importlib.resources.files(CATALOG_PACKAGE)
    except (ModuleNotFoundError, TypeError) as exc:
        raise ProfileError(
            "catálogo de perfis não está instalado; emissão qualificada indisponível"
        ) from exc
    if not root.is_dir():
        raise ProfileError(
            "catálogo de perfis instalado é inválido; emissão qualificada indisponível"
        )
    return root


def _read_json(resource: Traversable) -> Dict[str, Any]:
    try:
        payload = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileError(f"perfil ilegível ou inválido: {resource}") from exc
    if not isinstance(payload, dict):
        raise ProfileError(f"perfil deve ser objeto JSON: {resource}")
    return payload


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
    """Load every packaged profile, keyed by id; absence is a hard error."""
    catalog: Dict[str, Dict[str, Any]] = {}
    root = _resource_root()
    for group in CATALOG_GROUPS:
        directory = root.joinpath(group)
        if not directory.is_dir():
            raise ProfileError(
                f"grupo obrigatório do catálogo ausente: profiles/{group}"
            )
        resources = sorted(
            (item for item in directory.iterdir() if item.is_file() and item.name.endswith(".json")),
            key=lambda item: item.name,
        )
        if not resources:
            raise ProfileError(f"grupo obrigatório do catálogo vazio: profiles/{group}")
        for resource in resources:
            data = _read_json(resource)
            pid = data.get("id")
            if not pid:
                raise ProfileError(f"perfil sem id: profiles/{group}/{resource.name}")
            if pid in catalog:
                raise ProfileError(f"id de perfil duplicado: {pid!r}")
            data["_path"] = f"profiles/{group}/{resource.name}"
            catalog[pid] = data
    if not catalog:
        raise ProfileError("catálogo de perfis instalado está vazio")
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

    mismatches = {}
    for field in REQUEST_IDENTITY_FIELDS:
        requested = profile.get(field)
        if requested is None:
            continue
        expected = computed if field == "source_set_sha256" else known.get(field)
        if requested != expected:
            mismatches[field] = {"requested": requested, "catalog": expected}
    if mismatches:
        return {
            "id": pid,
            "state": PROFILE_UNKNOWN,
            "resolved": False,
            "catalog_version": catalog_version,
            "mismatches": mismatches,
            "detail": (
                f"Referência do perfil {pid!r} diverge do catálogo nos campos "
                f"{sorted(mismatches)}. Identidade normativa e semântica não é coercível."
            ),
        }

    resolved = dict(known)
    resolved["resolved"] = True
    resolved["state"] = state
    resolved["source_set_sha256"] = computed
    resolved["recipient_id"] = known.get("recipient_id")
    return resolved
