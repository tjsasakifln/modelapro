> **⚠️ DEFEITOS PROVADOS E ABERTOS NESTE DOCUMENTO.** A verificação
> adversarial provou defeitos aqui que **não** foram corrigidos (remediação
> interrompida por limite de sessão). Não leia este arquivo como verificado.
> Lista exata: `docs/comercial/c06/defeitos_abertos_nos_documentos.md`.

---

# MODELA PRO — Supply chain, secrets hygiene and CI security posture

**Campaign:** MP-COM-20260912/C06 — aceite C06-A07
**Worktree inspected:** `/home/tjsasakifln/code/modela-pro-p04`
**Branch / commit shipping this document:** `mp-pro-20260911/p04-referencia-consolidacao` @ `be464a2`
(`git rev-parse --abbrev-ref HEAD` / `git rev-parse --short HEAD`, re-run when this revision was written)
**Commit at which the evidence below was first gathered:** `a331606`, a verified ancestor of `be464a2`
(`git merge-base --is-ancestor a331606 HEAD` exits 0). Nothing cited in this document moved between the two;
the header is re-stamped so it names the commit that ships the document rather than a stale one.
**Date of inspection:** 2026-09-11
**Companion machine-readable manifest:** [`reuse.json`](./reuse.json)

Every statement below is traceable to a command recorded in this document or to a
file path with a line number. Nothing is asserted from memory. Where evidence was
unobtainable, the item is marked **BLOCKED** and no substitute claim is made.

---

## 0. What this document is not

This is a **factual record of an internal inspection**. It is not:

- a certification, accreditation or approval by any body;
- a legal opinion on licence compliance;
- a penetration test, a formal security audit, or a vulnerability scan result;
- a claim that any CVE is or is not present in this dependency set.

Section 6 explains, specifically, that **adopting NIST SSDF recommendations is not a
certification** of any kind.

---

## 1. Dependency surface and pinning

| Artefact | Role |
| --- | --- |
| `pyproject.toml` `[project.dependencies]` | canonical direct **runtime** ranges (18 packages) |
| `pyproject.toml` `[project.optional-dependencies]` | `redis` extra (1) and `dev` extra (10) |
| `constraints/linux-py3.txt` | the pin set — a `pip freeze` of a clean venv, header records `python: 3.12.3`; **93 pins**, of which **26 are direct** and **67 transitive** |
| `requirements.txt` / `requirements-dev.txt` | thin installers: `-c constraints/linux-py3.txt` plus `.` / `.[dev]` — they carry **no** second package list |
| `setup.py` | 4-line `setuptools` shim, declares no metadata |
| `MANIFEST.in` | sdist contents; notably `global-exclude .env`, `prune docs/normas`, `prune uploads`, `prune reports` |

Divergence between `requirements*.txt` and `pyproject.toml` is guarded by
`tests/c15_packaging/test_dependency_sync.py` (referenced from the header comment of
`requirements.txt` and from `constraints/README.md`).

**Licence determination.** Licences for every direct dependency were read from real
installed distributions, not from memory or from PyPI web pages. The authoritative
environment used was `/home/tjsasakifln/.cache/modelapro-c15-dev/bin/python3`
(Python 3.12.3), a pre-existing virtualenv whose installed versions match
`constraints/linux-py3.txt` **exactly** for every package examined — including the
three that the ambient system interpreter disagreed on (`numpy` 2.5.3 vs 2.5.2,
`setuptools` 84.0.0 vs 68.1.2, `wheel` 0.48.0 vs 0.42.0). **Nothing was installed,
upgraded or removed.**

```bash
V=/home/tjsasakifln/.cache/modelapro-c15-dev
$V/bin/python3 -c "import importlib.metadata as m; md=m.metadata('pandas'); \
  print(m.version('pandas'), md.get('License-Expression'), md.get_all('Classifier'))"
# locating the licence file — RECURSIVELY, never a top-level `ls`:
find $V/lib/python3.12/site-packages/pandas-3.0.5.dist-info -iname '*licen*'
# and, where no PEP 639 License-Expression exists:
head -40 $V/lib/python3.12/site-packages/pandas-3.0.5.dist-info/LICENSE
```

**Correction to an earlier revision of this deliverable.** `reuse.json` previously asserted,
for `wheel` and for `setuptools`, that the `dist-info` carried *no separate LICENSE file*.
Both files exist:

