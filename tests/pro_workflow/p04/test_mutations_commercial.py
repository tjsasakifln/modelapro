"""Adversarial detectors for the ten commercial claims (C06-A07 + C06-A01).

Each controlled defect is injected into a COPY of a real artifact or payload
-- a snapshot produced by the shipped HTTP/worker path, a runner artifact
directory, an on-disk evidence bundle -- never into product source. Every
detector is exercised twice: it must accept the clean artifact (empty problem
list) and reject the mutated one naming the intended cause.

Two cases are deliberately NOT injected into a real artifact, and say so on
the spot: ``test_defect04_non_identity_y_transformation_is_not_verified``
(a one-field variant of the real S01 snapshot) and the synthetic acceptance
record. Both are labelled in their own docstrings.

Extends, and does not duplicate, tests/fixtures/pro_workflow/mutations.py:
that module covers wrong_coefficient_order, missing_ci,
percent_band_replacing_uncertainty, none_instead_of_holdout, swapped_unit,
omitted_row and incompatible_recommendation on the snapshot. The defects here
are the commercial-claim surface (CI evidence, dossier, qualification
profile, normative rules, third-party reuse, external acceptance).

PRODUCT-SIDE GUARD STATUS (a real finding for the C06 parent). The machine
readable form is ``PRODUCT_SIDE_GUARD_STATUS`` below; this prose and that
mapping must agree, and ``test_defect_inventory_is_complete_and_partitioned``
enforces it.

GUARD_SHIPPED -- a product/tooling guard exists in the repo and is exercised
here end to end:
  1. lost_exit_code      -> scripts/c15_local/aggregate_required.py
                            (check_p04_run / check_junit / check_c16 /
                            verify_artifacts).
  6. missing_attachments -> modules.evidence_bundle.verify_bundle, run
                            against a real on-disk bundle.

GUARD_PARTIAL -- product code constrains part of the surface, but not the
step the defect exploits:
  7. wrong_profile       -- modules/report_presenter/verifier.py
     ::verify_report_consistency does bind document to snapshot, but only
     over value.point, target.unit, formula, used/excluded row ids and
     validation.fundamentacao.grade. Verified by grep: the word
     "profile"/"perfil" does not appear in that file, so
     qualification_profile.id / .version printed in the document is bound to
     nothing.
  8. unverified_rule_passed -- modules/normative_rules.py withholds the
     Tabela 2 grade whenever pending_items is non-empty ("absence is not
     approval") and stamps evidence_status = pending. What is missing is the
     rule-level guard: no code refuses a rule_result that carries
     counts_as_passed (or appears in an approval tally) while its own status
     is "unverified" / "pending_manual" / "error".

GUARD_NONE -- the detector below is a TEST-side validator written for this
campaign; nothing in modules/, backend/ or frontend/ refuses the mutated
artifact at runtime:
  2. empty_result                    -- result_contract documents value.point
     null as a legitimate outcome (Issue + JSON null, never 0) and
     ISSUANCE_STATUSES accepts "ready_for_professional_review" without any
     cross-check that a finite point and a non-empty used sample exist.
  3. method_none                     -- evaluation_policy.method = "none" is
     the documented way to skip C07; no product code refuses a commercial
     "externally validated" claim raised over a method-none run.
  4. tampered_coefficient            -- no product re-derivation of
     value.point from the frozen coefficients + subject design.
  5. tampered_confidence_interval    -- the snapshot records no standard
     error, so interval bounds cannot be re-derived product-side at all.
  9. missing_license                 -- a reuse/licence manifest now exists as
     documentation (docs/comercial/c06/reuse.json, written by a sibling C06
     agent), but no code in modules/, backend/, frontend/ or scripts/ reads
     or enforces it: a component added with no SPDX id would be refused by
     nothing at build or run time.
 10. nonexistent_external_acceptance -- there is no institution_acceptance
     schema in the repo at all; nothing forbids an approval record with no
     external act, evidence ref, date or scope.

FINDINGS about where the effective evaluation policy is observable (defect 3;
established by running the shipped FastAPI/worker path over corpus S01 and
dumping the raw snapshot, not by reading code):

FINDING -- THE SNAPSHOT CARRIES NO REQUEST SPEC. ``provenance`` ships exactly
    ['calculation_version', 'composed_by', 'filename', 'peers',
     'sample_ledger_present', 'subject_categorical_survived',
     'workflow_context'].
    There is no ``provenance.request_spec``. An earlier revision of this file
    created that key itself and then inspected it; the detector now reads
    only surfaces the product emits.

FINDING -- THE EFFECTIVE EVALUATION POLICY IS OBSERVABLE ONLY AS A CACHE-KEY
    COMPONENT, NOT AS VALIDATION EVIDENCE. The one place the shipped snapshot
    always records it is ``search.audit.cache_key_components
    .evaluation_policy``, copied verbatim from the request spec by
    modules/optimal_combination.py::build_search_cache_key and hashed into the
    search cache digest. Nothing under ``validation`` states which evaluation
    method was in force. A reader auditing "was this externally validated?"
    would not find the answer where validation evidence lives.

FINDING -- ``validation.statistical.procedure`` EXISTS ONLY WHEN AN
    EVALUATION WAS ACTUALLY REQUESTED. backend/worker.py::_map_validation adds
    that block only when modules/result_contract.py::is_evaluation_requested
    is true, i.e. only when the method is not "none"/"not_requested"/"skip"
    (result_contract.py:1301-1305, the source of NON_EVALUATION_METHODS
    below). A real method-none run therefore ships ``validation.statistical``
    with NO ``procedure`` key at all -- confirmed on the S01 run.

FINDING -- THE PINNED S01 FIXTURE ITSELF SHIPS method='none'. corpus
    .pinned_identity_spec() sets evaluation_policy.method = "none", so the
    default P04 run is already in the state defect 3 describes. The clean
    half of defect 3 therefore needs a SECOND real run with
    evaluation_policy.method = "holdout"; it is not a hand-edited baseline.

FINDING -- A REAL holdout RUN REPORTS procedure.usable_for_model_selection
    = False, and normalises procedure.method to 'random'
    (modules/model_evaluation.py:489 folds holdout/random_holdout into
    "random"). So even a genuine external-partition run does not, on its own
    evidence, substantiate a commercial "externally validated" claim: the
    product's own C07 output declares the result unusable for model
    selection. The detector accepts such a run (an evaluation did happen) and
    never reads usable_for_model_selection as endorsement.

No claim in this module asserts any certification, approval or external act.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Mapping

# scripts/ is not a package root by default; tests/c15_packaging/conftest.py
# adds it for its own suite. Do the same locally so the shipped aggregator can
# be imported here without touching a conftest another agent owns.
_SCRIPTS = str(Path(__file__).resolve().parents[3] / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from c15_local.aggregate_required import (  # noqa: E402
    CANDIDATE_MODE,
    check_c16,
    check_junit,
    check_p04_run,
    verify_artifacts,
)
from modules.evidence_bundle import MANIFEST_NAME, SCHEMA_VERSION_MP, verify_bundle  # noqa: E402
from modules.result_contract import EVALUATION_METHOD_NONE  # noqa: E402
from tests.fixtures.pro_workflow import corpus  # noqa: E402
from tests.pro_workflow.p04.helpers import client, run_job  # noqa: E402

COMMERCIAL_DEFECTS = (
    "lost_exit_code",
    "empty_result",
    "method_none",
    "tampered_coefficient",
    "tampered_confidence_interval",
    "missing_attachments",
    "wrong_profile",
    "unverified_rule_passed",
    "missing_license",
    "nonexistent_external_acceptance",
)

# Programmatic form of the PRODUCT-SIDE GUARD STATUS section of the module
# docstring. Three values, not two: a consumer reading this mapping must get
# exactly the status the prose claims, and never a harsher one.
GUARD_SHIPPED = "shipped"   # product/tooling code refuses the mutated artifact
GUARD_PARTIAL = "partial"   # product code binds part of the surface, not this step
GUARD_NONE = "none"         # the only detector today is the one in this module

PRODUCT_SIDE_GUARD_STATUS: Dict[str, str] = {
    "lost_exit_code": GUARD_SHIPPED,
    "empty_result": GUARD_NONE,
    "method_none": GUARD_NONE,
    "tampered_coefficient": GUARD_NONE,
    "tampered_confidence_interval": GUARD_NONE,
    "missing_attachments": GUARD_SHIPPED,
    "wrong_profile": GUARD_PARTIAL,
    "unverified_rule_passed": GUARD_PARTIAL,
    "missing_license": GUARD_NONE,
    "nonexistent_external_acceptance": GUARD_NONE,
}

GUARD_STATUSES = (GUARD_SHIPPED, GUARD_PARTIAL, GUARD_NONE)


def defects_with_guard_status(status: str) -> frozenset:
    return frozenset(d for d, s in PRODUCT_SIDE_GUARD_STATUS.items() if s == status)


CANDIDATE_SHA = "3f9a1c7d5b2e4086ac11d9e77b3c05a4f6182d90"

# Methods the PRODUCT treats as "no evaluation was run". Mirrors
# modules/result_contract.py::is_evaluation_requested (result_contract.py:
# 1301-1305), which returns False for a falsy method and for these strings.
NON_EVALUATION_METHODS = frozenset({EVALUATION_METHOD_NONE, "not_requested", "skip", "", None})

# Statuses that may never be counted as a passed normative rule.
NON_PASSING_RULE_STATUSES = frozenset(
    {"unverified", "pending", "pending_manual", "not_computed", "error", "unclassified"}
)


def _deep(obj: Any) -> Any:
    return copy.deepcopy(obj)


def _finite(value: Any) -> bool:
    try:
        return value is not None and not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------
# Detectors. Pure functions: artifact in, list of problem strings out.
# An empty list means clean. No product state is touched.
# --------------------------------------------------------------------------


def finished_valuation_problems(snapshot: Mapping[str, Any]) -> List[str]:
    """Defect 2 -- a snapshot offered as a finished valuation must carry a value.

    value.point null (or no used rows, or no fitted coefficients) is a
    legitimate *unfinished* outcome. It is a defect only when the same
    snapshot is presented as a concluded valuation.
    """
    problems: List[str] = []
    value = snapshot.get("value") or {}
    sample = snapshot.get("sample") or {}
    model = snapshot.get("model") or {}
    issuance = ((snapshot.get("validation") or {}).get("issuance") or {})
    presented = str(issuance.get("status") or "") in {"ready_for_professional_review", "review_required"}
    if not presented:
        return problems
    if not _finite(value.get("point")):
        problems.append(
            f"empty_result: value.point is {value.get('point')!r} while issuance.status is "
            f"{issuance.get('status')!r} (presented as a concluded valuation)"
        )
    used_ids = list(sample.get("used_row_ids") or [])
    if not used_ids or not sample.get("used"):
        problems.append(
            f"empty_result: no rows presented as used (used={sample.get('used')!r}, "
            f"used_row_ids={len(used_ids)}) for a concluded valuation"
        )
    if not (model.get("coefficients") or {}):
        problems.append("empty_result: no fitted coefficients on a concluded valuation")
    return problems


def effective_evaluation_policy(snapshot: Mapping[str, Any]) -> Any:
    """The evaluation policy the shipped search actually ran under, or None.

    ``search.audit.cache_key_components.evaluation_policy`` is copied verbatim
    from the request spec by optimal_combination.build_search_cache_key and
    hashed into the search cache digest, so it is load-bearing product output
    rather than decoration. Returns None (not {}) when the surface is absent,
    so "policy not observable" stays distinguishable from "policy is empty".
    """
    audit = (snapshot.get("search") or {}).get("audit")
    if not isinstance(audit, Mapping):
        return None
    components = audit.get("cache_key_components")
    if not isinstance(components, Mapping) or "evaluation_policy" not in components:
        return None
    return components.get("evaluation_policy")


def external_validation_claim_problems(
    snapshot: Mapping[str, Any], claim: Mapping[str, Any]
) -> List[str]:
    """Defect 3 -- a commercial 'externally validated' claim over method=none.

    Reads only surfaces the shipped worker emits (see the FINDINGS in the
    module docstring): the effective evaluation policy under
    search.audit.cache_key_components, and validation.statistical.procedure,
    which backend/worker.py::_map_validation writes only when an evaluation
    was actually requested. "I cannot observe the policy" is a problem, never
    a pass.
    """
    problems: List[str] = []
    if not claim.get("claims_external_validation"):
        return problems
    claim_id = claim.get("id")
    policy = effective_evaluation_policy(snapshot)
    if policy is None:
        problems.append(
            f"method_none: claim {claim_id!r} asserts external validation but the snapshot "
            "records no effective evaluation policy (no search.audit.cache_key_components"
            ".evaluation_policy); the claim cannot be checked against the artifact"
        )
    else:
        if not isinstance(policy, Mapping):
            problems.append(
                f"method_none: claim {claim_id!r} asserts external validation but the recorded "
                f"evaluation_policy is {policy!r}, not a mapping"
            )
            method: Any = None
        else:
            method = policy.get("method")
        normalised = method.strip().lower() if isinstance(method, str) else method
        if normalised in NON_EVALUATION_METHODS:
            problems.append(
                f"method_none: claim {claim_id!r} asserts external validation while the effective "
                f"evaluation_policy.method is {method!r}"
            )
    statistical = (snapshot.get("validation") or {}).get("statistical")
    statistical = statistical if isinstance(statistical, Mapping) else {}
    if "procedure" not in statistical or not isinstance(statistical.get("procedure"), Mapping):
        problems.append(
            f"method_none: claim {claim_id!r} asserts external validation but "
            "validation.statistical carries no procedure block, so no external evaluation was "
            "executed by the shipped worker"
        )
        return problems
    procedure = statistical["procedure"]
    procedure_method = procedure.get("method")
    proc_normalised = (
        procedure_method.strip().lower() if isinstance(procedure_method, str) else procedure_method
    )
    if proc_normalised in NON_EVALUATION_METHODS:
        problems.append(
            f"method_none: claim {claim_id!r} asserts external validation while "
            f"validation.statistical.procedure.method is {procedure_method!r}"
        )
    if procedure.get("usable_for_model_selection") and proc_normalised in NON_EVALUATION_METHODS:
        problems.append(
            "method_none: procedure declares usable_for_model_selection with no evaluation method"
        )
    return problems


def _design_value(name: str, subject: Mapping[str, Any], transformations: Mapping[str, Any]) -> float:
    raw = subject[name]
    kind = str(transformations.get(name) or "linear")
    x = float(raw)
    if kind in ("linear", "identity"):
        return x
    if kind in ("ln", "log"):
        return math.log(x)
    if kind in ("inv", "inverse", "1/x"):
        return 1.0 / x
    if kind in ("sq", "square", "x2"):
        return x * x
    raise ValueError(f"unsupported transformation {kind!r} for {name!r}")


def point_follows_from_model_problems(
    snapshot: Mapping[str, Any],
    subject: Mapping[str, Any],
    *,
    abs_tol: float = 1.0,
    rel_tol: float = 1e-6,
) -> List[str]:
    """Defect 4 -- the reported point must be reproducible from the frozen model.

    Re-derives point = const + sum(beta_j * design_j(subject)) from the
    snapshot's own coefficients. A coefficient altered after the fit breaks
    this identity even though every field stays well formed.
    """
    problems: List[str] = []
    model = snapshot.get("model") or {}
    coefficients = model.get("coefficients")
    if not isinstance(coefficients, Mapping) or not coefficients:
        return ["tampered_coefficient: no coefficient mapping to re-derive the point from"]
    y_transformation = str(model.get("y_transformation") or "identity")
    if y_transformation != "identity":
        # "I cannot check this" is not "this is clean".
        return [
            f"tampered_coefficient: y_transformation {y_transformation!r} is not re-derivable "
            "by this detector; the point was not verified against the frozen model"
        ]
    transformations = model.get("transformations") or {}
    point = (snapshot.get("value") or {}).get("point")
    if not _finite(point):
        return ["tampered_coefficient: value.point is not finite; cannot check the model identity"]
    total = 0.0
    for name, beta in coefficients.items():
        if name == "const":
            total += float(beta)
            continue
        if name not in subject:
            return [f"tampered_coefficient: subject has no value for design column {name!r}"]
        total += float(beta) * _design_value(name, subject, transformations)
    if abs(total - float(point)) > max(abs_tol, rel_tol * abs(float(point))):
        problems.append(
            f"tampered_coefficient: value.point {float(point)!r} does not follow from the frozen "
            f"coefficients (model implies {total!r})"
        )
    return problems


def interval_matches_reference_problems(
    snapshot: Mapping[str, Any],
    reference: Mapping[str, Any],
    *,
    abs_tol: float = 2.0,
    rel_tol: float = 1e-4,
) -> List[str]:
    """Defect 5 -- interval bounds narrowed while the point stays put.

    The reference is the independent OLS oracle's prediction for the same
    design; the snapshot itself records no standard error, so the bounds are
    only checkable against an outside re-derivation.
    """
    problems: List[str] = []
    value = snapshot.get("value") or {}
    point = value.get("point")
    ref_point = reference.get("point")
    point_intact = _finite(point) and _finite(ref_point) and abs(
        float(point) - float(ref_point)
    ) <= max(abs_tol, rel_tol * abs(float(ref_point)))
    # No standard error is recorded on the snapshot, so only the point is
    # verified as intact here; the suffix below never claims more than that.
    pairs = (("mean_ci80", "mean_ci"), ("prediction_interval", "prediction_interval"))
    for snap_key, ref_key in pairs:
        got = value.get(snap_key)
        want = reference.get(ref_key)
        # An artifact that ships no interval at all is NOT clean: an absent or
        # null interval is exactly how uncertainty gets dropped silently.
        if snap_key not in value:
            problems.append(
                f"tampered_confidence_interval: value.{snap_key} is absent from the snapshot; "
                "no interval was reported and none was verified"
            )
            continue
        if got is None:
            problems.append(
                f"tampered_confidence_interval: value.{snap_key} is None; no interval was "
                "reported and none was verified"
            )
            continue
        if not isinstance(got, Mapping):
            problems.append(
                f"tampered_confidence_interval: value.{snap_key} is {got!r}, not an interval mapping"
            )
            continue
        if not isinstance(want, Mapping):
            # "I have no oracle for this bound" is not "this bound is clean".
            problems.append(
                f"tampered_confidence_interval: no independent re-derivation available for "
                f"{snap_key} (reference.{ref_key} is {want!r}); bounds NOT verified"
            )
            continue
        for bound in ("lower", "upper"):
            a, b = got.get(bound), want.get(bound)
            if not (_finite(a) and _finite(b)):
                problems.append(f"tampered_confidence_interval: {snap_key}.{bound} is not finite")
                continue
            if abs(float(a) - float(b)) > max(abs_tol, rel_tol * abs(float(b))):
                problems.append(
                    f"tampered_confidence_interval: {snap_key}.{bound} is {float(a)!r}, "
                    f"independent re-derivation gives {float(b)!r}"
                    + (" (point unchanged)" if point_intact else "")
                )
    return problems


def profile_binding_problems(
    document: Mapping[str, Any], calculation: Mapping[str, Any]
) -> List[str]:
    """Defect 7 -- the profile printed in the document must be the one computed with."""
    problems: List[str] = []
    doc = document.get("qualification_profile") or {}
    calc = calculation.get("qualification_profile") or {}
    if not doc or not calc:
        return ["wrong_profile: qualification_profile absent from the document or the calculation"]
    for field in ("id", "version"):
        if doc.get(field) != calc.get(field):
            problems.append(
                f"wrong_profile: document qualification_profile.{field}={doc.get(field)!r} but the "
                f"calculation used {calc.get(field)!r}"
            )
    if doc.get("checksum") and calc.get("checksum") and doc["checksum"] != calc["checksum"]:
        problems.append("wrong_profile: qualification_profile.checksum differs between document and calculation")
    return problems


def rule_approval_problems(rule_results: Any, approval: Mapping[str, Any]) -> List[str]:
    """Defect 8 -- only verified rules may be counted toward an approval."""
    problems: List[str] = []
    results = list(rule_results or [])
    counted = approval.get("rules_counted_as_passed")
    counted_ids = set(counted or [])
    for item in results:
        if not isinstance(item, Mapping):
            problems.append(f"unverified_rule_passed: malformed rule_result {item!r}")
            continue
        status = str(item.get("status") or "")
        rule_id = item.get("rule_id", "?")
        if rule_id in counted_ids and status in NON_PASSING_RULE_STATUSES:
            problems.append(
                f"unverified_rule_passed: rule {rule_id!r} has status {status!r} but is counted as passed"
            )
        if status in NON_PASSING_RULE_STATUSES and item.get("counts_as_passed"):
            problems.append(
                f"unverified_rule_passed: rule {rule_id!r} with status {status!r} carries counts_as_passed"
            )
    declared = approval.get("passed_count")
    if declared is not None and declared != len(counted_ids):
        problems.append(
            f"unverified_rule_passed: approval.passed_count={declared!r} but "
            f"{len(counted_ids)} rules are listed as counted"
        )
    return problems


def reuse_manifest_problems(manifest: Mapping[str, Any]) -> List[str]:
    """Defect 9 -- every reused third-party component needs a recorded licence."""
    problems: List[str] = []
    components = manifest.get("components")
    if not isinstance(components, list) or not components:
        return ["missing_license: reuse manifest lists no components"]
    for entry in components:
        if not isinstance(entry, Mapping):
            problems.append(f"missing_license: malformed component entry {entry!r}")
            continue
        name = entry.get("name", "?")
        spdx = str(entry.get("license_spdx") or "").strip()
        if not spdx:
            problems.append(f"missing_license: component {name!r} records no SPDX licence id")
            continue
        if spdx.upper() in {"UNKNOWN", "NOASSERTION", "NONE", "TBD"}:
            problems.append(f"missing_license: component {name!r} records a placeholder licence {spdx!r}")
        if not str(entry.get("license_ref") or "").strip():
            problems.append(f"missing_license: component {name!r} records no licence text reference")
    return problems


def institution_acceptance_problems(record: Mapping[str, Any]) -> List[str]:
    """Defect 10 -- an approval record must point at a real, dated external act."""
    problems: List[str] = []
    if not record.get("asserts_approval"):
        return problems
    institution = record.get("institution", "?")
    for field in ("external_act_ref", "evidence_ref", "date", "scope"):
        if not str(record.get(field) or "").strip():
            problems.append(
                f"nonexistent_external_acceptance: {institution!r} asserts approval with no {field}"
            )
    if record.get("self_declared") is True:
        problems.append(
            f"nonexistent_external_acceptance: {institution!r} approval is self-declared, not an external act"
        )
    return problems


# --------------------------------------------------------------------------
# Clean artifacts, built from real product output or realistic payloads.
# --------------------------------------------------------------------------

_SNAPSHOT_CACHE: Dict[str, Any] = {}


def _run_s01(key: str, spec_overrides: Mapping[str, Any]) -> Dict[str, Any]:
    """Run corpus S01 through the shipped HTTP/worker path and cache the result.

    The snapshot is stored exactly as the product returned it. Nothing is
    added to it here -- in particular no request_spec is grafted onto
    provenance, because the product does not put one there.
    """
    if key not in _SNAPSHOT_CACHE:
        case = corpus.s01_identity_noise_category()
        payload = corpus.rows_to_csv_bytes(case["rows"], case["fieldnames"])
        spec = corpus.pinned_identity_spec(**dict(spec_overrides))
        subject = {"area": corpus.S01_SUBJECT_AREA}
        out = run_job(client(), payload, spec=spec, subject=subject)
        _SNAPSHOT_CACHE[key] = {
            "snapshot": _deep(out["snapshot"]),
            "subject": subject,
            "reference": _deep(case["oracle_area_only"]["prediction"]),
            "spec": _deep(spec),
        }
    return _deep(_SNAPSHOT_CACHE[key])


def _s01_snapshot() -> Dict[str, Any]:
    """Real snapshot from the shipped HTTP/worker path over corpus S01.

    corpus.pinned_identity_spec() pins evaluation_policy.method = "none", so
    this snapshot is already in the method-none state; it is the baseline for
    defects 2, 4 and 5, NOT for the clean half of defect 3.
    """
    return _run_s01("s01", {})


def _s01_holdout_snapshot() -> Dict[str, Any]:
    """Real snapshot from a second shipped run with an external partition.

    evaluation_policy.method = "holdout" is the only clean baseline available
    for defect 3, because the pinned S01 spec ships method = "none". The
    worker then emits validation.statistical.procedure (method normalised to
    'random' by model_evaluation._build_partition).
    """
    return _run_s01(
        "s01_holdout",
        {"evaluation_policy": {"method": "holdout", "partitions": None, "groups": None, "seed": 17}},
    )


def _clean_run_payload(**over: Any) -> Dict[str, Any]:
    payload = {
        "mode": CANDIDATE_MODE,
        "sha": CANDIDATE_SHA,
        "exit_code": 0,
        "skip_xfail_count": 0,
        "findings": [],
        "runs": [
            {"name": "core-1", "returncode": 0, "passed": 120, "failed": 0},
            {"name": "core-2", "returncode": 0, "passed": 120, "failed": 0},
            {"name": "extensions", "returncode": 0, "passed": 12, "failed": 0},
        ],
    }
    payload.update(over)
    return payload


def _clean_c16_payload(**over: Any) -> Dict[str, Any]:
    payload = {
        "sha": CANDIDATE_SHA,
        "counts": {
            "aprovados": 96,
            "reprovados": 0,
            "nao_executados": 0,
            "violacoes_a04_skip_xfail": 0,
            "disjoint": True,
        },
    }
    payload.update(over)
    return payload


def _write_junit(path: Path, *, classname: str, cases: int, skipped: int = 0) -> None:
    suite = ET.Element("testsuite")
    for i in range(cases):
        case = ET.SubElement(suite, "testcase", classname=classname, name=f"t{i}")
        if i < skipped:
            ET.SubElement(case, "skipped", message="gated")
    ET.ElementTree(suite).write(path)


def _write_artifacts_dir(root: Path, *, run_payload: Mapping[str, Any], cases: int = 40) -> Path:
    """Every artifact scripts/c15_local/aggregate_required.verify_artifacts opens.

    The list is the shipped aggregator's, not this file's: install-smoke
    .junit.xml became mandatory (forbid_skips=True) in aggregate_required at
    d2efd11, and the clean half below asserts verify_artifacts returns [], so
    this fixture cannot silently fall behind that contract again.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "run.json").write_text(json.dumps(run_payload), encoding="utf-8")
    (root / "c16.json").write_text(json.dumps(_clean_c16_payload()), encoding="utf-8")
    _write_junit(root / "wide.junit.xml", classname="wide", cases=cases)
    _write_junit(root / "install-smoke.junit.xml", classname="install_smoke", cases=1)
    return root


