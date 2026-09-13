# P04 workflow scripts

Independent corpus, measurement, PR discovery, and wheel evaluation.

```text
python scripts/pro_workflow/run.py --mode diagnose-base --output DIR
python scripts/pro_workflow/run.py --mode accept-candidate --output DIR
python scripts/pro_workflow/discover_prs.py --output DIR/composition_matrix.json
python scripts/pro_workflow/measure.py --phase before --sha SHA --output DIR/metrics-before.json --run-json DIR/run.json
python scripts/pro_workflow/wheel_eval.py --output DIR/wheel-eval.log
```

`diagnose-base` vs `accept-candidate` is an output-directory and
`P04_REQUIRE_EXTENSIONS` split. It is not skip/xfail. Core tests always
run. Extension tests always execute the real job; only the assertion
strictness changes.

Resume after producer HEADs are SEALED:

```text
git fetch origin
python scripts/pro_workflow/discover_prs.py --output docs/campaigns/MP-PRO-20260911/P04/composition_matrix.json
# merge SEALED HEADs onto mp-pro-20260911/p04-referencia-consolidacao (P01 → P03 → P02)
python scripts/pro_workflow/run.py --mode accept-candidate --output DIR
```
