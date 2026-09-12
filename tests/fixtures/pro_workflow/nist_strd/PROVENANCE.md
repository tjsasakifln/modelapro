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
  repository, or any part of it. No such act occurred. NIST's own site-wide text says
  as much in general terms, and it is quoted verbatim in section 3.
- StRD is **not a normative authority**. It is not ABNT, it is not NBR 14653-2, and
  it grants nothing under any Brazilian standard or professional-practice rule.
- StRD says **nothing about real estate**. Its datasets are ozone-monitor
  calibration, load-cell calibration, macroeconomic time series and synthetic
  polynomials. None of them is a property sample, and none of them speaks to the
  validity of a valuation, the adequacy of a model specification, or the acceptance
  of a report by any institution, court, bank or regulator.
- Every tolerance in this directory is **ours**, not NIST's. NIST publishes certified
  values and nothing else. No number in `datasets.py` that is not a certified value or
  a data point carries any NIST authority.
- What a passing comparison DOES support, and only this: the independent OLS oracle
  used by the P04 test suite computes least-squares quantities to the accuracy the
  numerical conditioning of the input permits. That is a statement about floating-point
  arithmetic, nothing more — and section 4.3 records exactly how sharp that statement
  is, because a pass against a worst-case bound is much weaker than it sounds.

The only claim made in this directory is arithmetic reproduction. Any presentation of
this material as an external approval, accreditation, seal or third-party validation of
MODELA PRO would be false.

## 1. Retrieval

