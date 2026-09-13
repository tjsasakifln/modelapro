# Independent OLS and interval conventions (P04)

This document is the numeric contract of `ols_oracle.py`. It is not a copy
of `modules.model_builder` and does not import the product.

## Model

Ordinary least squares with identity link on the original monetary unit:

\[
y = X\beta + \varepsilon, \quad \varepsilon_i \text{ iid}
\]

`X` always includes a leading column of ones named `const` (prepended).
No product helper chooses this matrix: the case spec lists the columns.

Point estimate:

\[
\hat\beta = \arg\min_\beta \| y - X\beta \|_2
\]

computed by reduced QR (`numpy.linalg.qr`, `mode="reduced"`) then
`R^{-1} Q^\top y`. Residual degrees of freedom \(n-p\) where \(p=\mathrm{rank}(X)\).

Unbiased residual variance:

\[
\hat\sigma^2 = \frac{\| y - X\hat\beta \|_2^2}{n-p}
\]

\[
\widehat{\mathrm{Var}}(\hat\beta) = \hat\sigma^2 (X^\top X)^{-1}
\]

with \((X^\top X)^{-1} = R^{-1}(R^{-1})^\top\).

## Intervals (two-sided Student-t)

Default level is **80%** (\(\alpha=0.20\)) so that the mean interval is
comparable to MP/1 `value.mean_ci80`. The same formulae apply at any
level in `(0, 1)`.

For a row \(x_0\) (including the leading 1):

\[
\hat y = x_0\hat\beta
\]

\[
\mathrm{se}_{\mathrm{mean}} = \hat\sigma \sqrt{x_0 (X^\top X)^{-1} x_0^\top}
\]

\[
\mathrm{se}_{\mathrm{pred}} = \hat\sigma \sqrt{1 + x_0 (X^\top X)^{-1} x_0^\top}
\]

\[
t^* = t_{1-\alpha/2,\, n-p}
\]

- **Mean CI** (statsmodels `mean_ci_*`): \(\hat y \pm t^*\,\mathrm{se}_{\mathrm{mean}}\)
- **Prediction interval** (statsmodels `obs_ci_*` / `get_prediction`): \(\hat y \pm t^*\,\mathrm{se}_{\mathrm{pred}}\)

These two intervals are distinct. A percent band around the point
(\(\hat y \times (1\pm k)\)) is not a statistical interval.

A second, independent cross-check may call `statsmodels.OLS(...).fit(method="qr", use_t=True).get_prediction` **directly**. That call is not an import of `modules.model_builder._predict_on_design`.

## Categories (treatment coding, independent of the product encoder)

When a case asks the oracle to encode a categorical column itself:

- Training levels = unique non-missing values on the **training** rows.
- Sort those levels as Unicode strings.
- Reference = the first sorted level (lexicographic). This is an oracle
  convention, not a claim about the product's most-frequent rule.
- Non-reference levels become columns named `{col}={level}`.
- A level that is absent from training is **unsupported**. It is not
  recoded to the reference and does not inherit a grade.

When comparing an **application path**, do not force search to pick this
encoding. Take the model the product actually chose, rebuild \(X\) from
that model's used rows and coefficient names, and run this oracle on
**that** matrix.

## Search vs oracle

- Numeric comparison: pin `candidate_cols` and identity \(y\) so the
  design is the case spec. Do not change default search just to hit a
  favourite model.
- Application-path comparison: use the chosen model; verify it against
  this oracle on the chosen design.
- Selection quality: exploratory evidence only; defaults stay unchanged.

## Holdout (independent partition)

For `evaluation_policy.method="holdout"` with `n_splits=1`, seed `s`,
`test_size=0.2` (the documented C07 default, reimplemented here from the
same public rule: shuffle with `numpy.random.RandomState(s)`, reserve the
first \(\mathrm{round}(n\cdot 0.2)\) ids, at least 1 and at most \(n-1\)):

- Inner selection must not see reserved ids.
- A category that exists only on reserved rows is not a training level.

## What this oracle does not claim

- Market accuracy.
- NBR item-4 wording (faixa ampliada 0.5×min–2×max is labelled as the
  campaign's characteristic-interval **probe**, verification pending).
- Human productivity. Machine time ≠ evaluator hours.
