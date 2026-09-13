# MP-COM-20260912/C06 — Inventory of applicable requirements and covering tests

## Inventário da composição corrente

O mapeamento de requisitos é [integration-matrix.md](integration-matrix.md).
A lista exata de obrigações é `mandatory-test-nodeids.json`, gerada por
`python -m c15_local.test_inventory --write` no ambiente Linux com o lock dev.
`python -m c15_local.test_inventory` recoleta e compara a lista integral; o CI
executa a comparação antes da suíte e o agregador compara novamente com
`collection.json` e JUnit. Remoção, adição sem registro, troca com mesma contagem
e duplicação reprovam. Atualizações exigem revisão do diff versionado.
A coleta prova seleção, não execução: somente os artefatos da candidata
identificada na matriz podem demonstrar os resultados.

## Inventário histórico anterior à composição

As contagens, ausências, findings e HEAD abaixo são o registro histórico
medido em `c9ab4dc`; não descrevem o produto composto atual.


Item A of the C06 implementation. Read-only analysis of the worktree; no test was
modified to produce this document.

| | |
| --- | --- |
| Worktree | `/home/tjsasakifln/code/modela-pro-p04` |
| Branch | `mp-pro-20260911/p04-referencia-consolidacao` |
| HEAD | `c9ab4dcaa16a1c366441ae814bfa544032203fa8` |
| Measured (UTC) | 2026-09-12T02:35:14Z |
| Command | `PYTHONPATH= python3 -m pytest tests --collect-only -q` |

> **Correction notice (this revision).** The first revision of this document was
> stamped `65cb121` but described the CI workflow as it stood at `65cb121`'s
> **parent** `8d66c79`: tests were re-collected against the new HEAD, the workflow
> file was not re-read. That produced a false high-severity finding (FIND-04) and
> two false statements about `p04-harness`. Every claim below has been re-derived
> against `.github/workflows/c15-ci.yml`, `scripts/c15_local/aggregate_required.py`
> and `scripts/pro_workflow/run.py` **as they are at `c9ab4dc`**, and every cited
> line number and node id was re-verified. Findings that the tree has since fixed
> are marked **RESOLVED** with the commit that fixed them; none has been deleted.
>
> **This branch moves under the measurement.** HEAD advanced `8d66c79 → 65cb121 →
> a331606 → 815251f → be464a2 → d2efd11 → 10e7c1d → c9ab4dc` while these two
> documents were being written, by sibling C06 agents working in this same
> worktree. Every line number below is as of `c9ab4dc` **plus the working-tree
> modifications listed in §1**; each citation is given with enough surrounding
> text to be re-found by `grep -n` after it drifts.

> **There is no requirements document for this campaign in the repository.**
> `docs/comercial/` did not exist before this file. The eleven areas below are the
> ones named in the C06 task statement, not a matrix published in the repo. So
> "applicable requirement" here means *asserted by the campaign brief*, not
> *verified against a ratified scope*. This is finding **FIND-01**, not a footnote.

---

## 1. Collected total

**894 tests collected, 0 collection errors**, confirmed by two consecutive
collections whose node-id lists are byte-identical (`diff` empty) at the SHA and
timestamp above.

**894 is not reproducible from a SHA.** Of those 894, **846 come from tracked
files and 48 from two untracked files** —
`tests/pro_workflow/p04/test_mutations_commercial.py` (30) and
`tests/pro_workflow/p04/test_metamorphic_reference.py` (18) — which no commit
determines. Observed within one session while sibling C06 agents wrote to this
same worktree: **705 → 733 → 739 → 756 → 852 → 894**. The 705→733 delta was
confined by node-id diff to `tests/c15_packaging/test_workflow_triggers.py`; later
growth came from the two untracked files above plus
`tests/pro_workflow/p04/test_nist_strd.py` (94) and further cases in
`test_ci_aggregator.py` (45).

**How a downstream document may quote a total (FIND-06 remedy).** Quoting the SHA
does *not* make the number reproducible, because the SHA does not determine the
untracked files. Use one of these instead:

* quote the **tracked-file total** (`846` here) and say it is the tracked-file
  total — it is the only part a checkout of `c9ab4dc` can approach; or
* quote `894` **together with** the output of `git status --porcelain tests/`; or
* do not use a collected total as a headline number at all.

Even `846` is not exactly recomputable from a clean checkout. At measurement time
`git status --porcelain tests/` reported:

