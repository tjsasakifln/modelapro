# C05 evidence — busca transparente, ranking e eficiência mensurável

Base: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`  
Contrato: MP/1  
Seed padrão dos testes: 0

## What shipped

- `modules.search_space` counts and enumerates the inclusion × transform space (groups stay grouped; domain-invalid transforms are dropped, not scored).
- `modules.optimal_combination.search_models` is the MP/1 entry point. `OptimalCombinationFinder.find_best_model` is an adapter over the same search.
- Ranking: numeric/technical admissibility, then required framing, then original-scale RMSE (never R² across transformed vs original target scales). Automatic row removal is not a scoring bonus. Missing metrics are omitted.
- Exact mode for spaces that fit the evaluation budget; otherwise budgeted diverse approximate search. `exact_optimum_guaranteed` is true only with exhaustive enumeration and full-objective evaluation of every candidate, plus a pruning proof (none is claimed).
- `candidate_cols=null` selects by role; `[]` is an explicit error (no authorized variables).
- `progress_callback` / `cancel_requested`, bounded history with full counters, in-process cache keyed by sample, policies, schema, transforms, objective, versions, and subject.

## Local measurements

Profile values come from `benchmarks/c05_search/profile_runner.py` on this host. They must not be extrapolated.

## Peers

C04 `fit_candidate` / `evaluate_fitted` and C06 inverse-target are consumed when present. Until those exports exist, production search uses the existing `ModelBuilder` OLS path (legacy, not a C04 substitute). C07 `evaluate_procedure` is never called from search.

## Commands

See `acceptance.json`.
