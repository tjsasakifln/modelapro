# C06 numerical verification — Pontius portability incident

Status recorded **before revalidation with the portable budget**: rule documented;
candidate validation pending.

## Retained failure evidence

GitHub Actions run `34670111908`, job `103489813101`, tested merge commit
`f537826a72c95381c53af32ccf2200c7e71d5cf5`. Its two numerical failures were:

| Quantity | NIST certified | GitHub runner | Relative error | Frozen floor |
| --- | ---: | ---: | ---: | ---: |
| Pontius residual sd | `0.000205177424076185` | `0.00020517742407622438` | `1.9194920734023983e-13` | `1.845e-13` |
| Pontius `sd(B0)` | `0.000107938612033077` | `0.00010793861203309784` | `1.930e-13` | `1.845e-13` |

The same NumPy 2.5.3 wheel produced a local residual-sd error of `8.1905e-15`.
Changing only `OPENBLAS_CORETYPE` among kernels executable on the local CPU moved it to
`5.0861e-14`; changing `OPENBLAS_NUM_THREADS` from 1 through 16 did not move it. This
supports a reduction/kernel-path effect. It does not identify the hosted runner's exact
CPU kernel because that run did not record it.

## Independent reference

A 100-digit Decimal solve formed normal equations from the decimal tokens in the
vendored NIST file. High precision makes the condition-number squaring harmless here
and keeps the implementation independent of NumPy, SciPy, BLAS and the QR oracle. For
Pontius it produced:

```
sigma = 0.000205177424076184630399300601028747858676446672357833272246...
relative error to published NIST sigma = 1.8013711842962498e-15
```

The three coefficient-standard-deviation errors were between `3.28e-16` and
`2.16e-15`. The NIST value is therefore preserved. The discrepancy is in the finite
precision path, and it is many orders too small to establish a monetary error.

## Error budget chosen before revalidation

The old `kappa_eq`-only floor omitted the conditioning of a small residual reconstructed
as `y - X beta`. The replacement comparison retains that historical floor and takes
the maximum with a uniform operation/conditioning budget:

```
u       = 2**-53
gamma   = (n*p*u) / (1 - n*p*u)
C_r     = (||y|| + ||X*beta_cert||) / sqrt(SSE_cert)
sigma   = gamma*(C_r + kappa_eq)   + half-ULP of the 15-digit decimal certificate
coef sd = gamma*(C_r + 2*kappa_eq) + half-ULP of the 15-digit decimal certificate
```

The terms and source links are recorded in
`tests/fixtures/pro_workflow/nist_strd/PROVENANCE.md` section 4.0.3. The formula uses no
observed Pontius output and has no dataset-specific fudge factor. It is evaluated for
all eleven StRD datasets. Certified-zero quantities retain their absolute checks.

Acceptance criteria for the subsequent validation are:

1. all source digests and certified literals remain unchanged;
2. the high-precision reconstruction agrees within the published reference resolution;
3. all QR comparisons pass the portable budget;
4. a deliberate 1% error in every applicable sigma/coefficient-sd comparison is still
   rejected;
5. the full `test_nist_strd.py` suite passes under the candidate environment.

## Subsequent local validation

The rule above was committed first as `6ec9dec`; only then were the comparisons changed
and executed. The independent command reported all eleven datasets passing at 100-digit
precision, with worst checked relative errors from `1.15e-15` through `4.50e-15` on the
non-exact datasets:

```
python3 scripts/comercial/numeric/verify_nist_high_precision.py
verified=11 precision=100 result=PASS
```

The focused suite then passed 96 tests, including the uniform budget derivation,
one-percent negative mutations and invocation of the Decimal checker from an arbitrary
working directory. A new candidate CI run is still required to turn the retained
GitHub-run failure into cross-platform execution evidence; local success is not recorded
as a hosted-run success.

## Fitted diagnostics added during C06 resumption

Commit `36c5208` added the fitted disclosures and eight initial tests. A separate
read-only review found three defects despite those passes: positional alignment
of the original correlation matrix, incomplete coverage of the influence union,
and omission of material diagnostics from C05's result fingerprint.

Commit `82166abba16d446ce10d260b603816c3b8652fd9` corrects these boundaries:

- Correlations join the frozen base frame to the effective row IDs. Missing,
  duplicate or canonically colliding IDs cannot produce a complete matrix.
- Influence counts require finite, exact maps for studentized residuals, Cook
  distance and leverage, their positive thresholds, and agreement with the
  recorded union. Missing or extra rows remain unavailable, with map-specific
  coverage evidence. An unverifiable union is never labelled verified.
- Statistical diagnostics participate in the reviewed result material. Removing
  any of the five diagnostic blocks invalidates the prior review in the real
  worker/C05 reassessment path. Snapshots without the added field retain their
  historical material shape; derived review/signature state is excluded to avoid
  a fingerprint cycle.

The two row/coverage regressions were reproduced before correction. The full
numeric disclosure file passed **11 tests** in the independent re-review; a final
coverage-metadata refinement passed its focused mutation test. These local checks
preserve the fitted coefficients, sample and normative grades. They do not approve
the final PDF/DOCX/XLSX or Windows artifact: those require the identified candidate
cohort in `integration-matrix.md`.

## Documentary consumption boundary — 2026-09-12

The output layer consumes the frozen numerical disclosures; it does not recompute them.
`test_real_worker_numeric_disclosure_reaches_verified_pdf_docx_xlsx_bytes` runs the real
BB worker and requires its `model.metrics`, p-values, correlation matrix, standardized
residuals, normal-frequency comparison, elasticities and outlier counts to reach verified
PDF, DOCX and XLSX bytes. It also compares the value block's arbitration bounds with the
verified bounds in `provenance.normative_assessment.intervals.arbitration_interval`.

Availability labels alone do not create documentary evidence. The manifest requires
finite metrics and complete producer coverage/status, while
`test_manifest_rejects_labels_missing_diagnostics_and_tampered_bytes` makes an unavailable
diagnostic and mutated representation fail. The real-worker test accounts for all 40 BB
output IDs: 28 pre-signature `emitted` representations must be present, the ICP-Brasil
signature remains an explicit post-review pending stage, and every one of the 11 human
requirements is present, pending or conditionally not applicable. These are local
documentary tests, not an additional numerical oracle, hosted-CI evidence or an
institutional acceptance claim.
