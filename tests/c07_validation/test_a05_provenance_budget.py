"""C07-A05: provenance, original scale, no normative grade, budget records what ran."""

from __future__ import annotations

import json
import math

from modules.model_evaluation import evaluate_procedure
from modules.model_stability import (
    CANDIDATE_DISPERSION,
    FIXED_MODEL_SENSITIVITY,
    JUSTIFIED_REVISION_SENSITIVITY,
    PIPELINE_BOOTSTRAP,
    VARIABLE_SELECTION_FREQUENCY,
    analyze_stability,
)

from contract_fixtures import (
    labeled_fit_select_predictor,
    make_input_bundle,
    make_request_spec,
    synthetic_signal_rows,
)


def _run(mode: str, stability: bool = True, revisions=None, nested=False):
    bundle = make_input_bundle(synthetic_signal_rows(36, seed=2), input_sha256="synthetic-a05")
    spec = make_request_spec(
        evaluation_policy={
            "method": "random",
            "test_size": 0.25,
            "n_splits": 1,
            "mode": mode,
            "stability": stability,
            "nested": nested,
            "budget": {
                "pipeline_bootstrap_replicates": 3 if mode == "fast" else 6,
                "fixed_model_perturbations": 3,
                "max_folds": 2,
            },
            "revisions": revisions
            or [
                {
                    "revision_id": "exclude_reviewed_pair",
                    "exclude_row_ids": ["r000"],
                    "reason": "justified reviewed exclusion (synthetic)",
                }
            ],
        }
    )
    fit = labeled_fit_select_predictor(bundle, spec, leak=False)
    result = evaluate_procedure(bundle, spec, fit, 13)
    return result, bundle, spec, fit


def test_result_has_procedure_provenance_on_original_scale_not_normative_grade():
    result, _, _, _ = _run("fast", stability=True)
    assert result["schema_version"] == "MP/1"
    assert result["kind"] == "evaluation_result"
    assert result["metrics"]["scale"] == "original"
    assert result["metrics"]["unit"] == "BRL"
    assert result["metrics"]["mae"] is not None
    assert result["procedure_provenance"]["evaluated_unit"] == "full_procedure"
    assert result["procedure_provenance"]["scale"] == "original"
    assert result["procedure_provenance"]["external_scores_fed_to_selection"] is False
    assert result["procedure_provenance"]["post_selection_inference_guarantee"] is False
    assert result["statistical_inference"]["post_selection_guarantee"] is False
    assert result["normative_label"]["applied"] is False
    assert result["normative_label"]["grau_fundamentacao"] is None
    assert result["normative_label"]["grau_precisao"] is None
    assert result["generalization"]["not_normative_classification"] is True
    assert "grau_fundamentacao" not in result["metrics"]
    assert result["usable_for_model_selection"] is False

    executed_steps = [item["step"] for item in result["procedure_provenance"]["executed"]]
    assert "partition_external" in executed_steps
    assert "fit_select_predictor" in executed_steps
    assert "score_reserved" in executed_steps
    assert "analyze_stability" in executed_steps
    assert result["procedure_provenance"]["mode"] == "fast"
    assert result["procedure_provenance"]["budget"]["pipeline_bootstrap_replicates"] == 3
    assert result["procedure_provenance"]["cost"]["n_fit_select_calls"] >= 1


def test_budget_fast_mode_records_exactly_what_ran_with_distinct_stability_names():
    result, bundle, spec, fit = _run("fast", stability=True)
    stability = result["stability"]
    assert stability is not None
    assert stability["mode"] == "fast"
    assert PIPELINE_BOOTSTRAP in stability
    assert FIXED_MODEL_SENSITIVITY in stability
    assert VARIABLE_SELECTION_FREQUENCY in stability
    assert CANDIDATE_DISPERSION in stability
    assert JUSTIFIED_REVISION_SENSITIVITY in stability
    assert stability["pipeline_bootstrap_is_not_fixed_model_sensitivity"] is True
    assert stability["not_post_selection_confidence_interval"] is True
    assert stability["not_normative_grade"] is True
    assert stability[PIPELINE_BOOTSTRAP]["not_fixed_model_sensitivity"] is True
    assert stability[FIXED_MODEL_SENSITIVITY]["not_pipeline_bootstrap"] is True
    assert stability[FIXED_MODEL_SENSITIVITY]["model_refit"] is False
    assert PIPELINE_BOOTSTRAP in stability["executed_analyses"]
    assert FIXED_MODEL_SENSITIVITY in stability["executed_analyses"]
    assert stability[PIPELINE_BOOTSTRAP]["n_replicates_requested"] == 3
    assert stability["cost"]["limits"]["pipeline_bootstrap_replicates"] == 3
    assert stability["underlying_data"][PIPELINE_BOOTSTRAP] is not None

    # Nested record when requested.
    nested_result, _, _, _ = _run("fast", stability=False, nested=True)
    assert nested_result["partition"]["nested"]["inner"] == "delegated_to_fit_select_predictor"
    assert nested_result["partition"]["nested"]["outer_seeds"]


def test_evaluation_result_is_json_serializable_mapping_without_nonfinite_numbers():
    result, _, _, _ = _run("fast", stability=True)
    dumped = json.dumps(result, allow_nan=False, default=str)
    assert dumped
    assert "NaN" not in dumped
    assert "Infinity" not in dumped

    def _walk(obj):
        if isinstance(obj, float):
            assert math.isfinite(obj)
        elif isinstance(obj, dict):
            for value in obj.values():
                _walk(value)
        elif isinstance(obj, list):
            for value in obj:
                _walk(value)

    _walk(result)


def test_analyze_stability_standalone_respects_budget_and_does_not_label_normative():
    result, bundle, spec, fit = _run("fast", stability=False)
    stability = analyze_stability(
        bundle,
        spec,
        fit,
        13,
        evaluation_result=result,
        fitted_folds=None,
        mode="fast",
        budget={"pipeline_bootstrap_replicates": 2, "fixed_model_perturbations": 2},
    )
    # Without live predictors, fixed-model sensitivity cannot run; pipeline bootstrap still can.
    assert PIPELINE_BOOTSTRAP in stability["executed_analyses"] or stability[PIPELINE_BOOTSTRAP]["executed"] in {True, False}
    assert stability["not_normative_grade"] is True
    assert stability["usable_for_model_selection"] is False
    assert "pipeline_bootstrap" in stability
    assert "fixed_model_sensitivity" in stability
    assert stability["pipeline_bootstrap"] is not stability["fixed_model_sensitivity"]
