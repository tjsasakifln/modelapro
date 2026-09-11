# C16 independent fixtures

All files in this directory are **synthetic**. They contain no client names,
addresses, phone numbers, documents, photos, or real market listings.

Row identifiers are generated integers. Prices follow closed-form rules
documented in `oracles.py` and `mapping.json` (typically `preco = 1000 * area`
or a documented linear combination). Locale tokens are textbook examples
(`R$ 1.234,56`, `1,234.56`).

Do not replace these with production extracts. Authorization would be required
before any real user data entered this tree.