```
 M tests/fixtures/pro_workflow/nist_strd/datasets.py
 M tests/pro_workflow/p04/test_nist_strd.py
?? tests/pro_workflow/p04/test_metamorphic_reference.py
?? tests/pro_workflow/p04/test_mutations_commercial.py
```

Two of those are **tracked files modified in the working tree**, and they are the
file that contributes the most cases (94) and the fixture it parametrises off. That
status block, not a bare SHA, is this number's provenance.

Largest contributors at this snapshot: `tests/pro_workflow/p04/test_nist_strd.py` 94,
`tests/c15_packaging/test_ci_aggregator.py` 45, `tests/test_nbr14653.py` 39,
`tests/c01_input/test_ingest_market.py` 33,
`tests/pro_workflow/p04/test_mutations_commercial.py` 30,
`tests/acceptance/test_oracles_f01_f16.py` 21.

---

## 2. Every skip, xfail, gate and guard

Re-enumerated at `c9ab4dc` with
`grep -rn "pytest\.skip\|skipif\|xfail\|pytest\.importorskip" tests/ --include=*.py`:
the suite contains **no `xfail` marker anywhere** (the only `xfail` strings are
inside aggregator *fixtures* and assertions about skip/xfail counting) and exactly
**three** genuine skip sites — unchanged since the 705-case snapshot, despite the
tree growing to 894. The grep also surfaced one *soft pass* — a green result that records it did not run —
which no skip-oriented search can see structurally, and which is now the sharpest
item in this section.

| ID | Location | Kind | Condition | Class |
| --- | --- | --- | --- | --- |
| SKIP-01 | `tests/c15_packaging/test_wheel_install_smoke.py:20-23` | module `pytest.mark.skipif` | `C15_INSTALL_SMOKE` not in `{1,true,yes}` | (a) — was **(b)**, see below |
| SKIP-02 | `tests/c15_packaging/test_packaging_metadata.py:99` | in-body `pytest.skip` | `python -m build` not importable | (a) |
| SKIP-03 | `tests/c02_schema/test_c01_real_bundle.py:21,23` | in-body `pytest.skip` on `ImportError` / `None` | `modules.data_loader.ingest_market` unpublished / `None` | (a) |
| SOFT-01 | `tests/pro_workflow/p02/test_a01_playwright.py:81` (`_record_block` at `:67`) | **soft pass, not a marker** | playwright import fails, or no free port in 18200–18280 | **(b)** |
| GUARD-01 | `tests/c08_report/pdf_text.py:22-25` | conditional import | `pypdf` missing → `pdftotext` binary | (a) |
| GUARD-02 | `tests/acceptance/_helpers.py:43-48` (`try_export`), `:51-56` (`require_export`) | conditional import | product module missing → `None` | (a) |
| GUARD-03 | `tests/c17_integration/test_scenarios_a_j.py:604-607` | conditional import | `c15_local.launcher` → `scripts.c15_local.launcher` | (a) |

### SKIP-01 — was class (b); **RESOLVED at `be464a2`**

The first revision of this document recorded, truthfully at the time, that
`grep -rn C15_INSTALL_SMOKE .github/` returned **nothing**, that no CI job set the
variable, and that the module docstring named an `install-smoke` job which did not
exist. **That has since been fixed**, in `be464a2`: the
`install-eval-linux` job now carries a step *"Clean-venv wheel install smoke (boots
/health off the installed dist)"* with `env: C15_INSTALL_SMOKE: "1"` which runs
`pytest tests/c15_packaging/test_wheel_install_smoke.py`. The test builds a wheel,
installs it into a venv, boots `uvicorn backend.api:app` with **that venv's**
interpreter and asserts `wait_for_health(...)["status"] == "healthy"`
(`test_wheel_install_smoke.py:113-128`).

The skip therefore still fires in `wide-suite-linux` (which does not set the
variable) but no longer fires in every job, so the property is asserted somewhere:
class **(a)**. A regression test now pins this:
`tests/c15_packaging/test_workflow_triggers.py::test_install_smoke_flag_is_actually_set_by_a_job`
fails if any future edit removes the setter. The docstring's *"dedicated
install-smoke job"* is still inaccurate as a job **name** (the step lives inside
`install-eval-linux`), and `docs/campaigns/MP-20260911/INTEGRATION.md:122` records
the skip as *"coberto por `install-eval-linux`"* — which is now true, by a
mechanism that did not exist when that line was written.

