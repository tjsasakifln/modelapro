"""C06 regressions for the real C01 -> C05 qualification contract.

All people, evidence and documents below are synthetic test fixtures. They are
not professional review, market evidence or an institutional act.
"""

from __future__ import annotations

import copy

import pytest

from modules.nbr14653_validation import assess_normative
from modules.qualification_profile import resolve_profile
from modules.valuation_policy.qualification import (
    QualificationProfileError,
    compose_qualification_context,
    reassess_qualification_context,
    validate_qualification_profile,
)


PROFILE_FIELDS = (
    "id",
    "version",
    "source_set_sha256",
    "purpose",
    "value_basis",
    "method",
    "asset_scope",
)


def _profile_ref():
    resolved = resolve_profile(
        {"id": "abnt-14653-2-regressao-mercado", "version": "1.0.0"}
    )
    return {field: resolved[field] for field in PROFILE_FIELDS}


def _normative_assessment(**overrides):
    finding = {
        "satisfied": True,
        "justification": "TESTE: exame profissional sintético registrado",
    }
    context = {
        "n": 36,
        "k": 1,
        "intercept": True,
        "axes": [
            {
                "name": "area",
                "kind": "quantitative",
                "avaliando_value": 100.0,
                "sample_min": 50.0,
                "sample_max": 180.0,
                "unit": "m2",
            }
        ],
        "subject_raw": {"area": 100.0},
        "predict_original": lambda _raw: 500000.0,
        "pvalues": {"area": 0.01},
        "f_pvalue": 0.001,
        "amplitude_pct": 20.0,
        "grau_item1": 1,
        "item1_provenance": {"ref": "TESTE::vistoria"},
        "grau_item3": 1,
        "item3_provenance": {"ref": "TESTE::amostra"},
        "central_estimate": 500000.0,
        "mean_ci80": {"lower": 475000.0, "upper": 525000.0},
        "prediction_interval": {"lower": 430000.0, "upper": 570000.0},
        "estimand": "valor_de_mercado",
        "category_counts": {},
        "diagnostics": {
            "anexoA.2.c.homocedasticidade": {"p_value": 0.5, "alpha": 0.1},
            "anexoA.2.d.normalidade": {"p_value": 0.5, "alpha": 0.1},
            "anexoA.2.e.autocorrelacao": {
                "p_value": 0.5,
                "alpha": 0.1,
                "ordering_declared": True,
            },
        },
        "professional_findings": {
            rule_id: finding
            for rule_id in (
                "anexoA.2.f.variaveis_relevantes",
                "anexoA.2.g.multicolinearidade",
                "anexoA.2.h.residuos_vs_independentes",
                "anexoA.2.i.pontos_influenciantes",
                "anexoA.8.agrupamentos",
            )
        },
    }
    context.update(overrides)
    return assess_normative(context)


def _spec(**overrides):
    spec = {
        "qualification_profile": _profile_ref(),
        "search_policy": {"minimum_fundamentacao_grade": 1, "objective": "aic"},
        "evaluation_policy": {"method": "none"},
        "units": {"area": "m2", "preco": "BRL"},
        "target_unit": "BRL",
        "reference_date": "2026-09-01",
        "inspection_date": "2026-08-31",
        "profile_evidence": {
            "parte1.6.3.vistoria": "TESTE::vistoria",
            "8.2.1.5.2.campo_suficiente": "TESTE::campo",
            "10.1.laudo_completo": "TESTE::laudo",
        },
    }
    spec.update(overrides)
    return spec


def _draft():
    return {
        "schema_version": "MP/1",
        "job_id": "job-sintetico-c06",
        "input_sha256": "1" * 64,
        "code_sha": "c06-test",
        "reference_date": "2026-09-01",
        "target": {"column": "preco", "unit": "BRL", "estimand": "valor_de_mercado"},
        "value": {
            "point": 500000.0,
            "mean_ci80": {"lower": 475000.0, "upper": 525000.0},
            "prediction_interval": {"lower": 430000.0, "upper": 570000.0},
            "arbitration_interval": None,
            "admissible_interval": None,
        },
        "sample": {
            "used": 36,
            "used_row_ids": [f"TESTE-{index:02d}" for index in range(36)],
            "observed_target": 36,
        },
        "model": {
            "candidate_id": "candidate-test",
            "coefficients": {"const": 100000.0, "area": 4000.0},
            "formula": "preco = 100000 + 4000*area",
        },
        "issues": [],
        "validation": {"statistical": {"limitations": []}},
        "provenance": {"calculation_version": "C06/TEST"},
    }


