# C03 evidence — regras normativas verificáveis e extrapolação completa

## Identity

- Campaign: C03
- Branch: `mp-20260911/c03-validacao_normativa`
- Audit base: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`
- Edition: ABNT NBR 14653-2:2011 (authorized PDF in `docs/normas/`)
- Contract: MP/1

## What changed

`assess_normative(context)` is the MP/1 entry point. Item 4 now applies
Tabela 1 (a) measure **and** (b) original-unit |Δvalue| via
`predict_original`. Grau III remains “não admitida” whenever any
quantitative axis is outside [min, max]. Grau II requires one
extrapolated quantitative axis, the measure window, and |Δ|≤15% vs the
frontier prediction. Grau I requires the measure window and |Δ|≤20% de
per si **and** simultaneously.

Legacy `NBRValidator` classifiers remain as adapters. Measure-only
admission of Grau II/I is removed. Missing callback with extrapolation
is pending (`assess_normative`) / 0 (legacy int score). In-sample still
scores 3 without a callback.

n/k are taken from context. Intercept is not assumed via `shape[1]-1`.
Documentary grades without provenance stay `declared`, never `verified`.
Precisão statuses are `not_computed` | `classified` | `unclassified` |
`error`. VIF/R² remain warnings. Computed grau does not authorize
issuance.

## A01

Sample área [50, 100], avaliando 150, y = 10000×área.

Independent oracle: |ŷ(150)−ŷ(100)|/|ŷ(100)| = |1.5e6−1e6|/1e6 = 50%.
150 lies in [0.5·50, 2·100] = [25, 200] but item 4 is **not** approved.

## Tests

Shipped entry points driven (no mock of `assess_normative`):

- `tests/c03_normative/` C03-A01…A05, contract, composed OLS callback
- `tests/test_nbr14653.py` crystallized item-4 cases corrected to the
  standard (measure-only no longer expects Grau II/I)

Commands and exit codes: `acceptance.json`.

## Unverified rules

See `unverified_rules.md`. Full-norm conformity is **not** declared.

## Integration

C04 must wire `predict_original` and effective n/k/intercept. Until then
status is `INTEGRATION_PENDING`. C03 does not edit `modules/results.py`
or `modules/model_builder.py`.