```bash
find $V/lib/python3.12/site-packages/wheel-0.48.0.dist-info      -iname '*licen*'
#   .../wheel-0.48.0.dist-info/licenses/LICENSE.txt        → opens "MIT License"
find $V/lib/python3.12/site-packages/setuptools-84.0.0.dist-info -iname '*licen*'
#   .../setuptools-84.0.0.dist-info/licenses/LICENSE       → the MIT grant text
```

The cause was a top-level `ls` on those two `dist-info` directories instead of recursing into
the PEP 639 `licenses/` subdirectory — which *was* checked correctly for `jinja2`, `weasyprint`,
`httpx`, `requests` and `python-dotenv`. The SPDX conclusion (MIT) is unaffected and is in fact
now *corroborated* by those files rather than resting on the metadata field alone. It is recorded
here rather than quietly patched because this document's warrant is that every statement is
traceable to a file: a cited primary source that does not exist is precisely the defect class the
warrant claims immunity from. Every other absence claim was re-checked by running the recursive
`find` above across all 26 locked direct dependencies. Two survive, both now sourced from that
find: `scipy-1.18.1.dist-info` has no `licenses/` subdirectory (`LICENSE.txt` only — it does ship
`sboms/auditwheel.cdx.json`, a CycloneDX SBOM naming `libquadmath` and `libgfortran`, but with no
`licenses` field on any component, so the native licences remain undetermined), and
`streamlit-1.63.0.dist-info` ships no licence file at any depth, which is why the `streamlit`
entry rests on its `License-Expression` field and asserts nothing about a licence file.

**Three licences were read from the ambient interpreter, not the lock.** `redis` (8.1.0),
`pypdf` (6.16.1) and `playwright` (1.62.0) are absent from `constraints/linux-py3.txt`, so they
are not installed in the locked venv; their licences were read from `/usr/bin/python3` at
whatever versions it carries. **Those three determinations are not tied to a shipped, locked
version** — the version CI or a user resolves may differ, and no licence is asserted for it. The
other 26 direct dependencies were all read from the locked venv at exactly the pinned version.

A Trove classifier such as `License :: OSI Approved :: BSD License` was **not** treated
as determinative — it does not separate BSD-2-Clause from BSD-3-Clause — so the
`dist-info` licence text was read and the SPDX id derived from the clause structure.
Full per-package results, with the evidence for each, are in `reuse.json`.

### Two licence facts that matter commercially

1. **`xlrd` (2.0.2, direct runtime) is dual-licensed `BSD-3-Clause AND BSD-4-Clause`.**
   `xlrd-2.0.2.dist-info/LICENSE` states "There are two licenses associated with xlrd".
   The earlier David Giffin portion has a **fourth clause**: *"Redistributions of any
   form whatsoever must retain the following acknowledgment: 'This product includes
   software developed by David Giffin <david@giffin.org>.'"* BSD-4-Clause carries an
   attribution obligation BSD-3-Clause does not. A commercial distribution that ships
   or requires `xlrd` should carry that acknowledgment in its third-party notices.
   Flagged here for legal review; not resolved here. `xlrd` is reached only by the
   legacy `.xls` import path (`modules/import_formats.py:270`).

2. **`numpy`'s licence is a compound expression**, `BSD-3-Clause AND 0BSD AND MIT AND
   Zlib AND CC0-1.0`, because numpy bundles code under several licences. It is recorded
   verbatim in `reuse.json` rather than collapsed to "BSD".

`matplotlib` is a third nuance: its `LICENSE` is a **bespoke agreement** ("License
agreement for matplotlib versions 1.3.0 and later") between the Matplotlib Development
Team and the licensee. It is PSF-derived in structure but is not the PSF-2.0 text, so
no SPDX id is asserted; `reuse.json` records `LicenseRef-Matplotlib-1.3.0-or-later`
and cites the file.

### Vendoring: none

`reuse.json` records `"decision": "dependency_only, no vendored fragments"` with an
empty `vendored[]`. That is an evidenced claim, not an assumption. The one file where
vendoring would have been tempting — the independent OLS oracle used to validate the
product's regression path — was checked directly:

```bash
grep -niE "copyright|licen|adapted from|based on|taken from|SPDX|derived" \
  tests/fixtures/pro_workflow/ols_oracle.py          # exit status 1 — no match
