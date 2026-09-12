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