### SKIP-02 / SKIP-03 — class (a)

SKIP-02 guards sdist content; `build` is a declared dev extra installed by every CI
job via `-e ".[dev]"`, so the skip cannot fire in CI, and its wheel twin
(`test_wheel_contains_packages_templates_css_and_entrypoint`) is ungated.

SKIP-03 is dormant: the module docstring says *"Skipped until C01 publishes
`ingest_market`… Not evidence of end-to-end integration"*, and the symbol **is**
published on this tree (`tests/c01_input/test_ingest_market.py` collects 33 cases
against it). It is honest about what it is not. The two `pytest.skip` calls are at
`:21` (on `ImportError`) and `:23` (on `ingest_market is None`).

### SOFT-01 — class (b), open

On browser unavailability, `test_a01_playwright_real_path_or_record_unavailability`
writes a JSON log with `"status": "BLOCKED"`, asserts the log file exists, and
`return`s — **green**. Its two siblings covering the same property fail honestly:

* `tests/pro_workflow/p04/test_browser_composed.py:57` → `AssertionError("NOT_RUN:…")`
* `tests/acceptance/test_e2e_ui.py:70` → `AssertionError("NOT_RUN:…")`

Because it is neither `skip` nor `xfail`, it is invisible to skip reporting and to
the aggregator's own skip/xfail check
(`tests/c15_packaging/test_ci_aggregator.py::test_skip_xfail_is_caught`, at `:233`).
Its `SCRATCH` default is also a hardcoded foreign path,
`/tmp/grok-goal-7164525daca4/implementer` (line 19). *Mitigation:*
`wide-suite-linux` installs Playwright Chromium, so the real path is expected to run
there — the defect is that a green suite result cannot prove it did.

### A note on `os.name == "posix"`

`tests/c17_integration/test_scenarios_a_j.py:621` asserts `os.name == "posix"`,
which would fail on Windows. Class (a): no CI job runs `tests/c17_integration` on
Windows, and `docs/campaigns/MP-PRO-20260911/OVERVIEW.md:4` explicitly does not
announce Windows readiness (*"Não é … Windows PDF nem piloto humano de mercado"*).

---

## 3. Requirement areas → covering tests

Verdicts are **COVERED / PARTIAL / ABSENT**. ABSENT is written where nothing
exists; it is never softened to PARTIAL.

The task named **11** areas; this table has **14** rows. Two areas are split
deliberately, because one verdict would flatten opposite findings —
*PDF/DOCX generation* → PDF (COVERED) + DOCX (ABSENT), and
*backup and recovery* → recovery (COVERED) + backup (ABSENT). In
`test_inventory.json` every entry carries a `requested_area` field naming the
task's original label, so the 14 rows map back onto the 11 requested areas.

Every node id below was verified to collect with
`PYTHONPATH= python3 -m pytest "<nodeid>" --collect-only -q`; class-based tests are
written with their class segment, because a two-segment id collects zero.

