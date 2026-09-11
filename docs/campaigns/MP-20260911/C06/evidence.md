# C06 evidence — Domínios corretos e transformação responsável do preço

Campaign: C06  
Lot: MP-20260911  
Contract: MP/1  
Base: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`  
Branch: `mp-20260911/c06-transformacoes_alvo`  
Head (implementation): `a416db2ea85c245018dd270171153800e6d494f1`  
PR: https://github.com/tjsasakifln/modelapro/pull/1

## What changed

`Transformer.apply_transformation` keeps the legacy `(series, bool)` unpack used by C04/C05 and now carries `failure_code` on failure. Domains are no longer lumped:

- `sqrt` accepts 0 and rejects negatives (`sqrt([0,1,4]) -> [0,1,2]`).
- `ln` / `inv_sqrt` require strictly positive values.
- `inverse` / `inv_sqr` require nonzero (negatives allowed).
- Input NaN/inf, output inf/overflow, and unknown names fail with `success=False` and a distinguishable `failure_code`. Non-finite values are never a successful transform.

`Transformer.test_transformations` still computes Shapiro-Wilk on the marginal X as a diagnostic. It no longer sorts or ranks by that p-value.

New module `modules/target_transform.py` exports:

- `fit_target_transform(y_train, name, options=None)`
- `transform_target(y, state)`
- `inverse_target_prediction(prediction, state, residual_context=None)`

Families: **identity** and **log** only. State is a JSON-friendly mapping learned from the training sample. Inverse returns original-unit values with `estimand`, `method`, `assumptions`, and `limitations`. `exp(E[log Y|X])`, `E[Y|X]` under lognormal, and Duan smearing are distinct. Holdout residuals cannot estimate a correction. Log-scale intervals are not published as `mean_ci80`.

## F12 reproduction (before the fix)

At base `c92949e`, `sqrt([0,1,4])` returned `success=False` because `ln`/`sqrt`/`inv_sqrt` shared a `<= 0` check. Failures had no `failure_code`. After the fix, `sqrt([0,1,4])` succeeds with `[0,1,2]`; `ln(0)` is `domain_zero`; `sqrt(-1)` is `domain_negative`; `inverse(0)` is `domain_zero`.

## Commands

Python 3.12.3, numpy 2.5.2, pandas 3.0.5, scipy 1.18.1, pytest 9.1.1.

```
cd /home/tjsasakifln/code/modela-pro-c06
python3 -m pytest tests/test_transformations.py tests/c06_transformations/ -q
# run 1: 43 passed, exit 0
# run 2: 43 passed, exit 0

PYTHONPATH=. python3 tests/c06_transformations/print_observables.py
# both launches identical; sqrt_line=0,1,2
```

Logs (scratch, not committed): `pytest_c06_1.log`, `pytest_c06_2.log`, `launch_1.txt`, `launch_2.txt`.

Seed used in the synthetic lognormal case: `20260911` (`np.random.default_rng(20260911)`), μ=1.0, σ=0.5. Analytic oracles in the test: `exp(μ)` median, `exp(μ+σ²/2)` mean.

## Caller check (read-only)

`tests/test_optimal_combination.py` and `tests/test_model_builder.py` still pass (apply_transformation unpack compatibility).

`tests/test_audit_fixes.py::TestAvaliandoDomainPreFilter::test_transformation_invalid_for_avaliando_value_is_excluded_from_search` **fails as expected**: with avaliando `idade=0`, C05 now keeps `sqrt(idade)` (valid) and still drops `ln` / `inv_sqrt` / `inverse` / `inv_sqr`. C06 must not edit that C16 file; see `handoff.json`.

## Self-review

- Identity inverse equals the prediction; identity `mean_ci80` is passed through only on the original scale.
- Log inverse default is `exp(E[log Y|X])`, not the monetary mean. `mean_ci80` stays null. `precisao.grade` stays null. Normative classification is `unavailable` for log.
- Residual correction requires `residual_context.origin == "train"`. The origin label is trusted; a caller that lies about origin can still pass holdout residuals. Documented limitation for C04/C07.
- No new third-party dependencies.
- Extra Y families (Box-Cox, sqrt-on-Y, …) were not added.

## Status

`READY_COMPONENT` for C06 local acceptances C06-A01..A05. Full-suite CI of this PR may fail the C16 sqrt(0) assertion until C16 applies the handoff.