- **Retrieval date: 2026-09-11.**
- **Index page consulted:** <https://www.itl.nist.gov/div898/strd/lls/lls.shtml>
- **Data files:** `https://www.itl.nist.gov/div898/strd/lls/data/LINKS/DATA/<Name>.dat`
- **Catalogue identity** (read from <https://www.itl.nist.gov/div898/strd/>): StRD is
  *NIST Standard Reference Database 140*, DOI `http://dx.doi.org/10.18434/T43G6C`,
  last update to data content 2003.
- **Channel:** the eleven `.dat` files were retrieved with `curl` (HTTP 200 each) so the
  bytes are unmodified. The sha256 values below are of the raw fetched files, CRLF line
  endings included. `curl` was used deliberately in preference to a page-summarising
  fetcher: certified values must be transcribed byte-exactly, and any
  markdown-conversion or model-summarisation step in the path would put that at risk.
- **Vendored.** The eleven raw files are stored unmodified under `data/`. That is what
  makes the digests below mean anything: previously the only assertion involving them
  compared the string in `datasets.py` to the same string in this file, which is
  circular and cannot fail for any reason a reader cares about. Two tests now close
  that loop — one hashes the vendored bytes against the recorded digest, and one
  re-parses every certified value and every data point out of the vendored files and
  compares them to the literals in `datasets.py` with **exact float equality**.
  `data/.gitattributes` marks `*.dat` as binary (`-text`) so that no checkout
  normalises CRLF to LF and silently breaks the hashes.
- **Transcription:** `datasets.py` was generated mechanically from those raw bytes; no
  numeric value was typed from memory. NIST's `E-03` exponent notation is already valid
  Python float-literal syntax, so the literals can be diffed against the source files
  character by character — and now are, mechanically, by the re-parse test.
- **Self-validation of the parse:** for every dataset, `RegressionSS / (RegressionSS +
  ResidualSS)` taken from the certified ANOVA table reproduces the separately-parsed
  certified R² to within 3.4e-16. A mis-parse of either block would break this.

### sha256 of the raw fetched files (and of the vendored copies under `data/`)

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
also carries the same sha256 per dataset. Re-verify from outside the repo with:

```
curl -sS https://www.itl.nist.gov/div898/strd/lls/data/LINKS/DATA/Norris.dat | sha256sum
```

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

## 3. NIST's own statements, as actually read — all byte-verified

Everything in this section was fetched with `curl` on 2026-09-11 and read from the
returned bytes. An earlier revision of this file carried part of it at a lower
confidence level, flagged as "read through an automated fetch-and-summarise step, NOT
byte-verified". That caveat is now withdrawn because the fetches were redone with
`curl`; the wording below is what the pages actually serve.

- The eleven `.dat` files contain **no licence, no terms-of-use clause and no
  data-availability statement**. They carry only the dataset header, the certified
  values and the data.
- Neither <https://www.itl.nist.gov/div898/strd/lls/lls.shtml> nor
  <https://www.itl.nist.gov/div898/strd/general/dataarchive.html> carries any licence
  or terms-of-use statement of its own. Their entire text content is a dataset index
  and a navigation line respectively. This is a **negative finding**, recorded as such.
- From <https://www.itl.nist.gov/div898/strd/>, on the purpose of the project:
  > "The purpose of this project is to improve the accuracy of statistical software by
  > providing reference datasets with certified computational results that enable the
  > objective evaluation of statistical software."
- From <https://www.nist.gov/disclaimer>, on copyright status:
  > "With the exception of material marked as copyrighted, information presented on
  > NIST sites are considered public information and may be distributed or copied. Use
  > of appropriate byline/photo/image credits is requested."
- From the same page, the **general disclaimer** — which is the relevant text for any
  suggestion that StRD endorses a product:
  > "Any mention of commercial products within NIST web pages is for information only;
  > it does not imply recommendation or endorsement by NIST."
- From the same page, the **data disclaimer**:
  > "The National Institute of Standards and Technology (NIST) uses its best efforts to
  > deliver a high-quality copy of the Database and to verify that the data contained
  > therein have been selected on the basis of sound scientific judgment. However, NIST
  > makes no warranties to that effect, and NIST shall not be liable for any damage
  > that may result from errors or omissions in the Database."

**Basis for vendoring the raw files.** The material is not marked as copyrighted, it is
served from a NIST site, and NIST's site-wide text states such material "may be
distributed or copied" with appropriate credit. The credit is given: section 2 carries
NIST's own citations, and section 1 carries the retrieval URLs, the database DOI and the
byte digests. Nothing found in the retrieval path grants, implies, or could be read as
an endorsement of any third-party product, and nothing found restricts reproducing these
datasets for software testing. Anyone relying on this for a redistribution decision of
their own should re-read the NIST disclaimer directly rather than trust this summary.

## 4. The tolerance tiers, and which of them is pre-registered

There are three tiers. They are not equally authoritative and the difference matters,
so each is labelled everywhere it appears.

### 4.0 Tier 1 — pre-registered (frozen before any comparison was executed)

The floors in `datasets.py` were derived by a fixed rule and frozen **before** any
comparison against the oracle was executed. They were not chosen after seeing a result,
and nothing here may be loosened after seeing one.

The rule, per dataset:

```
kappa_eq      = cond_2(X with every column scaled to unit norm)
rho           = sqrt(certified residual SS) / (||X_eq||_2 * ||diag(colnorms) @ beta_cert||_2)
digits(A)     = max(0, 15 - log10(A))                  # 15 ~ decimal digits of a double
rel_floor(A)  = min(1.0, 10 ** -(digits(A) - 1))       # 1 digit of engineering margin

beta                    : A = kappa_eq + kappa_eq**2 * rho   (Higham, ASNA Thm 20.1)
residual sigma-hat, R^2 : A = kappa_eq        (the projection onto col(X) is far better
                                               determined than coordinates within it)
parameter std deviations: A = kappa_eq**2     (worst case, for an implementation that
                                               forms and inverts X'X — see tier 2)
```

Both inputs to the rule — the design matrix and `rho` — come from the fetched data and
NIST's certified values only. Neither depends on any oracle output, so computing them
first is pre-registration, not peeking. The equilibrated condition number is the quantity
that governs per-coefficient relative error; the raw condition number would be dominated
by mere column scaling (Pontius' `x²` column runs to ~1e13) and would hand easy datasets
a vacuous tolerance. As an external check that the quantity is the intended one: the
value computed here for Longley, `kappa_eq = 4.3275e4`, reproduces Belsley's published
scaled condition number for Longley (43275).

**The `min(1.0, ...)` clamp is part of the rule, and it was previously undocumented.**
Without it the expression returns `10**1 = 10` once `digits(A)` saturates at zero, and
"relative error at most 10" bounds nothing — a relative error of 1.0 already means not
one correct significant digit. Exactly one stored literal is produced by the clamp:
Filip's `sd_rel_floor`, where `A = kappa_eq² = 2.711e19` gives `1.000e+01` unclamped and
`1.000e+00` clamped. The stored literal has always been the clamped `1.000e+00`; what was
missing was the clamp in the written rule, which broke the "diff the rule against the
literals" auditability this directory advertises. It is now written down, and
`test_every_frozen_floor_reproduces_the_stated_rule` re-derives all **44** floors and
digit counts from `kappa_eq` and `rho` and fails on any literal that disagrees, so rule
and literals cannot drift apart again unnoticed.

Resulting tier-1 floors, all frozen in `datasets.py`:

| Dataset  | kappa_eq | rho | beta floor | sigma/R² floor | std-dev floor (kappa_eq²) |
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
| Filip    | 5.207e+09 | 3.33e-10 | 1.42e-04 | 5.21e-05 | **1.00 (vacuous)** |

### 4.0.1 Tier 2 — `sd_rel_floor_qr`, derived from the algorithm, NOT pre-registered

**A retraction first.** An earlier revision of this file and of the test docstring
stated that the rule "*predicts in advance* that Filip's parameter standard deviations
carry no reproducible significant digit in double precision". **That prediction is
retracted. It is empirically false.** The oracle reproduces Filip's certified parameter
standard deviations to **8.47 to 10.11 correct digits**:

| Filip sd | B0 | B1 | B2 | B3 | B4 | B5 | B6 | B7 | B8 | B9 | B10 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rel. error | 3.41e-9 | 3.28e-9 | 3.07e-9 | 2.76e-9 | 2.37e-9 | 1.90e-9 | 1.35e-9 | 7.42e-10 | 7.75e-11 | 6.31e-10 | 1.37e-9 |
| correct digits | 8.47 | 8.48 | 8.51 | 8.56 | 8.63 | 8.72 | 8.87 | 9.13 | 10.11 | 9.20 | 8.86 |

What the tier-1 rule actually produced was not a prediction about the oracle but a bound
so weak it clamped to 1.0. Presenting a vacuous bound as a measured limit is a
substantive error, and it had a behavioural consequence: eleven comparisons took a
branch that asserted only `isfinite(x) and x >= 0`. Eleven assertions that could not go
red, in a suite whose whole purpose is that assertions can go red, described in prose as
a documented limit. That is a skip, and it is fixed: the branch is gone, and
`_assert_within` now **refuses** any floor ≥ 1.0 outright instead of degrading to a
finiteness check.

**Why the kappa_eq² worst case is not attained here.** Not luck — structure.
`ols_oracle.fit_ols` never forms `X'X`. It computes a Householder QR of `X` and sets
`xtx_inv = R⁻¹R⁻ᵀ`, so `sd_j = sigma · ‖row_j(R⁻¹)‖₂`. Triangular inversion by
substitution is *componentwise* backward stable (Higham, *ASNA* 2nd ed., ch. 8 on
triangular systems: the computed solution of `Tx = b` satisfies `(T + ΔT)x̂ = b` with
`|ΔT| ≤ γ_n|T|`), which gives the componentwise forward bound
`|R̂⁻¹ − R⁻¹| ≲ γ_n |R⁻¹||R||R⁻¹|`. The squaring of the condition number is realised by
explicitly forming the cross-product matrix; this oracle does not. The attainable
amplification is therefore **one** factor of `kappa_eq`, so

```
sd_rel_floor_qr = min(1.0, 10 ** -(max(0, 15 - log10(kappa_eq)) - 1))
```

which is the same `A` as the projection class and so coincides numerically with
`proj_rel_floor` on every dataset. It is stored as a separate literal anyway, so the
re-derivation test checks it independently.

**The confirming signature is in the data, and it is componentwise.** This matters,
because applying a *normwise* argument coefficient-by-coefficient is exactly the error
section 4.1 retracts, and the same mistake must not be made inside its fix. The
prediction of a componentwise mechanism is that sd errors should be roughly flat across
`j`, where beta errors are not. Observed spread (max/min of the relative error across
coefficients):

| Dataset | sd spread | beta spread |
| --- | --- | --- |
| Pontius  |  1.3x |    931x |
| Longley  |  3.5x |    197x |
| Wampler5 |  3.9x |  20922x |
| Filip    | 44x (a dip at B8, not a decay in j) | 15x |

A `kappa_eq²` mechanism driven by column scaling would not look like that.

**It is not fitted to the observation.** Filip's worst sd error is 3.41e-09 against this
floor of 5.21e-05 — four orders of margin. A number chosen to fit would sit just above
3.41e-09. But it was derived *after* the first run, so it is **not pre-registered**, and
is never to be described as such.

The binding sd floor asserted by the test is `min(sd_rel_floor, sd_rel_floor_qr)`, which
is the tier-2 value on every dataset; the tier-1 literal is retained so the
re-derivation test can still check it and so a reader can confirm nothing was loosened.
**The tightest comparison in the entire suite is Norris `sd(B0)`: 1.752e-14 against
2.801e-14, 63% of budget.** If that ever trips, it is a finding to investigate — not a
literal to move.

### 4.0.2 Tier 3 — `EMPIRICAL_REGRESSION_CEILINGS`, measured, no authority at all

Measured on 2026-09-11, from this oracle, on one machine; multiplied by 100 and rounded
up to one significant figure. No theoretical standing whatsoever. Recorded only for the
datasets where the tier-1/tier-2 margin exceeds ~1e2 (Longley, Wampler1–5, Filip);
adding a literal where the derived floor already binds within two orders would be flake
surface without resolution. See section 4.3 for why they exist and `datasets.py` for the
full label. Never quote them as pre-registered, as certified, or as a NIST tolerance.

Certified-zero quantities (Wampler1 and Wampler2 have an exact fit: residual standard
deviation and all parameter standard deviations are certified `0.000000000000000`) cannot
be compared relatively. They use an absolute floor scaled to the data,
`ZERO_SIGMA_REL = 1e-9` times `rms(y)`. Justification, also pre-registered: with an exact
fit the computed residual is pure roundoff, bounded by roughly
`u * kappa_eq * ||y|| ≈ 2.2e-16 * 2.2e3` relative, i.e. ~5e-13 — so 1e-9 leaves more than
three orders of margin while remaining a real constraint.

## 4.1 A correction to the METRIC, with the floors left untouched

This must be on the record, because a reader has to be able to check that no tolerance
moved.

**v1, as pre-registered.** The tier-1 floors above, asserted against the *componentwise*
relative error `|beta_hat_j − beta_cert_j| / |beta_cert_j|` in *raw* coordinates.

**The run — corrected.** An earlier revision of this section stated: "Six of eleven
datasets failed. **Every single failure was on `B0`.** No other coefficient missed on any
dataset." The dataset count was right; **the coefficient claim was false**. The v1 metric
has been reconstructed and re-measured, and the true pattern is thirteen coefficient
failures across six datasets:

| Dataset | beta floor (v1 and v2 alike) | coefficients that missed | coefficients that passed |
| --- | --- | --- | --- |
| Norris   | 2.810e-14 | **B0** (8.196e-13) | B1 |
| Pontius  | 1.848e-13 | **B0** (4.039e-13) | B1, B2 |
| Wampler1 | 2.220e-11 | **B0** (3.401e-10), **B1** (1.292e-10) | B2…B5 |
| Wampler3 | 6.196e-11 | **B0** (7.042e-10), **B1** (5.505e-10), **B2** (1.658e-10) | B3…B5 |
| Wampler4 | 3.998e-09 | **B0** (1.191e-08), **B1** (2.122e-08), **B2** (7.384e-09) | B3…B5 |
| Wampler5 | 3.976e-07 | **B0** (1.146e-06), **B1** (2.113e-06), **B2** (7.395e-07) | B3…B5 |

NoInt1, NoInt2, Longley, Wampler2 and Filip missed nothing.

The false claim was load-bearing: the "exclusively-B0 signature" was the stated evidence
both for changing the metric and for rejecting the alternative `c(n,p)` hypothesis. Both
conclusions survive, but on the true premise, which is a **graded** pattern rather than a
single-coefficient one — and the graded pattern is the sharper fingerprint.

**The diagnosis.** The failure was in the pre-registration, not in the oracle. Higham
*ASNA* Thm 20.1 bounds a **normwise** relative error, and `kappa_eq` was computed for the
**column-equilibrated** matrix — so the bound governs
`‖D(beta_hat − beta_cert)‖ / ‖D·beta_cert‖`, not a raw componentwise ratio. The two
differ, per coefficient, by exactly

```
ratio_j = ‖D·beta_cert‖ / |D_jj · beta_cert_j|
```

and that ratio decays with `j` on these designs, which is why the misses decay with `j`
too. On the Wampler design the ratios run B0 = 1.07e6, B1 = 9.19e4, B2 = 5.79e3,
B3 = 3.35e2, B4 = 18.5, B5 = 1.00 — and the misses are B0, B0–B1, or B0–B2 depending on
how large the dataset's `rel_eq` is relative to its floor. Applying a normwise bound to a
componentwise metric is a derivation error in v1, and the ratio is the size of that
error.

**The structural claim, and it is asserted rather than merely written down.** On every
one of the eleven datasets, the set of v1 misses is exactly a **prefix** of the
coefficients ranked by `ratio_j` descending. Never once did a small-ratio coefficient
miss while a larger-ratio one passed. That is what
`test_v1_metric_failure_pattern_is_as_documented` asserts — the structure, not the exact
failure list, because Wampler1 B2 sits at 73% of its budget and a LAPACK difference could
flip it for no substantive reason. If the equilibration diagnosis were wrong, that test
goes red.

That Norris — the canonical *well-conditioned* set — was among the failures is decisive:
no defensible reading calls the oracle defective there.

**The `c(n,p)` hypothesis, rejected on the corrected data.** One hypothesis was
considered: adding a dimension-dependent backward-error constant `log10(n·p)` to the
margin. It would have covered the observed gaps numerically. It is rejected because
**Wampler2 has exactly the same n = 21, p = 6 and kappa_eq = 2220 as Wampler1, Wampler3,
Wampler4 and Wampler5, and missed nothing at all**, while Wampler5 missed three
coefficients. A factor depending only on `(n, p)` is identical across those five
datasets and cannot produce that. The same test asserts this premise, so it cannot
silently stop being true. Adopting `c(n,p)` would have been a textbook citation wrapped
around a number chosen to fit what had just been seen — which is exactly what these
floors exist to prevent.

**v2, as now asserted.** The floors are the **same literals, unchanged**. Only the metric
was corrected to the one the bound governs:

```
rel_eq  = ||D (beta_hat - beta_cert)||_2 / ||D beta_cert||_2   <=   beta_rel_floor
floor_j = beta_rel_floor * ratio_j                             (per coefficient)
```

## 4.2 Comparison against other implementations — with the method column labelled

Minimum correct digits across all coefficients, same data, same raw basis. This is a
recorded observation, not an assertion in the test suite: making a library comparison
load-bearing would require a slack constant chosen after seeing these numbers.

The previous version of this table had a single unlabelled "statsmodels" column. It was
the **default `pinv`/SVD path**, and presenting it unlabelled overstated the oracle's
standing. With `method='qr'` — the very method `ols_oracle.statsmodels_crosscheck()`
itself calls — statsmodels agrees with the oracle to the printed precision on all eleven
datasets, Filip included.

| Dataset | oracle (QR) | statsmodels `method='qr'` | statsmodels `pinv` (default) | numpy `lstsq` (SVD) | normal equations |
| --- | --- | --- | --- | --- | --- |
| Norris   | 12.09 | 12.09 | 12.77 | 12.85 | 11.82 |
| Pontius  | 12.39 | 12.39 |  6.24 |  6.24 | 11.53 |
| NoInt1   | 14.72 | 14.72 | 14.72 | 14.72 | 14.72 |
| NoInt2   | 15.12 | 15.12 | 15.12 | 15.21 | 15.34 |
| Longley  | 10.92 | 10.92 | 10.99 | 10.99 |  7.38 |
| Wampler1 |  9.47 |  9.47 |  9.55 |  9.78 |  6.25 |
| Wampler2 | 13.22 | 13.22 | 10.12 | 10.12 |  9.37 |
| Wampler3 |  9.15 |  9.15 |  9.40 |  9.02 |  6.25 |
| Wampler4 |  7.67 |  7.67 |  7.67 |  7.68 |  6.25 |
| Wampler5 |  5.68 |  5.68 |  5.67 |  5.68 |  6.25 |
| **Filip**|**8.55**|**8.55**| 0.00 | 0.00 | 0.00 |

The honest statement, and the only one this table supports: **the oracle's QR is at
parity with a reference QR everywhere, and ahead of the SVD/`pinv` path on Filip,
Pontius and Wampler2.** It is *not* better than statsmodels as such — it is the same
algorithm producing the same answer. What the table shows is a property of QR versus
SVD-with-default-`rcond` on rank-deficient-looking polynomial designs, not a property of
this repository. Any claim that the oracle "beats statsmodels" would be false.

## 4.3 How sharp is a pass? — the achieved-vs-floor margins, and the limitation

**The limitation, stated plainly.** The tier-1 floors are a worst-case bound. The oracle
beats them by factors of **1e2 to 5e7**. A suite asserting only tier 1 therefore verifies
that the arithmetic is **not catastrophically wrong** — it does *not* verify that the
oracle reproduces the certified digits. This was demonstrated, not assumed: corrupting
Longley's certified `B1` by 1e-6 relative passed every tier-1 assertion, and corrupting
Norris' certified `regression_ss` by 1e-9 relative passed as well.

Two things address that, and neither is a tightened tolerance:

1. **Literal corruption** is now caught at machine precision by the re-parse test
   (section 1), which compares every certified value and data point against the vendored
   NIST bytes with exact float equality. No accuracy floor can compete with that, and
   none needs to.
2. **Numerical regression in the oracle** is caught by the tier-3 empirical ceilings,
   which sit at 100× the measured error. The corrupted-Longley-`B1` case above moves
   `rel_eq` to ~3.1e-10 against a tier-3 ceiling of 6e-11, so it now goes red.

The full margin record, so the looseness is on the file:

| Dataset | quantity | achieved | tier-1 floor | tier-1 margin | binding tier | binding floor | binding margin |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Norris | beta (rel_eq) | 4.008e-15 | 2.810e-14 | 7x | pre-registered | 2.810e-14 | 7x |
| Norris | residual sd | 1.493e-14 | 2.801e-14 | 2x | pre-registered | 2.801e-14 | 2x |
| Norris | param sds (worst) | 1.752e-14 | 7.843e-14 | 4x | QR-structure | 2.801e-14 | **1.6x** |
| Pontius | beta (rel_eq) | 6.221e-16 | 1.848e-13 | 297x | pre-registered | 1.848e-13 | 297x |
| Pontius | residual sd | 8.191e-15 | 1.845e-13 | 23x | pre-registered | 1.845e-13 | 23x |
| Pontius | param sds (worst) | 9.009e-15 | 3.403e-12 | 378x | QR-structure | 1.845e-13 | 20x |
| NoInt1 | beta (rel_eq) | 1.927e-15 | 1.025e-14 | 5x | pre-registered | 1.025e-14 | 5x |
| NoInt1 | residual sd | 8.714e-16 | 1.000e-14 | 11x | pre-registered | 1.000e-14 | 11x |
| NoInt1 | param sds (worst) | 2.099e-16 | 1.000e-14 | 48x | QR-structure | 1.000e-14 | 48x |
| NoInt2 | beta (rel_eq) | 7.633e-16 | 1.082e-14 | 14x | pre-registered | 1.082e-14 | 14x |
| NoInt2 | residual sd | 6.013e-16 | 1.000e-14 | 17x | pre-registered | 1.000e-14 | 17x |
| NoInt2 | param sds (worst) | 1.154e-15 | 1.000e-14 | 9x | QR-structure | 1.000e-14 | 9x |
| Longley | beta (rel_eq) | 5.661e-13 | 7.603e-10 | 1343x | EMPIRICAL | 6.000e-11 | 106x |
| Longley | residual sd | 2.834e-13 | 4.328e-10 | 1527x | EMPIRICAL | 3.000e-11 | 106x |
| Longley | param sds (worst) | 3.704e-13 | 1.873e-05 | 5.1e7x | EMPIRICAL | 4.000e-11 | 108x |
| Wampler1 | beta (rel_eq) | 1.097e-14 | 2.220e-11 | 2024x | EMPIRICAL | 2.000e-12 | 182x |
| Wampler2 | beta (rel_eq) | 2.151e-14 | 2.220e-11 | 1032x | EMPIRICAL | 3.000e-12 | 139x |
| Wampler3 | beta (rel_eq) | 1.016e-13 | 6.196e-11 | 610x | EMPIRICAL | 2.000e-11 | 197x |
| Wampler3 | residual sd | 1.214e-14 | 2.220e-11 | 1829x | EMPIRICAL | 2.000e-12 | 165x |
| Wampler3 | param sds (worst) | 5.849e-14 | 4.929e-08 | 8.4e5x | EMPIRICAL | 6.000e-12 | 103x |
| Wampler4 | beta (rel_eq) | 4.339e-12 | 3.998e-09 | 921x | EMPIRICAL | 5.000e-10 | 115x |
| Wampler4 | residual sd | 1.356e-15 | 2.220e-11 | 1.6e4x | EMPIRICAL | 2.000e-13 | 147x |
| Wampler4 | param sds (worst) | 4.790e-14 | 4.929e-08 | 1.0e6x | EMPIRICAL | 5.000e-12 | 104x |
| Wampler5 | beta (rel_eq) | 4.341e-10 | 3.976e-07 | 916x | EMPIRICAL | 5.000e-08 | 115x |
| Wampler5 | residual sd | 1.578e-15 | 2.220e-11 | 1.4e4x | EMPIRICAL | 2.000e-13 | 127x |
| Wampler5 | param sds (worst) | 4.807e-14 | 4.929e-08 | 1.0e6x | EMPIRICAL | 5.000e-12 | 104x |
| Filip | beta (rel_eq) | 6.239e-10 | 1.424e-04 | 2.3e5x | EMPIRICAL | 7.000e-08 | 112x |
| Filip | residual sd | 1.183e-08 | 5.207e-05 | 4403x | EMPIRICAL | 2.000e-06 | 169x |
| Filip | param sds (worst) | 3.412e-09 | 1.000e+00 | 2.9e8x | EMPIRICAL | 4.000e-07 | 117x |

Wampler1 and Wampler2 fit exactly, so their residual sd, R² and parameter sds are
certified `0` / `1` and are compared on an absolute scale instead (section 4.0.2).

Read the table this way: where the binding tier is "pre-registered" or "QR-structure",
the pass is a genuine statement about numerical accuracy against a bound derived without
looking at the answer. Where it is "EMPIRICAL", the pass is only a statement that this
oracle still computes what it computed on 2026-09-11.

## 5. Files

- `data/` — the eleven raw NIST `.dat` files exactly as fetched, CRLF preserved, plus a
  `.gitattributes` marking them binary so no checkout normalises them. These are the
  bytes the sha256 values in section 1 refer to.
- `datasets.py` — data and certified values as plain Python literals, plus the frozen
  tolerance tiers. Imports nothing at all, and in particular nothing from `modules/`,
  `backend/` or `frontend/`.
- `tests/pro_workflow/p04/test_nist_strd.py` — compares the independent oracle
  (`tests/fixtures/pro_workflow/ols_oracle.py`) against the certified values under the
  floors above. It does not modify the oracle. Beyond the certified-value comparisons it
  asserts: the vendored bytes against the recorded digests; every certified literal
  against a fresh parse of those bytes; every frozen floor against the written rule;
  that no binding floor is vacuous; and that the v1 failure pattern in section 4.1 still
  has the structure the diagnosis claims.