| Area | Verdict | Evidence |
| --- | --- | --- |
| Calculation boundaries | **COVERED** | Thresholds probed on both sides (`c03_normative/test_a02_frontiers.py` ×10, `test_nbr14653.py::TestItem6SignificanciaGlobal::test_classifier_boundaries`, `test_nbr14653.py::TestItem2QuantidadeDados::test_formula_boundaries`); transform input domains and round-trips enumerated (`c06_transformations/test_a01_x_domains.py` ×18, `test_a02_roundtrip.py` ×9); extrapolation exercised at the exact limit (`test_nbr14653.py::TestFinalizePrecisionAndExtrapolation::test_extrapolation_admitida_uma_variavel_com_valor_na_fronteira`). |
| Statistical hypotheses | **COVERED** | Worst-p-value rule with the constant excluded (`test_nbr14653.py::TestItem5SignificanciaRegressores::test_worst_pvalue_determines_grade_not_average_or_best`, `test_nbr14653.py::TestItem5SignificanciaRegressores::test_worst_pvalue_fails_even_if_average_would_pass`, `test_nbr14653.py::TestItem5SignificanciaRegressores::test_const_excluded_from_worst_pvalue`); intervals, rank-deficiency and Cook influence cross-checked against `tests/fixtures/pro_workflow/ols_oracle.py` (numpy/scipy only), whose independence is itself asserted by `pro_workflow/p04/test_oracle_independence.py` ×8. |
| Qualification profile (fundamentação / precisão) | **COVERED** | Points total and per-item minimum tested separately — a passing total with a failing required item downgrades (`test_nbr14653.py::TestClassifyFundamentacao::test_points_enough_but_required_item_downgrades_from_iii_to_ii`); precision ranges in `test_nbr14653.py::TestFinalizePrecisionAndExtrapolation::test_grau_precisao_ranges`; the contract rule that the effective grade comes from `validation.fundamentacao` and never from the request is asserted in `p01/test_a03_grade_aliases.py` ×4 and `p02/test_request_grade_method.py` ×5. |
| UI | **PARTIAL** | Presenter, request-spec and layout states covered at unit/AppTest level (`c09_frontend/*` 35 cases, `p02/test_presenter_and_delivery.py` ×9, `p02/test_invalidation_and_binding.py` ×8). Real-browser coverage exists and fails honestly in `acceptance/test_e2e_ui.py` and `p04/test_browser_composed.py`, but SOFT-01 can report green without driving a browser — so end-to-end UI cannot be asserted from a green suite alone. |
| PDF generation | **COVERED** | Bytes asserted to start with `%PDF` and extracted text matched field-by-field against snapshot numbers (`c08_report/*` 13 cases, `p03/test_a01_pdf_fields.py` ×3, `p03/test_a02_integral_annex.py`, `p03/test_a03_formula_series.py` ×6, `acceptance/test_e2e_pdf.py` ×2), on Linux with the native pango/cairo stack installed by CI. **Linux only** — Windows PDF is not claimed and the Windows `--check-pdf` step is `continue-on-error`. |
| DOCX generation | **ABSENT** | `NONE`. grep for `docx` / `python-docx` / `Document(` across `tests/`, `modules/`, `backend/`, `frontend/` and `pyproject.toml` returns **no hit**. There is no DOCX feature — unimplemented, not merely untested. |
| Digital signature | **ABSENT** | `NONE`. grep for `assinatura` / `signature` / `sign_pdf` / `ICP-Brasil` / `pyhanko` / `endesive` matches **only** `inspect.signature()` reflection (`modules/local_task_runner.py:28`, `backend/api.py:527`, `tests/c14_batch/test_public_api.py:12`, `tests/acceptance/test_oracles_f01_f16.py:234`). No signing, no certificate handling, no verification. |
| Dossier / evidence bundle | **COVERED** | Manifest hash integrity (`c12_evidence/test_a02_integrity_manifest.py` ×2), CSV-injection safety of exported cells (`test_a04_csv_safety.py` ×4), and an end-to-end `reproduce_from_bundle` landing within tolerance of the original point (`test_a03_reproduction.py` ×6, `p01/test_a05_dossier.py` ×5) — repeated from the *installed wheel* by the `install-eval-linux` job. |
| Recovery (crash / restart durability) | **COVERED** | Torn write does not corrupt the prior snapshot (`c11_persistence/test_a05_durability_security.py::TestDurabilityAndSafety::test_truncated_write_does_not_corrupt_existing_snapshot`); an abandoned running job becomes `interrupted` rather than silently succeeded (`c11_persistence/test_a02_restart_and_abandoned.py::TestRestartAndAbandoned::test_abandoned_running_becomes_interrupted_without_fabricating_success`); store queryable from a fresh process with no websocket (`test_fresh_process.py::test_fresh_process_public_api`, `test_a01_queryable_without_ws.py` ×4). |
| Backup (user-facing backup / export / restore-from-backup) | **ABSENT** | `NONE`. There is no backup command, no archive/export of the data directory, no restore-from-backup path — therefore no test. The `modules/job_store.py`, `project_store.py`, `evidence_bundle.py` grep hits are durable-store and state-restore code, already counted under *Recovery*. **Do not read the Recovery verdict as backup coverage.** |
| Installer | **PARTIAL** | Real and verified: wheel/sdist contents and package data (`c15_packaging/test_packaging_metadata.py` ×5), dependency-to-import sync and pinning (`test_dependency_sync.py` ×8), launcher commands and loopback health (`test_launcher_command.py` ×4), a clean-venv install that computes a value and emits a PDF (`install-eval-linux`), and — since `be464a2` — that same job booting `/health` off the installed wheel (`test_wheel_install_smoke.py::test_clean_venv_install_imports_resources_and_health`). Missing: **no end-user installer artefact** — no `.exe`/`.msi`/`.pkg`/`.deb`, only a wheel plus `scripts/c15_local/launcher.py`. |
| Update | **ABSENT** | `NONE`. grep for `updater` / `auto_update` / `update_check` / `atualização` across `tests/`, `modules/`, `backend/`, `scripts/` returns nothing. `scripts/c15_local/update_constraints.py` is a **developer** tool that regenerates `constraints/linux-py3.txt` — it is not a product update channel and must not be counted as coverage. No version-check endpoint, no migration-on-upgrade, no upgrade test. |
| Licences | **ABSENT** | `NONE`. No `LICENSE` file at the repo root; `pyproject.toml` declares no `license` field and no `License ::` classifier; no third-party licence inventory, no `NOTICE`, no product licence-key or entitlement mechanism. grep for `licen[cs]` across `tests/`, `modules/`, `backend/` returns no hit. Nothing is covered because nothing exists. |
| Security | **PARTIAL** | The *local single-user* threat model is covered concretely: loopback-only bind and non-`*` CORS (`c15_packaging/test_config_defaults.py` ×9 in the file, of which `test_config_defaults.py::test_default_bind_is_loopback_not_all_interfaces`, `test_config_defaults.py::test_default_cors_is_explicit_localhost_not_star`, `test_config_defaults.py::test_star_cors_is_rejected` carry this property), ws token + per-job payload isolation (`c11_persistence/test_a04_ws_isolation.py::TestWebsocketIsolation::test_real_ws_route_requires_local_token_and_isolates_jobs`, `c11_persistence/test_a04_ws_isolation.py::TestWebsocketIsolation::test_wrong_token_is_rejected`, `c11_persistence/test_a04_ws_isolation.py::TestWebsocketIsolation::test_two_jobs_never_see_each_others_payloads`), path traversal rejected (`c11_persistence/test_a05_durability_security.py::TestDurabilityAndSafety::test_path_traversal_is_rejected`, `c11_persistence/test_c10_callsite_adapters.py::TestC10CallsiteAdapters::test_save_and_get_artifact_rejects_traversal`), no pickle deserialization, CSV formula injection (`c12_evidence/test_a04_csv_safety.py` ×4), no secrets in defaults (`test_no_secrets.py` ×2), PII stripped from logs (`test_logging.py` ×2), plus `c10_pipeline/test_a05_security_peers.py` ×8 and `c17_integration/test_r17_hardening.py` ×9. **Not covered:** multi-user authn/authz and transport encryption (arguably out of matrix for a local install), and — not out of matrix — **no dependency-vulnerability or SBOM/licence scan anywhere in CI**. |