grep -nE "^\s*(import|from) " tests/fixtures/pro_workflow/ols_oracle.py
```

377 lines, no third-party copyright header or attribution marker of any kind. The second command
above gives the **complete** import set, re-derived for this revision: `from __future__ import
annotations` (line 9), `math` (11), `typing` (12), `numpy` (14) and `scipy.stats` (15) at module
level, plus exactly **three** function-local imports — `pandas` (246) and `statsmodels.api` (247)
inside an optional library cross-check, and the standard-library `re` (348) inside `parse_number`.
An earlier revision listed only the first two function-local imports while reading as exhaustive;
the omitted `re` is standard library and does not change the conclusion. It is a first-party
reimplementation. `tests/pro_workflow/p04/test_oracle_independence.py`
enforces the independence mechanically: it AST-parses the oracle source and asserts
that no imported name starts with `modules.`, `backend.` or `frontend.`.

### Scope limit

`reuse.json` covers the **29 direct** dependencies — 18 runtime, 1 `redis` extra, 10 `dev` extra.
`constraints/linux-py3.txt` is a different artefact with a different count: **93 pins**, of which
**26 pin a direct dependency** (the 18 runtime plus 8 of the 10 dev — `redis`, `pypdf` and
`playwright` are absent from the lock) and the remaining **67 are transitive** distributions
(`altair`, `pyarrow`, `protobuf`, `pillow`, `pydantic`, `starlette`, `brotli`, `zopfli`,
`tinycss2`, …). The two numbers count different things and are never interchangeable here:
**29 = direct dependencies declared; 26 = direct dependencies the lock pins; 67 = transitive pins;
93 = total pins.**

```bash
grep -cE '==' constraints/linux-py3.txt                       # 93
# names normalised per PEP 503 and matched against the pyproject lists:
#   total pins: 93 | direct declared: 29 | direct pinned: 26
#   absent: ['redis', 'pypdf', 'playwright'] | transitive: 67
```

An earlier revision said "roughly eighty" transitive distributions with no cited command; that
figure was wrong. Those 67 transitive pins were **not** individually licence-reviewed for this
deliverable. Doing that properly needs an SBOM generator, which is not installed — see BLOCKED
below.

---

## 2. Vulnerability scanning — **BLOCKED**

No vulnerability check was performed, because no scanner is available and the campaign
rules forbid installing one.

```bash
python3 -m pip_audit --help      # /usr/bin/python3: No module named pip_audit
python3 -m safety   --help       # /usr/bin/python3: No module named safety
which pip-audit safety cyclonedx-py syft   # (no output — none on PATH)
/home/tjsasakifln/.cache/modelapro-c15-dev/bin/python3 -m pip_audit --help  # No module named pip_audit
/home/tjsasakifln/.cache/modelapro-c15-dev/bin/python3 -m safety   --help  # No module named safety
```

**Exact requirement to unblock:** install `pip-audit` into the project venv and run

```bash
pip-audit -r constraints/linux-py3.txt --strict --format json -o artifacts/pip-audit.json
```

`pip-audit` also needs network access to the PyPI JSON API / OSV. An SBOM (for the
transitive licence gap in §1) would need `cyclonedx-py` or `syft` on the same terms.

**No CVE result is claimed, simulated or inferred in this document.** The absence of
findings here is the absence of a scan, not a clean bill of health. Until that command
has been run and its output archived, "MODELA PRO has no known vulnerable dependencies"
is a statement nobody in this campaign is entitled to make.

---

## 3. Secrets hygiene

### 3.1 Scan performed

Run at `a331606` (`mp-pro-20260911/p04-referencia-consolidacao`) in the inspected worktree, over **tracked files only**
(that commit is an ancestor of the shipping commit `be464a2`; see the header)
(`git grep` searches the working tree of tracked paths; it does **not** search git
history — see the limitation in §3.4).

```bash
git grep -nIE "(AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[baprs]-\
|ghp_[A-Za-z0-9]{20,}|github_pat_|sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,})"
# exit status 1 — no match

git grep -nIE "(password|secret|api_key|apikey|token|credential)[[:space:]]*[:=]\
[[:space:]]*[\"'][^\"']{8,}[\"']" -- '*.py' '*.yml' '*.yaml' '*.toml' '*.json'
# exit status 1 — no match

git grep -n "secrets\." .github/
# exit status 1 — no workflow consumes any GitHub Actions secret