def _compose(spec=None, draft=None, normative=None):
    return compose_qualification_context(
        request_spec=spec or _spec(),
        snapshot_draft=draft or _draft(),
        winner={"status": "fitted"},
        search_audit={"coverage": {"enumeration": "exhaustive"}},
        normative_assessment=normative or _normative_assessment(),
    )


def test_real_c05_decision_is_preserved_across_two_pass_review():
    first = _compose()
    assert first["calculation_status"] == "ok"
    assert first["grade_requirement_status"] == "met"
    assert first["case_release_status"] == "review_required"
    assert first["release_blockers"] == []

    fingerprint = first["result_fingerprint"]
    review = {
        "professional_id": "TESTE-CREA-000",
        "motive": "TESTE: revisão técnica sintética",
        "version": "C06/TEST",
        "fingerprint": fingerprint,
    }
    second = _compose(_spec(review_events=[review]))

    assert second["result_fingerprint"] == fingerprint
    assert second["case_release_status"] == "ready_for_professional_signoff"
    assert second["release_blockers"] == []


def test_valid_flag_cannot_launder_review_and_stale_history_is_preserved():
    first = _compose()
    incomplete = {"valid": True, "fingerprint": first["result_fingerprint"]}
    changed = _draft()
    changed["model"]["coefficients"]["area"] = 4001.0

    current = _compose(_spec(review_events=[incomplete]), changed)
    assert current["case_release_status"] == "review_required"

    stale_event = {
        "professional_id": "TESTE-CREA-000",
        "motive": "TESTE: revisão anterior",
        "version": "C06/TEST",
        "fingerprint": first["result_fingerprint"],
        "valid": True,
    }
    stale = _compose(_spec(review_events=[stale_event]), changed)
    assert stale["result_fingerprint"] != first["result_fingerprint"]
    assert stale["stale_review_events"] == [stale_event]
    assert "review_invalidated_by_material_change" in {
        blocker["code"] for blocker in stale["release_blockers"]
    }


def test_review_cannot_override_a_failed_decisive_normative_rule():
    failed_assessment = _normative_assessment(f_pvalue=0.2)
    first = _compose(normative=failed_assessment)
    review = {
        "professional_id": "TESTE-CREA-000",
        "motive": "TESTE: revisão não substitui regra reprovada",
        "version": "C06/TEST",
        "fingerprint": first["result_fingerprint"],
    }

    reviewed = _compose(_spec(review_events=[review]), normative=failed_assessment)

    assert reviewed["case_release_status"] == "analysis_only"
    assert any(
        rule["rule_id"] == "tabela1.item6" and rule["status"] == "failed"
        for rule in reviewed["rule_results"]
    )
    assert "decisive_rule_not_satisfied" in {
        blocker["code"] for blocker in reviewed["release_blockers"]
    }


def test_missing_profile_document_stays_pending_after_review():
    spec = _spec()
    del spec["profile_evidence"]["parte1.6.3.vistoria"]
    first = _compose(spec)
    review = {
        "professional_id": "TESTE-CREA-000",
        "motive": "TESTE: revisão sem documento obrigatório",
        "version": "C06/TEST",
        "fingerprint": first["result_fingerprint"],
    }

    reviewed = _compose({**spec, "review_events": [review]})

    assert reviewed["case_release_status"] != "ready_for_professional_signoff"
    assert "parte1.6.3.vistoria" in reviewed["pending_manual_rules"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", "0.0.0"),
        ("source_set_sha256", "0" * 64),
        ("purpose", "finalidade-inventada"),
        ("value_basis", "base-inventada"),
        ("method", "metodo-inventado"),
        ("asset_scope", "bem-inventado"),
    ],
)
def test_profile_version_hash_and_semantics_must_match_catalog(field, value):
    profile = _profile_ref()
    profile[field] = value
    with pytest.raises(QualificationProfileError) as exc:
        validate_qualification_profile(profile)
    assert any(
        issue["code"].startswith("QUALIFICATION_PROFILE")
        for issue in exc.value.issues
    )