---

## 4. Env-gated optional tests, and whether another job runs the property

### OPT-01 — `C15_INSTALL_SMOKE` → **RESOLVED at `be464a2`** (was FIND-03)

`tests/c15_packaging/test_wheel_install_smoke.py::test_clean_venv_install_imports_resources_and_health`
asserts, in one test: `pip wheel` builds; the wheel installs into a clean venv under
`constraints/linux-py3.txt`; `backend`/`modules`/`frontend`/`c15_local` import from
`site-packages`; `report.html` and `styles.css` resolve as package data;
`frontend_command` is the Streamlit CLI; **and `uvicorn backend.api:app` boots from
the installed wheel and `/health` returns `status=healthy`**.

`install-eval-linux`'s *inline evaluation script* covers the first five — clean
venv, constrained install, `site-packages` imports, package-data-backed PDF,
evidence bundle and `reproduce_from_bundle` — and never starts a server. **At the
document's previous SHA that was the whole job, and the `/health`-from-the-wheel
property was asserted by no CI job.** At `be464a2` the same job gained a prior step
that sets `C15_INSTALL_SMOKE: "1"` and runs the gated test, so the composite
property *"the thing we ship serves `/health`"* is now asserted in CI.

The residual observation stands and is worth keeping: every *other* health boot in
the tree runs against the **editable checkout**
(`tests/c15_packaging/test_launcher_command.py:95`,
`tests/c17_integration/test_r17_hardening.py:218`,
`tests/acceptance/test_e2e_ui.py:117`,
`tests/pro_workflow/p04/test_browser_composed.py:105`) or in-process via the
FastAPI `TestClient` (`tests/test_api.py:15`,
`tests/acceptance/test_e2e_http.py:23`). The gated test remains the **only** test
that boots a server from a non-editable installed distribution, so removing its CI
setter would silently remove the property again — which is exactly what
`test_workflow_triggers.py::test_install_smoke_flag_is_actually_set_by_a_job` now
prevents.

