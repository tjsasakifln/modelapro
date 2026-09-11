# C01 — Importação íntegra e sem preços inventados

Campaign: `C01`  
Contract: `MP/1`  
Base: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`  
Branch: `mp-20260911/c01-dados_integros`

## Findings reproduced on the audited HEAD

On `c92949e` before the change:

- **F02** `DataLoader.load_data` filled numeric NaN with the column mean. Fixture `preco=[600000,800000,ausente]` returned `n=3` and materialised `700000.0`.
- **F03** `safe_float_conversion` did `replace('.', '')` then comma-to-dot. Observed: `"1.234"→1234.0`, `"123.45"→12345.0`, `"1,234.56"→1.23456`. `"R$ 1.234,56"` happened to work.
- **F16 / preview split**: `frontend/components/forms.py` still calls `pd.read_csv` / `pd.read_excel` directly (not edited here). C01 centralises interpretation in `modules.import_formats.read_tabular` + `ingest_market` for C09/C10 to consume via `/preview`.

## What shipped

`modules.data_loader.ingest_market(file_bytes, filename, request_spec) -> InputBundle` with `schema_version`, `raw_frame`, `parsed_frame`, `column_map`, `row_ledger`, `input_sha256`, `issues`.

Three stages: read bytes → raw table; reversible name map + locale-aware numbers (roles recognised first); disposition by `row_id` without fill. `DataLoader.load_data` is an adapter: no mean imputation, no one-hot, no silent drop of high-cardinality text.

## Verification commands

Environment: Python 3.12.3, pandas 3.0.5, pytest 9.1.1, numpy 2.5.2, openpyxl 3.1.5 (undeclared in requirements — C15). xlrd absent.

```
python3 -m pytest tests/test_data_loader.py tests/c01_input/ -q
```

Exit 0, 40 passed.

Fresh consumer (not the pytest module), twice:

```
PYTHONPATH=. python3 {SCRATCH}/c01_launch_consumer.py
```

Both runs: `observed 2`, prices `[600000.0, 800000.0, nan]`, `has_700000 False`, `pending_n 1`, `LAUNCH_OK`.

Adapter:

```
DataLoader.load_data(a01_precos.csv)
```

`has_700000 False`, missing target remains NA, `ADAPTER_OK`.

## Criteria

| id | result | note |
| --- | --- | --- |
| C01-A01 | pass | two observed targets; 700000 never created; pending in ledger; `missing_before` captured from raw |
| C01-A02 | pass | pt-BR `R$ 1.234,56`→1234.56; en-US `1,234.56`→1234.56; `123.45`→123.45; auto `"1.234"` ambiguous, magnitude unchanged |
| C01-A03 | pass | `;` + decimal comma + BOM + `.CSV` and xlsx produce the same interpreted values/dispositions; hashes differ; `.xls` without xlrd is a structured engine issue |
| C01-A04 | pass | collisions, duplicate IDs, inf, empty file, missing target, `candidate_cols=[]`, absent column, malformed numbers — all explicit |
| C01-A05 | pass | `reconstruct_original_record` recovers raw values and changes; fixtures synthetic |

## Self-review

- `row_id` is reserved so a source column named `row_id` cannot overwrite identity.
- Ambiguous numbers stay as the original token (not 1234).
- `load_data` without `request_spec` does not guess a target column; it still does not invent 700000.
- High-cardinality text stays in the frame; capacity is a warning for C02, not an exclusion.
- Reading metadata is logged at INFO and also attached as `read_metadata` issues so it does not vanish.

No personal data in fixtures (synthetic `Rua Exemplo`, `(11) 90000-0000`, CEP `01310-100`).
