# C02 evidence — esquema único, categorias e prevenção de vazamento

Campaign: C02  
Lote: MP-20260911  
Contract: MP/1  
Base: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`  
Head (implementation): `797c75dbec8d0b34739bca40bbcf90dcf4164b94`  
Branch: `mp-20260911/c02-esquema_categorias`  
Worktree: `/home/tjsasakifln/code/modela-pro-c02` (exclusive; shared checkout was occupied by C14)

## What shipped

`modules.preprocessing.fit_dataset` and `modules.preprocessing.transform_subject` around an explicit `feature_schema` and declarative JSON-safe `encoder_state` (`modules/variable_schema.py`).

- Subject is entered as original values (`bairro="Centro"`), not dummy names.
- Encoder, imputation and category levels are fit only on `train_row_ids` (held-out rows never choose means or levels).
- Unknown category, predictor absence, unsupported group and constant/collinear columns are distinct issues; unknown/missing never become the reference encoding (NaN on the group, `supported=False`).
- Target is never imputed. Identifiers and `row_id` never enter `X`. Dates without an explicit interpretation stay `date_pending`.
- `candidate_cols=[]` is an explicit error; `null` is selection by role.
- Indicator groups stay atomic (`groups[base].columns` + per-column `group_id` / `reference_category`).
- High cardinality is diagnosed and still encoded.

## Commands

```
python3 -m pytest tests/c02_schema/ -v --tb=short
# exit 0; 8 passed, 1 skipped (C01 ingest_market not on this SHA)
python3 tests/c02_schema/launch_consumer.py
# run 1 and run 2, both exit 0, identical observables
```

Versions: Python 3.12.3, pytest 9.1.1, pandas 3.0.5, numpy 2.5.2. No new dependencies.

## Pytest (captured)

8 passed, 1 skipped:

- A01 shared encoder: PASS (`test_a01_bairro_and_formatted_numeric_share_encoder`)
- A02 distinct states: PASS (`test_a02_unknown_missing_unsupported_group_and_constant_are_distinct`)
- A03 leakage + empty candidates: PASS
- A04 JSON persist/restore: PASS
- A05 atomic groups / n / free parameters: PASS
- Boundaries (undeclared missing_policy, high cardinality encoded): PASS
- C01 real bundle: SKIPPED (`ingest_market` not published on `c92949e`)

## Launch consumer (two fresh processes)

Both runs printed:

```
numeric=True
supported=True
train_mean=20.0
imputed_mean=20.0
expected_mean=20.0
columns=['bairro_Norte', 'bairro_Sul', 'area']
held_out_in_categories=False
dataset_sha256=0f668fedddbd9879b98655715342f431b44667c377f7273c7c38115fb3c3198c
ok=True
```

Expected mean is the independent train literal `(10+20+30)/3 = 20.0`. Reserved category `ZonaReservada` is absent from known levels.

## Reproduction of the audited load-time behaviour (read-only)

On the audited SHA, `modules/data_loader.py` still one-hot encodes at load (`pd.get_dummies(..., drop_first=True)`) and fills all numeric columns (including target) with the full-frame mean. `frontend/components/forms.py` still offers a numeric-only avaliando editor. C02 does not edit those files; consumers must switch to `fit_dataset` / `transform_subject` via the handoff.

## Self-review

- Duplicate `constant_column` issues can appear (once at encoder fit, once on the design matrix). Codes remain distinct from unknown/missing/group_no_support.
- C01 `ingest_market` is not on this branch; the C01-real test is skip-gated and is not treated as fixture evidence.
- C09/C10 still use the legacy dummy expansion until they consume the handoff.
- High-cardinality threshold (20 levels or > n/2) is diagnostic only; levels are still encoded.

Fixtures under `tests/c02_schema/` are labeled synthetic MP/1 (`_fixture_kind: synthetic_mp1`), not C01 output.
