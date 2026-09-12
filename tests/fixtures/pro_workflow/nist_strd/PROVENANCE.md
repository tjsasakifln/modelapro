# Provenance — NIST/ITL StRD linear least squares reference data

Acceptance item: **MP-COM-20260912 / C06-A02** (independent numeric reference).

## 0. What this is, and what it emphatically is not

The NIST Statistical Reference Datasets (StRD) are reference data with certified
computational results, published by the Statistical Engineering Division of NIST/ITL.
They exercise **arithmetic only**: whether a least-squares implementation reproduces
known-correct numbers on inputs of known numerical difficulty.

Stated plainly, without hedging:

- Agreement with these certified values is **not a certification of MODELA PRO**.
  NIST has not examined, audited, tested, endorsed or approved MODELA PRO, this
  repository, or any part of it. No such act occurred.
- StRD is **not a normative authority**. It is not ABNT, it is not NBR 14653-2, and
  it grants nothing under any Brazilian standard or professional-practice rule.
- StRD says **nothing about real estate**. Its datasets are ozone-monitor
  calibration, load-cell calibration, macroeconomic time series and synthetic
  polynomials. None of them is a property sample, and none of them speaks to the
  validity of a valuation, the adequacy of a model specification, or the acceptance
  of a report by any institution, court, bank or regulator.
- What a passing comparison DOES support, and only this: the independent OLS oracle
  used by the P04 test suite computes least-squares quantities to the accuracy the
  numerical conditioning of the input permits. That is a statement about floating-point
  arithmetic, nothing more.

The only claim made in this directory is arithmetic reproduction. Any presentation of
this material as an external approval, accreditation, seal or third-party validation of
MODELA PRO would be false.

## 1. Retrieval

- **Retrieval date: 2026-09-11.**
- **Index page consulted:** <https://www.itl.nist.gov/div898/strd/lls/lls.shtml>
- **Data files:** `https://www.itl.nist.gov/div898/strd/lls/data/LINKS/DATA/<Name>.dat`
- **Channel:** the eleven `.dat` files were retrieved with `curl` (HTTP 200 each) so the
  bytes are unmodified. The sha256 values below are of the raw fetched files, CRLF line
  endings included. `curl` was used deliberately in preference to a page-summarising
  fetcher: certified values must be transcribed byte-exactly, and any
  markdown-conversion or model-summarisation step in the path would put that at risk.
- **Transcription:** `datasets.py` was generated mechanically from those raw bytes; no
  numeric value was typed from memory. NIST's `E-03` exponent notation is already valid
  Python float-literal syntax, so the literals can be diffed against the source files
  character by character.
- **Self-validation of the parse:** for every dataset, `RegressionSS / (RegressionSS +
  ResidualSS)` taken from the certified ANOVA table reproduces the separately-parsed
  certified R² to within 3.4e-16. A mis-parse of either block would break this.

### sha256 of the raw fetched files

| Dataset  | sha256 |
| -------- | ------ |
| Norris   | `5ab6906c68a9c4b2eb1661c0cd7d2a09f5a469a6d4e05b6b691f190f5f7b944f` |
| Pontius  | `de60baa5dc66fd804f9316f895bc5aa2b8f791c09d1ecc1ec39f8b199b8c15c7` |
| NoInt1   | `d8234c428dedaa9de23b67df7d04aeee83befae73ceb6b38321b224955a9b667` |
| NoInt2   | `a71c2810b1edcef8fec6b864c20c5f9d9908e530282a174772ce610999ca7c69` |
| Longley  | `fc4b0c824f8f0b834eb8e7d1c4c7e0b3cebdd7987bcb085e8f5e1007582480ea` |
| Wampler1 | `8bcd6f00dbe8c307ebc5c971e12b950eb3cdb75afbc2b38573082b5fcb0d7fbc` |
| Wampler2 | `01ba5f08b5b9f84431f3754216e006939a80264a1caa69fe08b3cbc543f9ee3e` |
| Wampler3 | `c5b025f6ebf0365de92d80e478ad826b01a6dfdafb71964ea8bae7eec993ce53` |
| Wampler4 | `dcff32075a52ecf31af70dad340776237544b1a29b5034a40f8b3e6b607cf9c1` |
| Wampler5 | `c4e260a6638db61287bfea75a2dd3b324c86c5d40931ddc6d8fab0c0305ffa39` |
| Filip    | `403b34689e401d915cb28bd69311d3ca5c3007d88d3b670b00e3203042315072` |

Each file is reachable at `SOURCE_URL_TEMPLATE.format(name)` in `datasets.py`, which
also carries the same sha256 per dataset.

## 2. Per-dataset record

