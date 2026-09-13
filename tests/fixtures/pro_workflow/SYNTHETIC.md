# P04 synthetic corpus

Every file under `tests/fixtures/pro_workflow/` is **synthetic**. There are
no client names, addresses, phones, documents, photos, or real listings.

Row identifiers are generated tokens (`IM-001`, …). Prices follow the
closed-form data-generating processes in `corpus.py` plus the independent
OLS conventions in `CONVENTIONS.md` / `ols_oracle.py`.

Do not replace these with production extracts. Authorization would be
required before any real user data entered this tree.

Expected numeric values are computed by `ols_oracle.py`. That module does
not import `modules.*`, `backend.*`, or `frontend.*`. Product output is
never copied into the expected-value tables.