def _write_bundle(root: Path) -> Dict[str, Any]:
    """A minimal but genuine C12-shaped bundle that verify_bundle accepts."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "policies").mkdir(exist_ok=True)
    payloads = {
        "snapshot.json": json.dumps({"schema_version": SCHEMA_VERSION_MP, "value": {"point": 1.0}}),
        "policies/request_spec.json": json.dumps({"evaluation_policy": {"method": "holdout"}}),
    }
    files = []
    for rel, text in payloads.items():
        path = root / rel
        path.write_text(text, encoding="utf-8")
        raw = path.read_bytes()
        files.append(
            {
                "path": rel,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
                "type": "application/json",
                "version": SCHEMA_VERSION_MP,
                "function": "evidence",
            }
        )
    manifest = {
        "schema_version": SCHEMA_VERSION_MP,
        "bundle_version": "C12/1",
        "input_id": "input-1",
        "code_id": "code-1",
        "schema_id": "schema-1",
        "policy_id": "policy-1",
        "files": files,
    }
    (root / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def _clean_profile_document() -> Dict[str, Any]:
    return {
        "document_id": "LAUDO-0001",
        "qualification_profile": {"id": "nbr14653-2/grau-II", "version": "2011.1", "checksum": "abc123"},
    }


def _clean_profile_calculation() -> Dict[str, Any]:
    return {
        "job_id": "job-0001",
        "qualification_profile": {"id": "nbr14653-2/grau-II", "version": "2011.1", "checksum": "abc123"},
    }


def _clean_rule_results() -> List[Dict[str, Any]]:
    return [
        {"rule_id": "A.5", "status": "verified", "counts_as_passed": True},
        {"rule_id": "A.6", "status": "verified", "counts_as_passed": True},
        {"rule_id": "A.7", "status": "verified", "counts_as_passed": True},
    ]


def _clean_approval() -> Dict[str, Any]:
    return {"rules_counted_as_passed": ["A.5", "A.6", "A.7"], "passed_count": 3}


def _clean_reuse_manifest() -> Dict[str, Any]:
    return {
        "components": [
            {"name": "numpy", "version": "1.26.4", "license_spdx": "BSD-3-Clause", "license_ref": "LICENSES/numpy.txt"},
            {
                "name": "statsmodels",
                "version": "0.14.1",
                "license_spdx": "BSD-3-Clause",
                "license_ref": "LICENSES/statsmodels.txt",
            },
        ]
    }


def _clean_acceptance_record() -> Dict[str, Any]:
    """A record that is honest because it asserts no approval at all."""
    return {
        "institution": "instituicao-piloto",
        "asserts_approval": False,
        "status": "no_external_act_on_file",
        "notes": "Nenhum ato externo de aprovacao foi praticado.",
    }


def _synthetic_complete_acceptance_record() -> Dict[str, Any]:
    """SYNTHETIC TEST DATA -- a fictional institution, not a real acceptance.

    Exists only so the detector's accept-half exercises the field checks
    instead of the asserts_approval early return. No real external act,
    institution or approval is described or implied by this fixture.
    """
    return {
        "institution": "INSTITUICAO-FICTICIA-DE-TESTE (dado sintetico, nao real)",
        "asserts_approval": True,
        "self_declared": False,
        "external_act_ref": "ATO-FICTICIO-0000/TESTE",
        "evidence_ref": "tests/fixtures/ficticio/ato-0000.pdf",
        "date": "2026-01-01",
        "scope": "escopo ficticio usado apenas para exercitar o detector",
        "notes": "SYNTHETIC: nenhuma instituicao real avaliou ou aprovou este produto.",
    }


# --------------------------------------------------------------------------
# Mutations. Always applied to a copy; the product source is never touched.
# --------------------------------------------------------------------------


def mutate_commercial(artifact: Any, cause: str) -> Any:
    if cause not in COMMERCIAL_DEFECTS:
        raise ValueError(cause)
    art = _deep(artifact)
    if cause == "lost_exit_code":
        art["exit_code"] = 1
    elif cause == "empty_result":
        art.setdefault("value", {})["point"] = None
        art["value"]["mean_ci80"] = None
        art["value"]["prediction_interval"] = None
        art.setdefault("sample", {})["used_row_ids"] = []
        art["sample"]["used"] = 0
        art.setdefault("model", {})["coefficients"] = {}
        art.setdefault("validation", {}).setdefault("issuance", {})["status"] = "ready_for_professional_review"
    elif cause == "method_none":
        # Shape-identical to a REAL method-none run: the effective policy under
        # the search audit reads "none", and validation.statistical carries no
        # procedure block at all (worker._map_validation only writes one when
        # result_contract.is_evaluation_requested is true).
        components = ((art.get("search") or {}).get("audit") or {}).get("cache_key_components")
        if not isinstance(components, dict):
            raise ValueError("snapshot has no search.audit.cache_key_components to mutate")
        policy = dict(components.get("evaluation_policy") or {})
        policy["method"] = EVALUATION_METHOD_NONE
        components["evaluation_policy"] = policy
        statistical = (art.get("validation") or {}).get("statistical")
        if isinstance(statistical, dict):
            statistical.pop("procedure", None)
    elif cause == "tampered_coefficient":
        coefs = dict((art.get("model") or {}).get("coefficients") or {})
        slope = next((k for k in coefs if k != "const"), None)
        if slope is None:
            raise ValueError("no slope coefficient to tamper with")
        coefs[slope] = float(coefs[slope]) * 1.15 + 1.0
        art.setdefault("model", {})["coefficients"] = coefs
    elif cause == "tampered_confidence_interval":
        value = art.setdefault("value", {})
        point = float(value["point"])
        for key in ("mean_ci80", "prediction_interval"):
            interval = value.get(key)
            if not interval:
                continue
            half = (float(interval["upper"]) - float(interval["lower"])) / 2.0
            value[key] = dict(interval, lower=point - half * 0.4, upper=point + half * 0.4)
    elif cause == "missing_attachments":
        raise ValueError("missing_attachments mutates a directory; use _mutate_bundle_dir")
    elif cause == "wrong_profile":
        art.setdefault("qualification_profile", {})["version"] = "2011.9"
        art["qualification_profile"]["checksum"] = "def456"
    elif cause == "unverified_rule_passed":
        rules, approval = art
        rules = list(rules)
        rules[1] = dict(rules[1], status="pending_manual")
        rules[2] = dict(rules[2], status="unverified")
        art = (rules, dict(approval))
    elif cause == "missing_license":
        components = list(art.get("components") or [])
        components.append({"name": "vendored-helper", "version": "0.1.0"})
        art["components"] = components
    elif cause == "nonexistent_external_acceptance":
        art.update(
            {
                "asserts_approval": True,
                "status": "aprovado",
                "self_declared": True,
                "external_act_ref": "",
                "evidence_ref": "",
                "date": "",
                "scope": "",
            }
        )
    if isinstance(art, dict):
        art.setdefault("provenance", {})["c06_mutation"] = cause
    return art


def _mutate_bundle_dir(root: Path) -> str:
    """Defect 6 -- delete a file the manifest still lists."""
    manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    victim = manifest["files"][-1]["path"]
    (root / victim).unlink()
    return victim


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


def test_defect_inventory_is_complete_and_partitioned():
    assert len(COMMERCIAL_DEFECTS) == 10
    assert set(PRODUCT_SIDE_GUARD_STATUS) == set(COMMERCIAL_DEFECTS)
    assert set(PRODUCT_SIDE_GUARD_STATUS.values()) <= set(GUARD_STATUSES)
    buckets = [defects_with_guard_status(s) for s in GUARD_STATUSES]
    assert frozenset().union(*buckets) == set(COMMERCIAL_DEFECTS)
    for i, left in enumerate(buckets):
        for right in buckets[i + 1:]:
            assert not left & right


def test_guard_status_matches_the_docstring_prose():
    """The programmatic status may not be harsher than the prose it summarises.

    Defects 7 and 8 are described as "PARTIAL guard only"; a consumer reading
    the mapping must get PARTIAL, not "no guard at all".
    """
    assert defects_with_guard_status(GUARD_SHIPPED) == {"lost_exit_code", "missing_attachments"}
    assert defects_with_guard_status(GUARD_PARTIAL) == {"wrong_profile", "unverified_rule_passed"}
    assert defects_with_guard_status(GUARD_NONE) == {
        "empty_result",
        "method_none",
        "tampered_coefficient",
        "tampered_confidence_interval",
        "missing_license",
        "nonexistent_external_acceptance",
    }
    doc = __doc__ or ""
    for heading in ("GUARD_SHIPPED --", "GUARD_PARTIAL --", "GUARD_NONE --"):
        assert heading in doc, heading
    partial_section = doc.split("GUARD_PARTIAL --")[1].split("GUARD_NONE --")[0]
    for defect in defects_with_guard_status(GUARD_PARTIAL):
        assert defect in partial_section, defect
    none_section = doc.split("GUARD_NONE --")[1]
    for defect in defects_with_guard_status(GUARD_NONE):
        assert defect in none_section, defect


# --- Defect 1: lost exit code (product-side guard: aggregate_required) -----


def test_defect01_clean_run_artifacts_are_accepted(tmp_path):
    root = _write_artifacts_dir(tmp_path / "artifacts", run_payload=_clean_run_payload())
    assert check_p04_run(root / "run.json", expected_sha=CANDIDATE_SHA) == []
    assert check_junit(root / "wide.junit.xml", min_tests=40, label="wide.junit.xml") == []
    assert check_c16(root / "c16.json", expected_sha=CANDIDATE_SHA) == []
    assert verify_artifacts(root, expected_sha=CANDIDATE_SHA, min_wide_tests=40) == []


def test_defect01_lost_exit_code_is_caught_end_to_end(tmp_path):
    """The CI job returned success; the artifact it produced records exit_code 1."""
    mutated = mutate_commercial(_clean_run_payload(), "lost_exit_code")
    root = _write_artifacts_dir(tmp_path / "artifacts", run_payload=mutated)
    problems = verify_artifacts(root, expected_sha=CANDIDATE_SHA, min_wide_tests=40)
    assert problems, "a green job over an exit_code 1 artifact must not aggregate clean"
    assert any("exit_code" in p for p in problems), problems


def test_defect01_absent_exit_code_is_not_treated_as_zero(tmp_path):
    payload = _clean_run_payload()
    payload.pop("exit_code")
    root = _write_artifacts_dir(tmp_path / "artifacts", run_payload=payload)
    problems = verify_artifacts(root, expected_sha=CANDIDATE_SHA, min_wide_tests=40)
    assert any("exit_code absent" in p for p in problems), problems


# --- Defect 2: empty result -----------------------------------------------


def test_defect02_empty_result_presented_as_finished(isolated_p04_runtime):
    bundle = _s01_snapshot()
    clean = _deep(bundle["snapshot"])
    # The shipped run is a draft; raise it to the strongest status the product
    # allows so the "accepts the clean artifact" half is not vacuous.
    clean["validation"]["issuance"]["status"] = "ready_for_professional_review"
    assert _finite(clean["value"]["point"]) and clean["sample"]["used_row_ids"]
    assert finished_valuation_problems(clean) == []
    mutated = mutate_commercial(clean, "empty_result")
    problems = finished_valuation_problems(mutated)
    assert problems, "a null point presented as a concluded valuation must be rejected"
    assert any("value.point" in p for p in problems), problems
    assert any("no rows presented as used" in p for p in problems), problems


def test_defect02_null_point_is_clean_when_not_presented_as_finished():
    unfinished = {
        "value": {"point": None},
        "sample": {"used": 0, "used_row_ids": []},
        "model": {"coefficients": {}},
        "validation": {"issuance": {"status": "draft"}},
    }
    assert finished_valuation_problems(unfinished) == []


# --- Defect 3: method none -------------------------------------------------


def test_defect03_method_none_passed_off_as_external_validation(isolated_p04_runtime):
    """Clean half is a REAL holdout run; no field is hand-authored on it.

    See the module FINDINGS: the pinned S01 spec ships method='none', so the
    clean artifact is a second shipped run with evaluation_policy.method =
    'holdout', read back on the surfaces the worker actually emits.
    """
    clean = _s01_holdout_snapshot()["snapshot"]
    policy = effective_evaluation_policy(clean)
    assert isinstance(policy, Mapping) and policy.get("method") == "holdout", policy
    procedure = clean["validation"]["statistical"]["procedure"]
    # The product normalises holdout -> 'random' (model_evaluation.py:489).
    assert procedure["method"] == "random", procedure["method"]
    # FINDING, asserted so it goes red if the product ever starts endorsing it:
    # a real external-partition run still declares itself unusable for model
    # selection, so it is not by itself evidence for an "externally validated"
    # commercial claim.
    assert procedure["usable_for_model_selection"] is False

    claim = {"id": "C06-CLAIM-VALIDATION", "claims_external_validation": True}
    assert external_validation_claim_problems(clean, claim) == []

    mutated = mutate_commercial(clean, "method_none")
    problems = external_validation_claim_problems(mutated, claim)
    assert problems, "method=none may not back an external-validation claim"
    assert any("evaluation_policy.method is 'none'" in p for p in problems), problems
    assert any("no procedure block" in p for p in problems), problems


def test_defect03_mutation_is_shape_identical_to_a_real_method_none_run(isolated_p04_runtime):
    """The mutated artifact must be indistinguishable from shipped output.

    Both evaluation surfaces of the mutation are compared against the real
    method-none snapshot the product returns for the pinned S01 spec.
    """
    real_none = _s01_snapshot()["snapshot"]
    mutated = mutate_commercial(_s01_holdout_snapshot()["snapshot"], "method_none")
    assert effective_evaluation_policy(real_none)["method"] == EVALUATION_METHOD_NONE
    assert effective_evaluation_policy(mutated)["method"] == EVALUATION_METHOD_NONE
    assert "procedure" not in real_none["validation"]["statistical"]
    assert "procedure" not in mutated["validation"]["statistical"]
    claim = {"id": "C06-CLAIM-VALIDATION", "claims_external_validation": True}
    # The real method-none run is refused on the same evidence as the mutation.
    assert external_validation_claim_problems(real_none, claim)


def test_defect03_unobservable_evaluation_policy_is_not_clean(isolated_p04_runtime):
    """A snapshot with no recorded policy must not be reported clean.

    'I cannot observe the evaluation policy' is not 'the claim checks out'.
    """
    clean = _s01_holdout_snapshot()["snapshot"]
    claim = {"id": "C06-CLAIM-VALIDATION", "claims_external_validation": True}
    stripped = _deep(clean)
    stripped["search"]["audit"].pop("cache_key_components")
    assert effective_evaluation_policy(stripped) is None
    problems = external_validation_claim_problems(stripped, claim)
    assert any("records no effective evaluation policy" in p for p in problems), problems

    nulled = _deep(clean)
    nulled["search"]["audit"]["cache_key_components"]["evaluation_policy"] = None
    problems = external_validation_claim_problems(nulled, claim)
    assert any("records no effective evaluation policy" in p for p in problems), problems

    scrambled = _deep(clean)
    scrambled["search"]["audit"]["cache_key_components"]["evaluation_policy"] = "holdout"
    problems = external_validation_claim_problems(scrambled, claim)
    assert any("not a mapping" in p for p in problems), problems


def test_defect03_usable_for_model_selection_without_a_method_is_rejected(isolated_p04_runtime):
    """The third arm: a procedure that claims usability with no method at all."""
    art = _deep(_s01_holdout_snapshot()["snapshot"])
    art["validation"]["statistical"]["procedure"] = {
        "method": "none",
        "usable_for_model_selection": True,
    }
    claim = {"id": "C06-CLAIM-VALIDATION", "claims_external_validation": True}
    problems = external_validation_claim_problems(art, claim)
    assert any("procedure.method is 'none'" in p for p in problems), problems
    assert any("usable_for_model_selection with no evaluation method" in p for p in problems), problems


def test_defect03_method_none_is_clean_when_nothing_is_claimed(isolated_p04_runtime):
    mutated = mutate_commercial(_s01_holdout_snapshot()["snapshot"], "method_none")
    assert external_validation_claim_problems(mutated, {"id": "x", "claims_external_validation": False}) == []


# --- Defect 4: tampered coefficient ---------------------------------------


def test_defect04_tampered_coefficient_breaks_the_model_identity(isolated_p04_runtime):
    bundle = _s01_snapshot()
    clean, subject = bundle["snapshot"], bundle["subject"]
    assert point_follows_from_model_problems(clean, subject) == []
    mutated = mutate_commercial(clean, "tampered_coefficient")
    problems = point_follows_from_model_problems(mutated, subject)
    assert problems, "a coefficient altered after the fit must not reproduce the reported point"
    assert any("does not follow from the frozen coefficients" in p for p in problems), problems


def test_defect04_tampered_coefficient_keeps_every_field_well_formed(isolated_p04_runtime):
    """The mutation is invisible to shape checks: that is why it needs a detector."""
    bundle = _s01_snapshot()
    mutated = mutate_commercial(bundle["snapshot"], "tampered_coefficient")
    assert _finite(mutated["value"]["point"])
    assert set(mutated["model"]["coefficients"]) == set(bundle["snapshot"]["model"]["coefficients"])
    assert all(_finite(v) for v in mutated["model"]["coefficients"].values())


def test_defect04_non_identity_y_transformation_is_not_verified(isolated_p04_runtime):
    """The 'I cannot check this' arm must not report clean.

    TEST-AUTHORED VARIANT, not shipped output: model.y_transformation is set
    to 'ln' on a copy of the real S01 snapshot. The property under test
    belongs to the DETECTOR ("cannot verify" is not "clean"), so the variant
    is the right artifact for it.

    FINDING -- I could not obtain a non-identity winner from the shipped
    HTTP/worker path in two probes: corpus S01 with search_policy
    .y_transformations = ['ln'], and a log-linear synthetic sample with the
    same override, both ended in HTTP 409 no_admissible_winner (discard
    reasons observed via a direct search_models call: original_scale_error
    _unavailable and peer_fit_not_fitted). That direct call did NOT carry the
    worker-injected target-transform peers, so the cause is not isolated and
    this is NOT a claim that the product cannot emit a non-identity winner.
    """
    bundle = _s01_snapshot()
    real, subject = bundle["snapshot"], bundle["subject"]
    assert real["model"]["y_transformation"] == "identity"
    assert point_follows_from_model_problems(real, subject) == []

    variant = _deep(real)
    variant["model"]["y_transformation"] = "ln"
    problems = point_follows_from_model_problems(variant, subject)
    assert problems, "a point the detector cannot re-derive must not be reported clean"
    assert any("was not verified against the frozen model" in p for p in problems), problems
    assert any("'ln'" in p for p in problems), problems


def test_defect04_missing_coefficients_are_not_verified(isolated_p04_runtime):
    """The other unverifiable arm: no coefficient mapping to re-derive from."""
    variant = _deep(_s01_snapshot()["snapshot"])
    variant["model"]["coefficients"] = {}
    problems = point_follows_from_model_problems(variant, _s01_snapshot()["subject"])
    assert any("no coefficient mapping" in p for p in problems), problems


# --- Defect 5: tampered confidence interval -------------------------------


def test_defect05_narrowed_interval_with_untouched_point(isolated_p04_runtime):
    bundle = _s01_snapshot()
    clean, reference = bundle["snapshot"], bundle["reference"]
    assert interval_matches_reference_problems(clean, reference) == []
    mutated = mutate_commercial(clean, "tampered_confidence_interval")
    assert mutated["value"]["point"] == clean["value"]["point"]
    problems = interval_matches_reference_problems(mutated, reference)
    assert problems, "narrowed bounds must not pass while the point is unchanged"
    assert any("point unchanged" in p for p in problems), problems
    # BOTH arms of the detector are computed, so both must be asserted.
    assert any("mean_ci80" in p for p in problems), problems
    assert any("prediction_interval" in p for p in problems), problems
    for key in ("mean_ci80", "prediction_interval"):
        for bound in ("lower", "upper"):
            assert any(f"{key}.{bound}" in p for p in problems), (key, bound, problems)


def test_defect05_an_absent_interval_is_not_clean(isolated_p04_runtime):
    """Shipping no interval at all must be a problem, not a silent pass.

    Closes the hole the `continue` used to leave: both a null interval and a
    deleted key were previously reported clean.
    """
    bundle = _s01_snapshot()
    clean, reference = bundle["snapshot"], bundle["reference"]
    assert interval_matches_reference_problems(clean, reference) == []

    nulled = _deep(clean)
    nulled["value"]["mean_ci80"] = None
    nulled["value"]["prediction_interval"] = None
    problems = interval_matches_reference_problems(nulled, reference)
    assert problems, "an artifact reporting no interval must not be reported clean"
    for key in ("mean_ci80", "prediction_interval"):
        assert any(f"value.{key} is None" in p for p in problems), (key, problems)

    deleted = _deep(clean)
    deleted["value"].pop("mean_ci80")
    deleted["value"].pop("prediction_interval")
    problems = interval_matches_reference_problems(deleted, reference)
    assert problems, "an artifact with no interval key must not be reported clean"
    for key in ("mean_ci80", "prediction_interval"):
        assert any(f"value.{key} is absent" in p for p in problems), (key, problems)


def test_defect05_a_missing_oracle_is_reported_as_unverified(isolated_p04_runtime):
    """No independent re-derivation available is NOT VERIFIED, not clean."""
    bundle = _s01_snapshot()
    clean = bundle["snapshot"]
    blind = dict(bundle["reference"])
    blind["mean_ci"] = None
    blind.pop("prediction_interval")
    problems = interval_matches_reference_problems(clean, blind)
    for key in ("mean_ci80", "prediction_interval"):
        assert any(key in p and "NOT verified" in p for p in problems), (key, problems)


def test_defect05_a_non_mapping_interval_is_reported_not_raised(isolated_p04_runtime):
    """A scalar where an interval belongs must be reported, not crash."""
    bundle = _s01_snapshot()
    broken = _deep(bundle["snapshot"])
    broken["value"]["mean_ci80"] = 601436.97
    problems = interval_matches_reference_problems(broken, bundle["reference"])
    assert any("not an interval mapping" in p for p in problems), problems


# --- Defect 6: missing attachments (product-side guard: verify_bundle) ----


def test_defect06_clean_bundle_verifies(tmp_path):
    root = tmp_path / "bundle"
    _write_bundle(root)
    report = verify_bundle(root)
    assert report["ok"], report["errors"]


def test_defect06_manifest_listing_an_absent_file_is_caught(tmp_path):
    root = tmp_path / "bundle"
    _write_bundle(root)
    victim = _mutate_bundle_dir(root)
    report = verify_bundle(root)
    assert not report["ok"]
    assert any(f"missing listed file: {victim}" == err for err in report["errors"]), report["errors"]


# --- Defect 7: wrong profile ----------------------------------------------


def test_defect07_document_profile_must_match_the_calculation():
    document, calculation = _clean_profile_document(), _clean_profile_calculation()
    assert profile_binding_problems(document, calculation) == []
    mutated_doc = mutate_commercial(document, "wrong_profile")
    problems = profile_binding_problems(mutated_doc, calculation)
    assert problems, "a profile version printed but not used must be rejected"
    assert any("qualification_profile.version" in p for p in problems), problems
    assert any("checksum" in p for p in problems), problems


# --- Defect 8: unverified rule counted as passed --------------------------


def test_defect08_unverified_and_pending_manual_never_count_as_passed():
    clean = (_clean_rule_results(), _clean_approval())
    assert rule_approval_problems(*clean) == []
    rules, approval = mutate_commercial(clean, "unverified_rule_passed")
    problems = rule_approval_problems(rules, approval)
    assert problems, "unverified/pending_manual rules must not be counted toward approval"
    assert any("'pending_manual'" in p for p in problems), problems
    assert any("'unverified'" in p for p in problems), problems


def test_defect08_count_mismatch_is_also_caught():
    rules = _clean_rule_results()
    approval = dict(_clean_approval(), passed_count=4)
    problems = rule_approval_problems(rules, approval)
    assert any("passed_count" in p for p in problems), problems


# --- Defect 9: missing licence --------------------------------------------


def test_defect09_component_without_spdx_is_rejected():
    clean = _clean_reuse_manifest()
    assert reuse_manifest_problems(clean) == []
    mutated = mutate_commercial(clean, "missing_license")
    problems = reuse_manifest_problems(mutated)
    assert problems, "a reused component with no SPDX licence must be rejected"
    assert any("vendored-helper" in p and "SPDX" in p for p in problems), problems


def test_defect09_placeholder_licence_is_not_a_licence():
    manifest = _clean_reuse_manifest()
    manifest["components"][0] = dict(manifest["components"][0], license_spdx="NOASSERTION")
    problems = reuse_manifest_problems(manifest)
    assert any("placeholder licence" in p for p in problems), problems


# --- Defect 10: nonexistent external acceptance ---------------------------


def test_defect10_complete_synthetic_record_is_accepted():
    """Accept-half over the field checks, not over the asserts_approval shortcut."""
    clean = _synthetic_complete_acceptance_record()
    assert clean["asserts_approval"] is True
    assert institution_acceptance_problems(clean) == []
    for field in ("external_act_ref", "evidence_ref", "date", "scope"):
        stripped = dict(clean, **{field: ""})
        problems = institution_acceptance_problems(stripped)
        assert any(field in p for p in problems), (field, problems)


def test_defect10_approval_without_a_real_external_act_is_rejected():
    clean = _synthetic_complete_acceptance_record()
    assert institution_acceptance_problems(clean) == []
    mutated = mutate_commercial(clean, "nonexistent_external_acceptance")
    problems = institution_acceptance_problems(mutated)
    assert problems, "an approval with no external act, evidence, date or scope must be rejected"
    for field in ("external_act_ref", "evidence_ref", "date", "scope"):
        assert any(field in p for p in problems), (field, problems)
    assert any("self-declared" in p for p in problems), problems


def test_defect10_detector_does_not_invent_an_approval():
    """A record that asserts nothing is clean; the detector never upgrades it."""
    record = _clean_acceptance_record()
    assert record["asserts_approval"] is False
    assert institution_acceptance_problems(record) == []