All eleven were retrieved on 2026-09-11 from the URL pattern above. Difficulty level,
model form, observation count and data origin below are quoted from the header of the
`.dat` file itself.

| Dataset  | NIST difficulty | Model (as printed in the file) | n | p | Origin |
| -------- | --------------- | ------------------------------ | -- | -- | ------ |
| Norris   | Lower   | `y = B0 + B1*x + e` | 36 | 2 | Observed Data |
| Pontius  | Lower   | `y = B0 + B1*x + B2*(x**2)` | 40 | 3 | Observed Data |
| NoInt1   | Average | `y = B1*x + e` (**no intercept**) | 11 | 1 | Generated Data |
| NoInt2   | Average | `y = B1*x + e` (**no intercept**) | 3 | 1 | Generated Data |
| Longley  | Higher  | `y = B0 + B1*x1 + ... + B6*x6 + e` | 16 | 7 | Observed Data |
| Wampler1 | Higher  | `y = B0 + B1*x + ... + B5*(x**5)` | 21 | 6 | Generated Data |
| Wampler2 | Higher  | `y = B0 + B1*x + ... + B5*(x**5)` | 21 | 6 | Generated Data |
| Wampler3 | Higher  | `y = B0 + B1*x + ... + B5*(x**5)` | 21 | 6 | Generated Data |
| Wampler4 | Higher  | `y = B0 + B1*x + ... + B5*(x**5)` | 21 | 6 | Generated Data |
| Wampler5 | Higher  | `y = B0 + B1*x + ... + B5*(x**5)` | 21 | 6 | Generated Data |
| Filip    | Higher  | `y = B0 + B1*x + ... + B10*(x**10)` | 82 | 11 | Observed Data |

Citations printed by NIST in the files themselves: Norris, J., NIST (*Calibration of
Ozone Monitors*); Pontius, P., NIST (*Load Cell Calibration*); Eberhardt, K., NIST
(NoInt1, NoInt2); Longley, J. W. (1967), *JASA* 62, 819–841; Wampler, R. H. (1970),
*JASA* 65, 549–565; Filippelli, A., NIST.

Transcribed per dataset into `datasets.py`: every certified parameter estimate, every
certified standard deviation of estimate, the certified residual standard deviation, the
certified R², the certified ANOVA table (df / sums of squares), and the certified data.

### R² convention — read before comparing

NIST certifies a **centred** R² for the intercept datasets and an **uncentred** R² for
the two no-intercept datasets. This is verifiable in the files rather than assumed: for
NoInt1, `RegSS + ResidSS = 200457.727272727 + 127.272727272727 = 200585 = Σy²` exactly
(not `Σ(y − ȳ)²`); for NoInt2, `40.7272727272727 + 0.272727272727273 = 41 = Σy²`. For
Norris the same sum reproduces `Σ(y − ȳ)²`. The test uses each convention accordingly.

## 3. NIST's own statements, as actually read

Two different confidence levels apply here, and they are labelled as such.

**(a) Byte-verified.** The eleven `.dat` files, fetched by `curl`, contain no licence,
no terms-of-use clause and no data-availability statement. They carry only the dataset
header, the certified values and the data.

**(b) Read through an automated fetch-and-summarise step, NOT byte-verified.** The
following came back from a tool that converts a page to markdown and answers a question
against it. They are recorded as read, with that caveat stated, rather than presented as
guaranteed-verbatim quotations:

- From <https://www.itl.nist.gov/div898/strd/>, on the purpose of the project:
  > "The purpose of this project is to improve the accuracy of statistical software by
  > providing reference datasets with certified computational results that enable the
  > objective evaluation of statistical software."
