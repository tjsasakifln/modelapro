# C12 local reproduction

Verify integrity and reconstruct the original-unit prediction from a package
written by `modules.evidence_bundle.build_evidence_bundle`.

```bash
python scripts/c12_reproduce/reproduce.py --bundle PATH/TO/PACKAGE
python scripts/c12_reproduce/reproduce.py --bundle PATH/TO/PACKAGE --verify-only
```

The command reads JSON/CSV as data only. It does not `pickle.loads`, `eval`,
`exec`, or import files from the bundle. Tolerance and determinism are printed
in the JSON report. A one-byte change in any listed file fails integrity
(exit 2). A legacy model without integral coefficients fails with a documented
gap (exit 3) instead of echoing a memorized snapshot value.