### OPT-02 — `P04_REQUIRE_EXTENSIONS` → **RESOLVED at `65cb121`** (was FIND-04)

`tests/pro_workflow/p04/test_candidate_extensions.py` is **never skipped** —
`wide-suite-linux` runs `pytest tests`, so it executes. With the variable unset, a
missing extension is written to `finding_*.json` and **the case still passes**
(`test_candidate_extensions.py:15`).

No *workflow step* sets `P04_REQUIRE_EXTENSIONS` directly, and the first revision of
this document concluded from that alone that the strict run never happens. **That
conclusion was wrong.** `scripts/pro_workflow/run.py:124-127` sets
`P04_REQUIRE_EXTENSIONS=1` in the child environment whenever `--mode
accept-candidate` is used, and since `65cb121` the `p04-harness` job runs exactly
`python scripts/pro_workflow/run.py --mode accept-candidate`. The strict extensions
suite therefore runs in CI, is recorded in `run.json` as a run named `extensions`
(`run.py:172-191`), and the aggregator fails the build if it is missing
(`aggregate_required.py:154-156`) or if the recorded mode is not `accept-candidate`
(`:130-132`).

Overlapping strict coverage also exists for the canonical grade field
(`p01/test_a03_grade_aliases.py`, `p02/test_request_grade_method.py`). Verdict:
**equivalence now established — resolved.**

### OPT-03 / OPT-04 — destination-only, not findings

`C17_UI_EVIDENCE` and `C16_UI_SCREENSHOT` (`acceptance/test_e2e_ui.py`) and
`P02_SCRATCH` (`p02/test_a01_playwright.py`) select where artefacts are written.
They gate no assertion; when unset, `test_e2e_ui.py` still drives Chromium and still
raises `NOT_RUN` on failure. `wide-suite-linux` sets `C17_UI_EVIDENCE`. (The
`P02_SCRATCH` *default value* is a separate defect — see SOFT-01.)

---

## 5. What each CI job actually runs

From `.github/workflows/c15-ci.yml` **as read at `c9ab4dc`**.