def test_result_report_and_signed_byte_fingerprints_have_distinct_roles():
    report_fingerprint = "a" * 64
    first = _compose(_spec(report_content_fingerprint=report_fingerprint))
    result_fingerprint = first["result_fingerprint"]
    review = {
        "professional_id": "TESTE-CREA-000",
        "motive": "TESTE: revisão técnica sintética",
        "version": "C06/TEST",
        "fingerprint": result_fingerprint,
    }
    signature = {
        "integrity_verified": True,
        "result_fingerprint": result_fingerprint,
        "report_content_fingerprint": report_fingerprint,
        "unsigned_pdf_sha256": "b" * 64,
        "signed_pdf_sha256": "c" * 64,
    }
    signed = _compose(
        _spec(
            review_events=[review],
            report_content_fingerprint=report_fingerprint,
            signature=signature,
        )
    )
    assert signed["case_release_status"] == "signed_integrity_verified"
    assert signed["result_fingerprint"] == result_fingerprint
    assert signed["report_content_fingerprint"] == report_fingerprint
    assert signed["signed_bytes_sha256"] == "c" * 64

    changed_report = _compose(
        _spec(
            review_events=[review],
            report_content_fingerprint="d" * 64,
            signature=signature,
        )
    )
    assert changed_report["result_fingerprint"] == result_fingerprint
    assert changed_report["case_release_status"] == "review_required"
    assert "signature_stale" in {
        blocker["code"] for blocker in changed_report["release_blockers"]
    }


def test_document_route_can_reassess_without_recalculating_the_normative_grade():
    spec = _spec()
    snapshot = _draft()
    normative = _normative_assessment()
    first = _compose(spec, snapshot)
    snapshot["provenance"]["qualification_context"] = first
    snapshot["provenance"]["normative_assessment"] = normative
    snapshot["search"] = {"audit": {"coverage": {"enumeration": "exhaustive"}}}

    manifest = {"TESTE::laudo": {"artifact": "report.pdf", "present": True}}
    document_pass = reassess_qualification_context(
        snapshot=snapshot,
        request_spec=spec,
        output_manifest=manifest,
        report_content_fingerprint="a" * 64,
    )
    assert document_pass["achieved_fundamentacao_grade"] == first["achieved_fundamentacao_grade"]
    assert document_pass["result_fingerprint"] != first["result_fingerprint"]

    review = {
        "professional_id": "TESTE-CREA-000",
        "motive": "TESTE: revisão após composição documental",
        "version": "C06/TEST",
        "fingerprint": document_pass["result_fingerprint"],
    }
    reviewed = reassess_qualification_context(
        snapshot=snapshot,
        request_spec=spec,
        output_manifest=manifest,
        report_content_fingerprint="a" * 64,
        review_events=[review],
    )
    assert reviewed["result_fingerprint"] == document_pass["result_fingerprint"]
    assert reviewed["case_release_status"] == "ready_for_professional_signoff"


@pytest.mark.parametrize("mutation", ["value", "sample", "coefficient", "unit", "date"])
def test_material_calculation_changes_invalidate_result_decisions(mutation):
    baseline = _compose()["result_fingerprint"]
    draft = copy.deepcopy(_draft())
    spec = _spec()
    if mutation == "value":
        draft["value"]["point"] += 1
    elif mutation == "sample":
        draft["sample"]["used_row_ids"][-1] = "TESTE-OUTRA-LINHA"
    elif mutation == "coefficient":
        draft["model"]["coefficients"]["area"] += 1
    elif mutation == "unit":
        spec["units"] = {"area": "cm2", "preco": "BRL"}
    else:
        spec["reference_date"] = "2026-09-02"

    assert _compose(spec, draft)["result_fingerprint"] != baseline
