"""C06: one verified arbitration policy across worker, batch and reproduction."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.worker import CompositionError, compose_valuation_job, resolve_peers
from modules.evidence_bundle import reproduce_from_bundle
from modules.job_store import JobStore
from modules.qualification_profile import resolve_arbitration_policy, resolve_profile
from modules import normative_rules
from modules.valuation_batch import builtin_evaluate_fitted, evaluate_batch
from modules.valuation_policy.intervals import compose_value_intervals
from tests.comercial.test_c06_document_flow import _professional_spec
from tests.comercial.test_c06_numeric_disclosure import _noisy_linear_csv


def _bb_profile() -> dict:
    resolved = resolve_profile({"id": "bb-meci-avaliacao-imovel-pf", "version": "0.3.0"})
    return {
        key: resolved[key]
        for key in (
            "id", "version", "source_set_sha256", "purpose", "value_basis",
            "method", "asset_scope", "recipient_id",
        )
    }


def _bb_spec() -> dict:
    spec = _professional_spec()
    spec["qualification_profile"] = _bb_profile()
    return spec


def _assert_band(value: dict) -> None:
    point = value["point"]
    assert point is not None
    assert value["arbitration_interval"]["lower"] == pytest.approx(point * 0.85)
    assert value["arbitration_interval"]["upper"] == pytest.approx(point * 1.15)
    assert value["arbitration_interval"]["not_statistical"] is True


def _simple_fit_and_design() -> tuple[dict, dict]:
    return (
        {
            "coefficients": {"const": 100.0, "area": 10.0},
            "candidate_spec": {"y_transformation": {"name": "identity"}},
            "model_state": {"feature_order": ["const", "area"], "n": 20, "k": 1},
            "used_row_ids": ["R000000"],
        },
        {
            "supported": True,
            "raw_values": {"area": 2.0},
            "issues": [],
            "X": {"const": 1.0, "area": 2.0},
        },
    )


@pytest.fixture(scope="module")
def real_bb_case(tmp_path_factory):
    root = tmp_path_factory.mktemp("c06-arbitration")
    store = JobStore(root / "store", recover_abandoned=False)
    spec = _bb_spec()
    created = store.create(request_spec=spec, payload={"filename": "SINTETICO.csv"})
    composed = compose_valuation_job(
        job_id=created["job_id"],
        file_bytes=_noisy_linear_csv()[0],
        filename="SINTETICO.csv",
        request_spec=spec,
        subject_raw={"area": 73.5, "bairro": "Centro"},
        project_id="p-arbitration",
        peers=resolve_peers(),
        job_store=store,
        output_dir=str(root / "bundle"),
    )
    return {"root": root, "store": store, "spec": spec, "composed": composed}


def test_real_bb_worker_matches_normative_interval_and_persists_used_rule(real_bb_case):
    composed = real_bb_case["composed"]
    snapshot = composed["snapshot"]
    value = snapshot["value"]
    normative = snapshot["provenance"]["normative_assessment"]["intervals"][
        "arbitration_interval"
    ]

    _assert_band(value)
    assert value["arbitration_interval"]["lower"] == pytest.approx(normative["lower"])
    assert value["arbitration_interval"]["upper"] == pytest.approx(normative["upper"])
    policy = composed["frozen_project"]["value_policy"]
    assert policy["arbitration"] == {
        "method": "percent_around_point",
        "percent": 15.0,
        "source": policy["arbitration_source"],
    }
    assert policy["arbitration_source"]["verification_status"] == "verified"
    assert policy["adopted"] == {"method": "point"}
    assert policy["source"] == "TESTE: política sintética explicitamente declarada"
    assert "arbitration" not in composed["frozen_project"]["request_spec"]["value_policy"]


def test_real_batch_uses_each_subject_point_for_its_own_endpoints(real_bb_case):
    composed = real_bb_case["composed"]
    batch = evaluate_batch(
        composed["frozen_project"],
        [
            {"subject_id": "s-1", "raw": {"area": 70.0, "bairro": "Centro"}},
            {"subject_id": "s-2", "raw": {"area": 90.0, "bairro": "Centro"}},
        ],
        real_bb_case["spec"],
    )

    assert [item["status"] for item in batch["items"]] == ["succeeded", "succeeded"]
    assert batch["items"][0]["value"]["point"] != batch["items"][1]["value"]["point"]
    for item in batch["items"]:
        _assert_band(item["value"])


def test_real_batch_marks_verified_profile_conflict_failed(real_bb_case):
    spec = _bb_spec()
    spec["value_policy"]["arbitration"] = {
        "method": "percent_around_point",
        "percent": 10.0,
    }
    batch = evaluate_batch(
        real_bb_case["composed"]["frozen_project"],
        [{"subject_id": "s-conflict", "raw": {"area": 70.0, "bairro": "Centro"}}],
        spec,
    )

    item = batch["items"][0]
    assert item["status"] == "failed"
    assert item["value"]["point"] is None
    conflict = next(
        issue for issue in item["pendencias"]
        if issue["code"] == "arbitration_policy_conflict"
    )
    assert conflict["severity"] == "error"


def test_restored_fit_subprocess_uses_same_verified_policy(real_bb_case):
    root = real_bb_case["root"]
    frozen_path = root / "frozen-subprocess.json"
    output_path = root / "subprocess-output.json"
    frozen_path.write_text(
        json.dumps(real_bb_case["composed"]["frozen_project"]), encoding="utf-8"
    )
    script = """