| Job | Actually runs | pytest suites | Required by the gate |
| --- | --- | --- | --- |
| `lint` | flake8 over an enumerated file list (C15/P04-owned paths only) | — | yes |
| `c15-tests-linux` | `pytest tests/c15_packaging -q` + junit | `tests/c15_packaging` | yes |
| `build-sdist-wheel` | `python -m build` | — | yes |
| `install-eval-linux` | wheel into a venv outside the checkout; then `C15_INSTALL_SMOKE=1 pytest tests/c15_packaging/test_wheel_install_smoke.py --junitxml=artifacts/install-smoke.junit.xml` (boots `/health` off the installed dist; since `d2efd11` this step installs only `pytest`, deliberately **not** `-e ".[dev]"`, so the job's contract stays the installed distribution); then an **inline script**: compose job → point ≈ 735000 → `%PDF` → evidence manifest → `reproduce_from_bundle` with `integrity.ok` | `tests/c15_packaging/test_wheel_install_smoke.py` | yes |
| `c15-tests-windows` | `pytest tests/c15_packaging -q`, then `launcher --check-pdf` with `continue-on-error` | `tests/c15_packaging` | **yes** (since `be464a2`) |
| `wide-suite-linux` | `pytest tests -q` — **the entire `tests/` tree**, with Chromium installed and `C17_UI_EVIDENCE` set | `tests` (all) | yes |
| `c16-harness` | `scripts/c16_acceptance/run_harness.py` | — | yes |
| `p04-harness` | `scripts/pro_workflow/run.py --mode accept-candidate` (which exports `P04_REQUIRE_EXTENSIONS=1`), then `measure.py --phase before`, then a guard step re-reading `run.json` and failing unless `mode == accept-candidate` and `exit_code == 0` | — | yes |
| `acceptance` | `aggregate_required.py --required-jobs … --results-json … --artifacts-dir evidence --expected-sha "$CANDIDATE_SHA" --min-wide-tests 800 --p04-mode accept-candidate` | — | (is the gate) |

Because `wide-suite-linux` runs the whole tree and `install-eval-linux` now runs the
`C15_INSTALL_SMOKE`-gated module, **no area-relevant test is left unexecuted by
every job**. That is a change from this document's previous revision, where
SKIP-01 / OPT-01 was exactly such a test.

`c15-tests-windows` **is** in the aggregator's `--required-jobs` list at `c9ab4dc`,
so a Windows failure does now make the build red (FIND-08 RESOLVED). It is pinned by
`tests/c15_packaging/test_workflow_triggers.py::test_windows_blocks_the_gate`. This
still does not amount to a Windows readiness claim: `--check-pdf` remains
`continue-on-error` and `OVERVIEW.md:4` does not announce Windows PDF.

### The gate checks job conclusions **and** the evidence

`scripts/c15_local/aggregate_required.py` contains `verify_artifacts()` (`:235`),
which reads the run/junit artefacts and fails when the P04 run artifact lacks a
**strict** `extensions` suite (`:154-156`), when the recorded mode is not
`accept-candidate` (`:130-132`), when the SHA is stale (`:170-173`), when a junit
is absent, unparseable, short or red (`check_junit` at `:178-207`), or when the
run artifact records skips/xfails or failure findings (`:158-159`, `:165-168`).
`tests/c15_packaging/test_ci_aggregator.py` asserts all of that
(`::test_missing_strict_extensions_suite_is_caught` at `:220`,
`::test_diagnostic_mode_cannot_accept_the_candidate` at `:182`,
`::test_skip_xfail_is_caught` at `:233`,
`::test_main_is_red_when_all_jobs_are_green_but_evidence_records_failure` at `:327`).

**Skips are treated asymmetrically, and deliberately so.** `check_junit`'s
`forbid_skips` defaults to `True`, but `verify_artifacts` passes
`forbid_skips=False` for `wide.junit.xml` (`:248`) and `forbid_skips=True` for
`install-smoke.junit.xml` (`:254`). That is the correct pairing at this SHA:
`wide-suite-linux` does not set `C15_INSTALL_SMOKE`, so its junit necessarily
carries one skipped case (SKIP-01) and a strict check there would make the gate and
the workflow mutually unsatisfiable; whereas `install-smoke.junit.xml` is produced
by the job that *does* set the flag, so a skip there means the flag was dropped and
must be red. Had `wide.junit.xml` been checked with the default, the gate would be
unsatisfiable — worth stating, because it was, briefly, between `be464a2` and
`d2efd11`.

`verify_artifacts()` runs only when `--artifacts-dir` is passed — `main()` is at
`:260` and the branch at `:287`. **At `c9ab4dc` the `acceptance` job does pass it**,
together with `--expected-sha`, `--min-wide-tests 800` and
`--p04-mode accept-candidate`, after downloading every evidence artifact into
`evidence/`. So the evidence-verification half of the gate **does** execute in CI.
`tests/c15_packaging/test_workflow_triggers.py::test_aggregator_opens_the_evidence_not_only_the_job_results`
and `tests/c15_packaging/test_workflow_triggers.py::test_p04_harness_job_accepts_the_candidate_strictly` keep it that way.

---

## 6. Findings

`Status` is **OPEN** unless a commit on this branch has since fixed the defect.
Resolved findings are retained, not deleted: they record a real negative that was
found and closed.

| ID | Sev | Status | Finding |
| --- | --- | --- | --- |
| FIND-01 | high | OPEN | **No requirements matrix exists for MP-COM-20260912/C06.** `docs/comercial/` did not exist before this file. The eleven areas come from the task statement; nothing in the repo declares which are obligatory. Coverage here is coverage against an unratified list. |
| FIND-02 | high | OPEN | **Digital signature, DOCX, licences and product update are entirely absent from the product** — no implementation, hence no test. ABSENT, not PARTIAL. |
| FIND-03 | high | **RESOLVED in `be464a2`** | **`C15_INSTALL_SMOKE` was set by no CI job**, so the installed-artefact `/health` property was asserted nowhere; the docstring named a job that did not exist, and `INTEGRATION.md:122` credited `install-eval-linux`, which then never started a server. `be464a2` added a `C15_INSTALL_SMOKE: "1"` step to `install-eval-linux` that runs the gated module, and a regression guard (`test_workflow_triggers.py::test_install_smoke_flag_is_actually_set_by_a_job`). |
| FIND-04 | high | **RESOLVED in `65cb121`** | **The aggregator's evidence verification, including the strict P04 extensions run, did not execute in CI.** Independently rediscovered here; it is the original R20-A defect, and it had already been fixed in `65cb121` — three minutes before this document's first measurement, which is why the first revision reported it as open against a stale reading of the workflow. At `c9ab4dc` the `acceptance` job passes `--artifacts-dir evidence --expected-sha … --min-wide-tests 800 --p04-mode accept-candidate`, and `p04-harness` runs `--mode accept-candidate`, which exports `P04_REQUIRE_EXTENSIONS=1` (`run.py:124-125`). A missing P01/P02/P03 extension on the composed candidate **does** now turn the build red. Guarded by `test_workflow_triggers.py::test_aggregator_opens_the_evidence_not_only_the_job_results` and `tests/c15_packaging/test_workflow_triggers.py::test_p04_harness_job_accepts_the_candidate_strictly`. |
| FIND-05 | med | OPEN | **`p02/test_a01_playwright.py` reports green when the browser flow did not run** (writes a `BLOCKED` log and returns), unlike its two `NOT_RUN`-raising siblings. Invisible to skip/xfail reporting. Hardcoded foreign `SCRATCH` default (`:19`). |
| FIND-06 | med | OPEN | **The collected total is not reproducible.** 705 → 733 → 739 → 756 → 852 in one session while sibling agents wrote to the worktree. 894 confirmed by two byte-identical collections at `c9ab4dc`, but **48 of the 894 come from two untracked files**, and the two largest contributing tracked files were modified in the working tree, so no SHA determines the number. Quoting the SHA alongside the total — this document's previous remedy — does **not** work. Quote the tracked-file total (846 here) labelled as such, or quote 894 together with `git status --porcelain tests/`, or do not headline a collected total at all. |
| FIND-07 | med | OPEN | **No dependency-vulnerability or supply-chain gate.** No pip-audit, safety, SBOM or licence scan in `c15-ci.yml`. Pins are verified to match imports but never checked against a vulnerability database, and dependency licences are never recorded. With FIND-02's missing `LICENSE`, the release's supply-chain posture is unverified. **Cross-reference:** the sibling C06 deliverable `docs/comercial/c06/security_supply_chain.md` reaches the same conclusion independently (its BLOCKED items **B1** and **B2**: `pip-audit`/`safety` absent from every interpreter and from `PATH`, no SBOM generator installed) and adds a concrete obligation (**F2**: `xlrd` 2.0.2 is `BSD-3-Clause AND BSD-4-Clause`, whose BSD-4-Clause portion requires an attribution acknowledgment in redistributions) — which reinforces *licences = ABSENT* here, since the repo ships no `LICENSE` and no third-party notices file to carry it. Consolidation should treat FIND-07 and that document's B1/B2/F2 as **one** finding. |
| FIND-08 | low | **RESOLVED in `be464a2`** | **`c15-tests-windows` could not block the gate** (absent from `--required-jobs`). It is present at `be464a2` and still at `c9ab4dc`, pinned by `test_workflow_triggers.py::test_windows_blocks_the_gate`. Note this makes the Windows *packaging tests* blocking; it is still not a Windows readiness claim, since `--check-pdf` is `continue-on-error` and `OVERVIEW.md:4` excludes Windows PDF. |
| FIND-09 | low | OPEN | **Lint covers only C15/P04-owned paths.** `modules/`, `backend/`, `frontend/` at large are not linted; a green `lint` job does not mean "the codebase lints". |

---

## 7. What this document does not claim

* It does **not** claim the suite passes. Only collection was run; no test was executed.
* It does **not** claim any external certification, approval or conformity assessment.
  NBR 14653-2 coverage above refers to tests the repo contains, not to any assessment
  by ABNT or any other body.
* It does **not** claim any GitHub Actions run was observed. The CI statements above
  are read from `.github/workflows/c15-ci.yml` at `c9ab4dc` — what the workflow
  *instructs*, not what a run *did*. The workflow's own comment cites GitHub run
  `34667257642`; this document did **not** open that run and makes no claim about it.
* It does **not** claim Windows readiness, and it does not claim the product has been
  validated in the hands of a human appraiser.
* Where an area is marked ABSENT, no compensating coverage was found and none is implied.