- From the NIST site-wide disclaimer (<https://www.nist.gov/disclaimer>), on copyright
  status: *"information presented on NIST sites are considered public information and may
  be distributed or copied"*; and on warranty: *"NIST makes no warranties to that effect,
  and NIST shall not be liable for any damage that may result from errors or omissions in
  the Database."*

**Negative finding, recorded honestly:** neither the StRD linear-least-squares index page
(`lls.shtml`) nor the StRD data-archive page carries any licence or terms-of-use
statement of its own. The only availability language found anywhere in the retrieval path
is the site-wide NIST disclaimer linked in (b). Nothing was found that grants, implies or
could be read as an endorsement of any third-party product; and nothing found suggests a
restriction on reproducing these datasets for software testing. Anyone relying on this for
a redistribution decision should re-read the NIST disclaimer directly rather than trust
this summary.

## 4. Pre-registered accuracy floors

The tolerances in `datasets.py` were derived by a fixed rule and frozen **before** any
comparison against the oracle was executed. They were not chosen after seeing a result,
and nothing here may be loosened after seeing one.

The rule, per dataset:

```
kappa_eq      = cond_2(X with every column scaled to unit norm)
rho           = sqrt(certified residual SS) / (||X_eq||_2 * ||diag(colnorms) @ beta_cert||_2)
digits(A)     = max(0, 15 - log10(A))          # 15 ~ decimal digits of IEEE-754 double
rel_floor(A)  = 10 ** -(digits(A) - 1)         # 1 digit of engineering margin

beta                    : A = kappa_eq + kappa_eq**2 * rho   (Higham, ASNA Thm 20.1)
residual sigma-hat, R^2 : A = kappa_eq        (the projection onto col(X) is far better
                                               determined than coordinates within it)
parameter std deviations: A = kappa_eq**2     (they come from diag((X'X)^-1))
```

Both inputs to the rule — the design matrix and `rho` — come from the fetched data and
NIST's certified values only. Neither depends on any oracle output, so computing them
first is pre-registration, not peeking. The equilibrated condition number is the quantity
that governs per-coefficient relative error; the raw condition number would be dominated
by mere column scaling (Pontius' `x²` column runs to ~1e13) and would hand easy datasets
a vacuous tolerance. As an external check that the quantity is the intended one: the
value computed here for Longley, `kappa_eq = 4.3275e4`, reproduces Belsley's published
scaled condition number for Longley (43275).

Resulting floors, all frozen in `datasets.py`:

| Dataset  | kappa_eq | rho | beta floor | sigma/R² floor | std-dev floor |
| -------- | -------- | --- | ---------- | -------------- | ------------- |
| Norris   | 2.801e+00 | 1.19e-03 | 2.81e-14 | 2.80e-14 | 7.84e-14 |
| Pontius  | 1.845e+01 | 9.07e-05 | 1.85e-13 | 1.84e-13 | 3.40e-12 |
| NoInt1   | 1.000e+00 | 2.52e-02 | 1.03e-14 | 1.00e-14 | 1.00e-14 |
| NoInt2   | 1.000e+00 | 8.18e-02 | 1.08e-14 | 1.00e-14 | 1.00e-14 |
| Longley  | 4.328e+04 | 1.75e-05 | 7.60e-10 | 4.33e-10 | 1.87e-05 |
| Wampler1 | 2.220e+03 | 0.00e+00 | 2.22e-11 | 2.22e-11 | 4.93e-08 |
| Wampler2 | 2.220e+03 | 0.00e+00 | 2.22e-11 | 2.22e-11 | 4.93e-08 |
| Wampler3 | 2.220e+03 | 8.07e-04 | 6.20e-11 | 2.22e-11 | 4.93e-08 |
| Wampler4 | 2.220e+03 | 8.07e-02 | 4.00e-09 | 2.22e-11 | 4.93e-08 |
| Wampler5 | 2.220e+03 | 8.07e+00 | 3.98e-07 | 2.22e-11 | 4.93e-08 |
| Filip    | 5.207e+09 | 3.33e-10 | 1.42e-04 | 5.21e-05 | **1.0 (vacuous)** |

The rule *predicts in advance* that Filip's parameter standard deviations carry no
reproducible significant digit in double precision (`kappa_eq**2 ≈ 2.7e19` exceeds the
precision of the arithmetic outright), so for that quantity the test asserts only
finiteness and records the measured error. That is the documented limit the rule
produced, declared before the run — not a tolerance relaxed after seeing a number. It
applies to Filip's *standard deviations* only; Filip's coefficients pass with margin.

### 4.1 A correction to the METRIC, with the floors left untouched

This must be on the record, because a reader has to be able to check that no tolerance
moved.

**v1, as pre-registered.** The floors above, asserted against the *componentwise*
relative error `|beta_hat_j − beta_cert_j| / |beta_cert_j|` in *raw* coordinates.

**The run.** Six of eleven datasets failed: Norris, Pontius, Wampler1, Wampler3,
Wampler4, Wampler5. **Every single failure was on `B0`.** No other coefficient missed on
any dataset.

**The diagnosis.** The failure was in the pre-registration, not in the oracle, and the
all-`B0` signature is what shows it. Higham ASNA Thm 20.1 bounds a **normwise** relative
error, and `kappa_eq` was computed for the **column-equilibrated** matrix — so the bound
governs `||D(beta_hat − beta_cert)|| / ||D beta_cert||`, not a raw componentwise ratio.
The two differ by up to `||D beta_cert|| / |D_jj beta_cert_j|`, and the intercept is the
smallest equilibrated component in every failing design (Norris: `B0 = −0.262` against a
response running to 998; Wampler: `B0 = 1.0` against an `x**5` column of norm ~3.5e6).
Applying a normwise bound to a componentwise metric is a derivation error in v1.

That Norris — the canonical *well-conditioned* set — was among the failures is decisive:
no defensible reading calls the oracle defective there.

**Independent exoneration of the oracle.** Minimum correct digits across all
coefficients, same data, same raw basis (this is a recorded observation, not an assertion
in the test suite — making a library comparison load-bearing would require a slack
constant chosen after seeing these numbers):

| Dataset | oracle (QR) | numpy `lstsq` (SVD) | statsmodels | normal equations |
| --- | --- | --- | --- | --- |
| Norris   | 12.09 | 12.85 | 12.77 | 11.82 |
| Pontius  | 12.39 |  6.24 |  6.24 | 11.53 |
| NoInt1   | 14.72 | 14.72 | 14.72 | 14.72 |
| NoInt2   | 15.12 | 15.21 | 15.12 | 15.34 |
| Longley  | 10.92 | 10.99 | 10.99 |  7.38 |
| Wampler1 |  9.47 |  9.78 |  9.55 |  6.25 |
| Wampler2 | 13.22 | 10.12 | 10.12 |  9.37 |
| Wampler3 |  9.15 |  9.02 |  9.40 |  6.25 |
| Wampler4 |  7.67 |  7.68 |  7.67 |  6.25 |
| Wampler5 |  5.68 |  5.68 |  5.67 |  6.25 |
| **Filip**|**8.55**|**0.00**|**0.00**|  0.00 |

The oracle is at parity with the reference implementations everywhere and materially
ahead on Filip (~8.5 digits) and Pontius (~6 digits), where the library SVD path returns
no correct digit at all on Filip.

**v2, as now asserted.** The floors are the **same literals, unchanged**. Only the metric
was corrected to the one the bound governs:

```
rel_eq  = ||D (beta_hat - beta_cert)||_2 / ||D beta_cert||_2   <=   beta_rel_floor
floor_j = beta_rel_floor * ||D beta_cert||_2 / |D_jj * beta_cert_j|   (per coefficient)
```

Achieved under v2, against the untouched floors — all eleven pass, with the tightest
dataset at 19% of its budget:

| Dataset | achieved `rel_eq` | pre-registered floor | used |
| --- | --- | --- | --- |
| Norris   | 4.008e-15 | 2.810e-14 | 14% |
| Pontius  | 6.221e-16 | 1.848e-13 |  0.3% |
| NoInt1   | 1.927e-15 | 1.025e-14 | 19% |
| NoInt2   | 7.633e-16 | 1.082e-14 |  7% |
| Longley  | 5.661e-13 | 7.603e-10 |  0.07% |
| Wampler1 | 1.097e-14 | 2.220e-11 |  0.05% |
| Wampler2 | 2.151e-14 | 2.220e-11 |  0.1% |
| Wampler3 | 1.016e-13 | 6.196e-11 |  0.2% |
| Wampler4 | 4.339e-12 | 3.998e-09 |  0.1% |
| Wampler5 | 4.341e-10 | 3.976e-07 |  0.1% |
| Filip    | 6.239e-10 | 1.424e-04 |  0.0004% |

One hypothesis was considered and **rejected**: adding a dimension-dependent
backward-error constant `log10(n*p)` to the margin. It would have covered the observed
gaps numerically, but a `c(n,p)` factor degrades all coefficients roughly uniformly and
could not produce an exclusively-`B0` failure pattern across designs with n from 21 to 40
and p from 2 to 6. Adopting it would have been a textbook citation wrapped around a
number chosen to fit what had just been seen — which is exactly what these floors exist
to prevent.

Certified-zero quantities (Wampler1 and Wampler2 have an exact fit: residual standard
deviation and all parameter standard deviations are certified `0.000000000000000`) cannot
be compared relatively. They use an absolute floor scaled to the data,
`ZERO_SIGMA_REL = 1e-9` times `rms(y)`. Justification, also pre-registered: with an exact
fit the computed residual is pure roundoff, bounded by roughly
`u * kappa_eq * ||y|| ≈ 2.2e-16 * 2.2e3` relative, i.e. ~5e-13 — so 1e-9 leaves more than
three orders of margin while remaining a real constraint.

## 5. Files

- `datasets.py` — data and certified values as plain Python literals. Imports nothing at
  all, and in particular nothing from `modules/`, `backend/` or `frontend/`.
- `tests/pro_workflow/p04/test_nist_strd.py` — compares the independent oracle
  (`tests/fixtures/pro_workflow/ols_oracle.py`) against the certified values under the
  floors above. It does not modify the oracle.