git ls-files | grep -iE "(^|/)\.env"
# .env.example   (only)
```

**Result: no committed credential of any recognised shape was found in tracked files
at HEAD.** No secret value is reproduced in this document, and none needed to be —
there was nothing to redact.

### 3.2 `.env` handling

- `.gitignore` ignores `.env` and `.env.*`, with an explicit `!.env.example` negation,
  and additionally ignores `*.pem`, `*.key`, `id_rsa*`, `credentials.json`,
  `secrets.json`, plus `data/`, `logs/`, `uploads/*`, `reports/*`.
- `MANIFEST.in` carries `global-exclude .env`, so a real `.env` cannot leak into an
  sdist even if one exists in the build tree.
- `.env.example` ships **no secret values**. It states so in its own header:
  *"Copy to .env (never commit .env). No secrets are shipped. Leave `LOCAL_AUTH_TOKEN`
  empty for unauthenticated local use."* Every value in it is a local default
  (`API_HOST=127.0.0.1`, `REDIS_ENABLED=false`, `LOG_LEVEL=INFO`, …).
- CI sets `MODELA_SKIP_DOTENV: "1"` at the workflow level, so no dotenv file is read in
  CI at all.

### 3.3 Token and binding validation

`modules/config_manager.py` refuses weak configuration rather than silently accepting it:

- `_validate_local_token` (line 104) raises `ValueError` if `LOCAL_AUTH_TOKEN` is set
  but is a known placeholder or shorter than 8 characters; empty is the supported
  single-user loopback mode. Its message ends *"Do not commit the token."*
- `LOCAL_AUTH_TOKEN` defaults to `""` (line 138) and is read from the environment,
  stripped, at line 260 — it is never a literal in the source.
- Loopback binding is the default (`API_HOST=127.0.0.1`, `FRONTEND_HOST=127.0.0.1`),
  with `_display_host` mapping unsafe bind hosts back to `127.0.0.1` for display, and
  `.env.example` records that `CORS_ORIGINS` rejects `"*"` at config validation.
- Sensitive payloads are redacted before they reach persisted output:
  `modules/provenance.py:315-321` replaces datasets and raw bytes with
  `"<redacted: dataset not logged>"` / a sha256 prefix, and
  `modules/results_generator.py:303` (`_redact_mapping`) is applied to the evidence
  block (line 445) and to `provenance_safe` (line 1151).

### 3.4 Limitations of this scan

- **Tracked files at HEAD only.** Git history was not scanned. A credential committed
  and later removed would not appear. Detecting that needs a history scanner
  (`gitleaks detect --log-opts=--all`, `trufflehog git file://.`), none of which is
  installed — same BLOCKED condition as §2.
- Regex-based detection finds credentials of **recognised shapes**. A high-entropy
  string in an unrecognised format would not be caught.

---

## 4. CI permissions and workflow trust model

Source: `.github/workflows/c15-ci.yml` (385 lines; it is the **only** file in
`.github/workflows/`, confirmed by `ls .github/workflows/`).

### 4.1 Token permissions — least privilege, and it is real

```yaml
permissions:
  contents: read
```

Declared once at workflow level (line 17-18). `git grep -n "permissions:"` over
`.github/` returns that single occurrence, so **no job widens it** — every one of the
nine jobs (`lint`, `c15-tests-linux`, `build-sdist-wheel`, `install-eval-linux`,
`c15-tests-windows`, `wide-suite-linux`, `c16-harness`, `p04-harness`, `acceptance`)
runs with a read-only `GITHUB_TOKEN`. No job can push a commit, open or edit a PR,
write a package, or create a release.

### 4.2 `pull_request_target` — not used

```bash
git grep -n 'pull_request_target' .github/workflows/    # exit status 1 — no match
```

Triggers are `push` (to an explicit branch allow-list), `pull_request` (to `main` and
two integration branches) and `workflow_dispatch`. The dangerous pattern —
`pull_request_target` checking out fork head code while holding write permissions and
secrets — **is absent**.

### 4.3 Untrusted-input interpolation — one `github.event` use, and it is safe

```bash
git grep -n 'github\.event' .github/workflows/
# .github/workflows/c15-ci.yml:377:  CANDIDATE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}
```

That is the only `github.event.*` reference in the repository, and it is safe on two
counts: the value is a **commit SHA** (40 hex characters chosen by git, not free text an
attacker writes), and it is passed through an `env:` block and referenced in the shell
as `"$CANDIDATE_SHA"` — the recommended pattern — rather than being interpolated
directly into the script body. There is **no** interpolation of a PR title, branch
name, body, or comment anywhere in the workflow.

### 4.4 Observations recorded as present-and-trusted, not as defects

- **`${{ toJSON(needs) }}` is interpolated inline** into a `run:` shell at line 380,
  quoted in single quotes and passed as `--results-json`. Its source is the Actions
  `needs` context (job names and result strings produced by the runner), not
  attacker-controlled content, so it is not an injection vector. It is noted because it
  is the one place where `${{ }}` reaches a shell command line directly.
- **Actions are pinned to mutable major tags**, not commit SHAs:
  `actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v4`,
  `actions/download-artifact@v4`. This is GitHub's own common practice and these are
  first-party actions, but tag pinning means the executed code can change under a
  fixed reference. Pinning to full commit SHAs is the hardening step if the commercial
  release requires a fully immutable build.
- **`sudo apt-get install`** of the WeasyPrint native stack runs in four jobs against
  the Ubuntu runner's default repositories, unpinned by version. The versions installed
  therefore drift with the runner image.
- **No secret is consumed** by any job (§3.1), so a compromised third-party action in
  this workflow would find no credential to exfiltrate beyond the read-only token.
- **The `acceptance` job is a real gate, not a rubber stamp.** It runs with
  `if: always()`, downloads every evidence artifact, and calls
  `scripts/c15_local/aggregate_required.py` with `--required-jobs` naming all seven
  mandatory jobs plus `--expected-sha`, `--min-wide-tests 700` and
  `--p04-mode accept-candidate`, so a job that is skipped or whose uploaded evidence
  disagrees with its green status fails the aggregate. The `p04-harness` job contains a
  further inline guard that fails if `run.json` reports a mode or exit code
  inconsistent with a green step.

---

## 5. Network and telemetry posture

### 5.1 Does the product phone home by default? No third-party endpoint was found.

```bash
git grep -lnE "requests\.(get|post)|urlopen|httpx\.(get|post|Client)|socket\.connect" -- '*.py'
# frontend/components/forms.py
# scripts/c15_local/launcher.py
# (the remaining five hits are all under tests/)
```

Both non-test hits target the **local API on loopback**:

- `frontend/components/forms.py:46` — `DEFAULT_API_URL = os.environ.get("MODELA_API_URL", "http://127.0.0.1:8000")`, used to build the `httpx.Client` at line 746.
- `scripts/c15_local/launcher.py` — `urllib.request.urlopen` against `health_url()`, which is `public_url + "/health"`, and `.env.example` sets `API_PUBLIC_URL=http://127.0.0.1:8000`.

Narrowing to the non-UI packages,
`git grep -nE "requests\.(get|post|put)|urlopen|httpx\.|urllib\.request" -- 'modules/*.py' 'backend/*.py'`
returns **no match at all** — the analysis, reporting and persistence modules make no
outbound calls whatsoever. (That narrowed command deliberately excludes `frontend/`,
whose single client is the loopback API call already disclosed above; note also that
git pathspecs do not expand `**` without `:(glob)`, so a `frontend/**/*.py` pattern
would silently match nothing.) No analytics, crash-reporting or licence-check endpoint
was found anywhere in the shipped packages.

### 5.2 Streamlit usage statistics — off on the supported launch path, default elsewhere

```bash
git grep -rn "gatherUsageStats" -- .
# scripts/c15_local/launcher.py:69
# tests/acceptance/test_e2e_ui.py:109
# tests/pro_workflow/p02/test_a01_playwright.py:128
# tests/pro_workflow/p04/test_browser_composed.py:97
```

`frontend_command()` in `scripts/c15_local/launcher.py` builds the Streamlit
invocation with `--browser.gatherUsageStats false` and `--server.headless true`, so the
**supported** entry points (`modelapro`, `modelapro-frontend`) disable Streamlit's
upstream usage statistics.

**Precise scope:** there is no tracked `.streamlit/config.toml` (`git ls-files | grep -i
streamlit` matches no config file). A user who bypasses the launcher and runs
`streamlit run frontend/app.py` directly therefore gets **Streamlit's upstream default**
for `browser.gatherUsageStats`, which is outside this project's control. If the
commercial release needs telemetry off unconditionally, the fix is a committed
`.streamlit/config.toml` with `[browser] gatherUsageStats = false`, not a claim in a
document.

### 5.3 Data residency

Uploads, jobs, projects, reports and logs are written to local paths configured in
`.env.example` (`DATA_DIR=./data`, `UPLOAD_DIR=./uploads`, `REPORTS_DIR=./reports`,
`LOG_DIR=./logs`), all of which `.gitignore` excludes from version control and
`MANIFEST.in` prunes from the sdist. Redis is optional and `REDIS_ENABLED=false` by
default. **No evidence of market data, valuation inputs or generated reports leaving
the machine was found.**

---

## 6. NIST SSDF — adoption is **not** a certification

Several practices above line up with recommendations in NIST SP 800-218, the Secure
Software Development Framework: a canonical declared dependency set with a recorded
lock (PS.3 / PW.4), automated verification in CI with an evidence aggregator (PW.7,
PW.8), least-privilege build permissions (PO.5), and secrets kept out of version
control (PO.5, PW.9).

**Stating that is a self-assessment and nothing more.** NIST does not certify, approve,
accredit or endorse software, organisations or products against the SSDF, and no such
assessment has been requested or performed for MODELA PRO. Nothing in this document may
be presented to a client, a regulator or a tender as "NIST certified", "NIST compliant",
"SSDF certified" or any equivalent. The same applies to every other body named anywhere
in this repository: no external audit, certification or approval has taken place.

---

## 7. Findings and open items

Severity is this document's own judgement about impact on the commercial release, not
an external rating.

| # | Severity | Finding | Evidence |
| --- | --- | --- | --- |
| F1 | **Medium — packaging defect** | `httpx` is imported unconditionally at module scope by shipped code, but is declared **only** in the `dev` extra. A non-dev install (`pip install modelapro`) that reaches this module raises `ModuleNotFoundError`. | `frontend/components/forms.py:19` `import httpx`; `frontend.components` is listed in `[tool.setuptools] packages`; `httpx>=0.26.0` appears only under `[project.optional-dependencies].dev`. CI's `install-eval-linux` job does not catch it because it imports only `backend` and `modules`. Fix is either to move `httpx` into `[project.dependencies]` or to make the import lazy. |
| F2 | **Medium — licence obligation** | `xlrd` is `BSD-3-Clause AND BSD-4-Clause`; the BSD-4-Clause portion requires an attribution acknowledgment in "redistributions of any form whatsoever". | `xlrd-2.0.2.dist-info/LICENSE`, clauses 3 and 4 of the David Giffin portion. Needs a third-party notices entry before commercial distribution. |
| F3 | **Low — lock incompleteness** | `constraints/linux-py3.txt` claims (in `constraints/README.md`) to be a full freeze of `pip install ".[dev]"`, but `pypdf` and `playwright` — both declared in the `dev` extra — are **absent** from it. `grep -inE "pypdf\|playwright" constraints/linux-py3.txt` matches nothing — so the lock pins 26 of the 29 declared direct dependencies, not all of them. CI's `pip install -c constraints/linux-py3.txt -e ".[dev]"` therefore resolves both **unconstrained**, so the test-tool versions drift. Not a build failure (a constraints file does not force installation), but the lock is not the complete freeze its README describes. |
| F4 | **Informational** | `requests` is declared as a direct runtime dependency, but no shipped module imports it (`git grep -E '^\s*(import\|from) requests\b' -- backend/ modules/ frontend/ scripts/` → no match). It remains installed transitively via `streamlit`. Recorded as declared-but-not-directly-imported; whether to drop the declaration is a packaging decision, not a C06 one. |
| F5 | **Informational** | `scikit-learn` 1.9.0 is present in the ambient system interpreter but is **not** declared in `pyproject.toml` and **not** in the lock. The single repository hit, `modules/result_contract.py:271`, is a `module.startswith("sklearn")` string test, not an import. Ambient-only; no action. |
| B1 | **BLOCKED** | No vulnerability scan. `pip-audit` and `safety` are both absent from every inspected interpreter and from `PATH`; installing them is out of scope for this campaign. Unblock: `pip-audit -r constraints/linux-py3.txt --strict --format json -o artifacts/pip-audit.json`. |
| B2 | **BLOCKED** | No transitive licence review (the **67** pinned indirect distributions of §1) and no git-history secret scan. Both need tooling that is not installed: an SBOM generator (`cyclonedx-py`, `syft`) and a history scanner (`gitleaks`, `trufflehog`). |

### Hardening suggestions (not defects)

1. Pin GitHub Actions to full commit SHAs rather than `@v4` / `@v5` major tags.
2. Commit a `.streamlit/config.toml` with `[browser] gatherUsageStats = false` so the
   setting does not depend on the launcher being used (§5.2).
3. Add `pip-audit` to the `dev` extra and a non-blocking CI job, so a scan result
   becomes archived evidence instead of a BLOCKED item.
