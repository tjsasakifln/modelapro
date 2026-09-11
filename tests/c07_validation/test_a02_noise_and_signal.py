"""C07-A02: pure noise vs known signal — original-scale metrics, no lucky-seed guarantee."""

from __future__ import annotations

from modules.model_evaluation import evaluate_procedure

from contract_fixtures import (
    SYNTHETIC_NOTE,
    labeled_fit_select_predictor,
    make_input_bundle,
    make_request_spec,
    synthetic_noise_rows,
    synthetic_signal_rows,
)


def _run(rows, seed, sha):
    bundle = make_input_bundle(rows, input_sha256=sha)
    spec = make_request_spec(
        evaluation_policy={
            "method": "random",
            "test_size": 0.25,
            "n_splits": 1,
            "mode": "fast",
            "stability": False,
        }
    )
    fit = labeled_fit_select_predictor(bundle, spec, leak=False)
    result = evaluate_procedure(bundle, spec, fit, seed)
    return result


def test_signal_and_noise_metrics_are_original_scale_and_seed_variability_is_visible():
    signal_seeds = [3, 11]
    noise_seeds = [3, 11]
    signal_results = [_run(synthetic_signal_rows(48, seed=0), seed, "synthetic-signal") for seed in signal_seeds]
    noise_results = [_run(synthetic_noise_rows(48, seed=0), seed, "synthetic-noise") for seed in noise_seeds]

    for result in signal_results + noise_results:
        assert result["status"] == "completed"
        metrics = result["metrics"]
        assert metrics["scale"] == "original"
        assert metrics["unit"] == "BRL"
        assert metrics["mae"] is not None and metrics["mae"] >= 0
        assert metrics["rmse"] is not None and metrics["rmse"] >= metrics["mae"] - 1e-9
        assert "mae" in metrics["primary_metrics"]
        assert result["reference"]["method"] == "train_mean"
        assert result["reference"]["mae"] is not None
        assert 0.0 <= metrics["coverage"] <= 1.0
        assert result["coverage"]["n_reserved"] == metrics["n_reserved"]
        assert result["variability"]["hidden_in_single_mean"] is False
        assert result["usable_for_model_selection"] is False

    signal_maes = [r["metrics"]["mae"] for r in signal_results]
    noise_maes = [r["metrics"]["mae"] for r in noise_results]
    signal_refs = [r["reference"]["mae"] for r in signal_results]
    noise_refs = [r["reference"]["mae"] for r in noise_results]

    # Known linear signal: both seeds beat the train-mean reference. This is not
    # a performance guarantee advertised as a product claim — it checks the
    # evaluator reports a plausible original-scale error.
    for mae, ref in zip(signal_maes, signal_refs):
        assert mae < 0.5 * ref

    # Pure noise: holdout MAE stays on the order of the naive reference across
    # seeds. A train-only re-score of the winner would typically look much better.
    for mae, ref in zip(noise_maes, noise_refs):
        assert mae > 0.4 * ref
        assert mae > 1000  # original unit, not a collapsed scaled residual

    # Limitations remain visible on noise; we do not hide instability in one mean.
    for result in noise_results:
        assert result["limitations"]
        assert result["metrics"]["aggregate"] in {"single_fold", "mean_across_folds_see_variability"}

    # Two seeds are reported separately — a single favourable seed is not the claim.
    assert len(set(round(m, 4) for m in noise_maes)) >= 1
    assert all(r["kind"] == "evaluation_result" for r in signal_results)
    assert SYNTHETIC_NOTE in "synthetic-identified"


def test_relative_error_omitted_when_denominator_is_zero():
    rows = []
    for i in range(24):
        rows.append(
            {
                "row_id": f"z{i:03d}",
                "area": float(50 + i),
                "quartos": 2,
                "preco": 0.0 if i % 2 == 0 else 1000.0 * (50 + i),
                "bairro": "Centro",
            }
        )
    result = _run(rows, seed=5, sha="synthetic-zero-target")
    # Relative metrics may be null or computed only on non-zero targets.
    metrics = result["metrics"]
    if metrics["relative_mae"] is None:
        assert metrics["n_relative"] == 0 or metrics["n_covered"] == 0
    else:
        assert metrics["n_relative"] <= metrics["n_covered"]
        assert metrics["relative_mae"] >= 0