import json, sys
from modules.preprocessing import transform_subject
from modules.valuation_batch import builtin_evaluate_fitted, restore_candidate_fit
with open(sys.argv[1], encoding='utf-8') as fh:
    frozen = json.load(fh)
fit = restore_candidate_fit(frozen)
design = transform_subject(
    {'area': 80.0, 'bairro': 'Centro'}, frozen['feature_schema'], frozen['encoder_state']
)
result = builtin_evaluate_fitted(fit, design, frozen['request_spec'])
with open(sys.argv[2], 'w', encoding='utf-8') as fh:
    json.dump(result['value'], fh)
"""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "-c", script, str(frozen_path), str(output_path)],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    _assert_band(json.loads(output_path.read_text(encoding="utf-8")))


def test_bundle_reproducer_uses_persisted_value_policy(real_bb_case):
    bundle = real_bb_case["root"] / "bundle"
    policy = json.loads((bundle / "policies" / "value_policy.json").read_text())
    frozen_policy = real_bb_case["composed"]["frozen_project"]["value_policy"]
    assert policy == frozen_policy

    reproduced = reproduce_from_bundle(bundle)
    assert reproduced["ok"] is True
    assert reproduced["point"] is not None
    expected = real_bb_case["composed"]["snapshot"]["value"]["arbitration_interval"]
    assert reproduced["arbitration_interval"]["lower"] == pytest.approx(expected["lower"])
    assert reproduced["arbitration_interval"]["upper"] == pytest.approx(expected["upper"])


@pytest.mark.parametrize(
    "profile",
    [
        None,
        {"id": "perfil-desconhecido", "version": "1"},
        {"id": "bb-meci-avaliacao-imovel-pf", "version": "0.3.0"},
        {"id": "bb-meci-avaliacao-imovel-pf", "version": "0.0.0"},
        {"id": "abnt-14653-2-custo-reedicao", "version": "0.2.0"},
        {
            "id": "bb-meci-avaliacao-imovel-pf",
            "version": "0.3.0",
            "source_set_sha256": "0" * 64,
        },
    ],
    ids=[
        "no-profile", "unknown", "missing-source-set", "version-mismatch", "cost",
        "unknown-source-set",
    ],
)
def test_inapplicable_or_unverified_profile_keeps_arbitration_null(profile):
    policy = resolve_arbitration_policy(profile)
    fit, design = _simple_fit_and_design()
    spec = {"qualification_profile": profile} if profile is not None else {}
    value = builtin_evaluate_fitted(fit, design, spec)["value"]
    assert policy is None
    assert value["arbitration_interval"] is None


@pytest.mark.parametrize("point", [math.inf, -100.0, 0.0])
def test_nonfinite_or_nonpositive_point_never_gets_arbitration_band(point):
    policy = resolve_arbitration_policy(_bb_profile())
    value, notes = compose_value_intervals(point=point, c05_interval_rule=policy)
    if math.isfinite(point):
        assert value["point"] == point
    else:
        assert value["point"] is None
    assert value["arbitration_interval"] is None
    if math.isfinite(point):
        assert "arbitration_point_non_positive" in notes

    normative = normative_rules.interval_roles(central_estimate=point)
    assert normative["arbitration_interval"] is None
    if math.isfinite(point):
        assert any("central_estimate_non_positive" in item for item in normative["reasons"])


def test_explicit_conflict_fails_closed_and_preserves_human_adopted_policy():
    spec = _bb_spec()
    spec["value_policy"] = {
        "adopted": {"method": "explicit", "value": 123.0},
        "source": "decisão profissional",
        "arbitration": {"method": "percent_around_point", "percent": 10},
    }
    fit, design = _simple_fit_and_design()

    assessment = builtin_evaluate_fitted(fit, design, spec)

    assert assessment["value"]["point"] == 120.0
    assert assessment["value"]["arbitration_interval"] is None
    assert assessment["value_policy"]["adopted"] == {
        "method": "explicit", "value": 123.0,
    }
    assert assessment["value_policy"]["source"] == "decisão profissional"
    assert assessment["value_policy"]["arbitration_resolution"]["status"] == "conflict_fail_closed"
    conflict = next(
        issue for issue in assessment["issues"]
        if issue["code"] == "arbitration_policy_conflict"
    )
    assert conflict["severity"] == "error"


def test_real_worker_conflict_fails_before_snapshot_frozen_and_manifest(tmp_path):
    spec = _bb_spec()
    spec["value_policy"]["arbitration"] = {
        "method": "percent_around_point",
        "percent": 10.0,
    }
    store = JobStore(tmp_path / "store", recover_abandoned=False)
    created = store.create(request_spec=spec, payload={"filename": "SINTETICO.csv"})
    bundle = tmp_path / "bundle"

    with pytest.raises(CompositionError, match="evaluate_fitted failed") as raised:
        compose_valuation_job(
            job_id=created["job_id"],
            file_bytes=_noisy_linear_csv()[0],
            filename="SINTETICO.csv",
            request_spec=spec,
            subject_raw={"area": 73.5, "bairro": "Centro"},
            project_id="p-arbitration-conflict",
            peers=resolve_peers(),
            job_store=store,
            output_dir=str(bundle),
        )

    conflict = next(
        issue for issue in raised.value.issues
        if issue["code"] == "arbitration_policy_conflict"
    )
    assert conflict["severity"] == "error"
    assert conflict["evidence"]["status"] == "conflict_fail_closed"
    assert store.get_snapshot(created["job_id"]) is None
    for artifact in (
        "frozen_project.json",
        "evidence_manifest.json",
        "evidence_bundle.zip",
        "output_manifest.json",
    ):
        assert store.get_artifact(created["job_id"], artifact) is None
    assert not bundle.exists()


def test_unknown_profile_cannot_promote_declared_verified_endpoints():
    fit, design = _simple_fit_and_design()
    assessment = builtin_evaluate_fitted(
        fit,
        design,
        {
            "qualification_profile": {"id": "unknown", "version": "1"},
            "c05_interval_rule": {
                "arbitration_interval": {
                    "lower": 102.0,
                    "upper": 138.0,
                    "verification_status": "verified",
                }
            },
        },
    )

    assert assessment["value"]["point"] == 120.0
    assert assessment["value"]["arbitration_interval"] is None
    resolution = assessment["value_policy"]["arbitration_resolution"]
    assert resolution["status"] == "rejected_unverified_or_inapplicable_profile"
    assert resolution["declarations"] == ["request_spec.c05_interval_rule"]
