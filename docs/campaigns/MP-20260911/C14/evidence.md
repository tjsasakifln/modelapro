# C14 evidence — avaliações em lote e reúso controlado de modelos

Campaign: C14  
Contract: MP/1  
Base: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`  
Branch: `mp-20260911/c14-lotes_reuso_modelos`  
Owned paths: `modules/valuation_batch.py`, `tests/c14_batch/`, `benchmarks/c14_batch/`, `docs/campaigns/MP-20260911/C14/`

## What shipped

`modules.valuation_batch.evaluate_batch(frozen_project, subjects, request_spec, progress_callback=None, cancel_requested=None)` applies a frozen project/model to many subjects without a new search or a new fit.

- `model_scope=population_model` requires a declared domain; a subject outside the domain is `unsupported` with reason `requires_individual_analysis` and a null value (never a substitute zero).
- `model_scope=subject_specific` is not reused as a silent population model. Another subject gets `unsupported` unless it satisfies `subject_constraints`.
- C02/C03/C04/C06 are called by MP/1 names when importable. C04 `evaluate_fitted` is used only for a live in-process `CandidateFit` with `model_object`. A specification-only FrozenProject is applied from stored coefficients/encoder_state (no pickle).
- C03 item 4 (extrapolation) and precisão are recomputed per subject via `NBRValidator` classifiers when present. Documentary items are taken from that subject only.
- Reuse key is the SHA-256 of the complete identity (hashes, sample ids/exclusions, schema, encoder, model spec, target+unit, policies, normative version, scope, and subject constraints when subject-specific). Filename, isolated row count, or target column alone do not form the key.
- Persistence coordinator is an in-process `ReuseLedger`. If C11 `ProjectStore` is importable it can be bound; C14 does not open Redis or a second database.
- Cancel marks remaining items `pending` (not success). Resume copies completed items and evaluates only proven pending ones. `max_workers` is capped at 8.
- Export is the structured `BatchResult` mapping (`result["export"]`), not a consolidated PDF.

## Commands

```
python3 -m pytest tests/c14_batch/ -q
# 16 passed, exit 0 (run twice)
python3 benchmarks/c14_batch/run_benchmark.py -n 40 --seed 20260911
# exit 0, reused_oracle_mismatches=0
```

Versions (isolated worktree at the audited base): python 3.12.3, pytest 9.1.1, pandas 3.0.5, numpy 2.5.2, statsmodels 0.15.0, scipy 1.18.1. Platform: Linux x86_64 (WSL2). Seed 20260911. Data: synthetic, identified.

## Acceptance mapping

- C14-A01: `tests/c14_batch/test_a01_domain_independence.py` — in-domain vs out-of-domain keep independent fundamentação/precisão; documentary lists are not copied; subject-specific model is not silent population reuse. Fresh consumer in scratch `c14_consumer.log` shows grades 3 vs null, points 350000 vs null.
- C14-A02: `tests/c14_batch/test_a02_unknown_category.py` — unknown category fails only that item; summary counts succeeded/failed/pending; item remains in the list; value is null not zero.
- C14-A03: `tests/c14_batch/test_a03_reuse_key.py` — mutating input hash, dataset hash, exclusions, schema, transformation, unit, policy, normative version, or subject-specific constraints changes the key; filename/n_rows do not; identical inputs reproduce; duplicate ids and resume do not duplicate items.
- C14-A04: `tests/c14_batch/test_a04_cancel_resume.py` — cancel after the first item leaves the rest pending; resume preserves the completed item (including a tampered stored point, proving no rewrite) and evaluates only pending ones; progress is completed/total.
- C14-A05: `tests/c14_batch/test_a05_parity.py` — batch `value.point` matches both the independent linear oracle and the individual `evaluate_fitted` path in BRL. Benchmark records preprocess/fit/evaluate/memory; no productivity multiplier is claimed.

## Benchmark (measurement, not a claim)

N=40 synthetic subjects, seed=20260911, fit_rows=80, max_workers=1.

| path | preprocess s | fit s | evaluate s | total s | mem_peak_mb |
| --- | --- | --- | --- | --- | --- |
| N individual (preprocess+OLS fit+predict each) | ~0.10 | ~0.31 | ~0.05 | ~0.46 | ~0.24 |
| 1 fit + evaluate_batch | ~0.003 | ~0.006 | ~0.24 | ~0.25 | ~1.34 |

Fit reuse is visible in the fit column. `evaluate_batch` does more per subject (encoder, domain, normative) than a bare `np.dot`, so evaluate time is not a laudo-throughput multiplier. Observed total ratio on this machine is a measurement only.

## Review (author)

- Did not wrap `find_best_model(..., avaliando_raw=...)` as batch reuse (that path is subject-conditioned and would recreate F04/F05/F11/F13).
- `model_eligibility.status=eligible` is not treated as issuance authorization.
- Calculation failure is null + issue.
- Did not edit worker, API, UI, or other owners' files.
- C10 `POST /projects/{id}/batch`, C11 job persistence, C09 UI, and C12 evidence bundle remain handoffs.

## Residual risks

- Integrated numeric parity against a live C04 `CandidateFit.model_object` restored by C11 is not claimed here (C04 restore/C11 revision storage are other owners).
- `assess_normative` (C03) and `inverse_target_prediction` (C06) are consumed when published; at the audited base they are unpublished and the frozen-application / `NBRValidator` classifiers run instead.
- No HTTP route was added (C10 owns it).
