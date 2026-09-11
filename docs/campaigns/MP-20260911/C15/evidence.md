# C15 evidence — instalação reproduzível, configuração local e CI

Base auditada: `c92949e4db8c559c6b02ef58b7df90d6cf01e7ed`  
Branch: `mp-20260911/c15-instalacao_ci_local`  
Ambiente local: Linux, Python 3.12.3, pip 26.2.1, pytest 9.1.1

## Direct dependencies (validated set)

From a clean venv (`pip install -e ".[dev]"`), subset:

```
fastapi==0.141.1
Jinja2==3.1.6
matplotlib==3.11.1
numpy==2.5.3
openpyxl==3.1.5
pandas==3.0.5
psutil==7.2.2
python-dotenv==1.2.3
python-multipart==0.0.32
requests==2.34.2
scipy==1.18.1
seaborn==0.13.2
statsmodels==0.15.0
streamlit==1.63.0
uvicorn==0.52.4
weasyprint==70.0
websockets==16.1.1
xlrd==2.0.2
pytest==9.1.1
httpx==0.28.1
build==1.6.1
```

Full pin set: `constraints/linux-py3.txt` (Python 3.12.3). Update: `python -m c15_local.update_constraints`.

Previously undeclared but imported/required: `psutil` (monitor), `requests` (frontend HTTP), `openpyxl` (xlsx), `xlrd` (xls). Redis Python package moved to extra `modelapro[redis]`; a Redis **server** is not required. `modules/cache_manager.py` is unused at runtime.

## Commands (local Linux)

| command | exit |
| --- | ---: |
| `python -m flake8 --max-line-length=120 …` (owned paths) | 0 |
| `pytest tests/c15_packaging -q` (run 1) | 0 (33 passed, 1 skipped = install smoke flag off) |
| `pytest tests/c15_packaging -q` (run 2) | 0 |
| `C15_INSTALL_SMOKE=1 pytest tests/c15_packaging/test_wheel_install_smoke.py -q` (run 1) | 0 |
| same (run 2) | 0 |
| `python -m c15_local.launcher --check-pdf` | 0 |
| backend+frontend start ×2, GET `/health` | 0 (`{"status":"healthy"}` both times) |
| `pytest tests --ignore=tests/c15_packaging -q` (inherited baseline) | 0 (81 passed) |

The skipped test in the default C15 suite is `test_clean_venv_install_imports_resources_and_health`, gated on `C15_INSTALL_SMOKE=1` so CI/local cheap runs stay short. The dedicated smoke job and the two flagged runs exercise it.

## A01 — wheel/sdist + clean install

- `pip wheel . --no-deps` includes `backend/`, `modules/`, `frontend/`, `c15_local/`, `modules/templates/report.html`, `frontend/assets/styles.css`, entry point `c15_local.launcher:main` (not `frontend.app:main`).
- `python -m build --sdist` includes the same templates/CSS/launcher sources.
- Clean venv **outside** the checkout, `PYTHONPATH` unset, cwd not the repo: `import backend, modules, frontend, c15_local`; `importlib.resources` finds non-empty template and CSS under `site-packages`. Repeated twice.

## A02 — formats and PDF

- CSV: `pandas.read_csv` round-trip.
- `.xlsx`: `engine="openpyxl"` round-trip (direct dep).
- `.xls`: `engine="xlrd"` reads `tests/c15_packaging/fixtures/synthetic_market.xls` (synthetic, not client data).
- WeasyPrint probe on this Linux: rendered a real PDF (`%PDF`). Native libraries present. Warning: HarfBuzz-Subset will be required by a future WeasyPrint; not a current failure.
- `pip install weasyprint` is documented as insufficient on Windows/macOS without GTK/Pango/cairo. Probe message names those libraries and OS-specific install hints.

## A03 — launcher and bind

- Public commands: `modelapro`, `modelapro-api`, `modelapro-frontend`.
- Frontend is `python -m streamlit run <installed-or-checkout frontend/app.py> --server.address 127.0.0.1`.
- Two launches: `/health` → HTTP 200 `{"status":"healthy"}`; backend `--host 127.0.0.1`; frontend process cmdline contains `streamlit run`, not `frontend.app:main`.
- Config defaults: `API_HOST=127.0.0.1`, explicit CORS list, `REDIS_ENABLED=false`, C10/C11 keys (`DATA_DIR`, limits, concurrency, empty `LOCAL_AUTH_TOKEN`) validated.
- Logs: `RotatingFileHandler` + filter that drops client-payload extras.

**Handoff:** `backend/api.py` still hardcodes `allow_origins=["*"]` (C10). Bind host already uses `config.API_HOST`.

## A04 — tests / OS / CI

Oracle: GitHub Actions run on PR #13, SHA `b8941e6b3300896767e2882b8bf9b1c373281255`.

- PR workflow: https://github.com/tjsasakifln/modelapro/actions/runs/34597990388 — **conclusion=success**
- Push workflow (same SHA): https://github.com/tjsasakifln/modelapro/actions/runs/34597974163 — **conclusion=success**

| Job | OS | Conclusion |
| --- | --- | --- |
| Lint owned C15 paths | ubuntu-latest / Python 3.12 | success |
| C15 tests (Linux) | ubuntu-latest / Python 3.12 | success |
| Build sdist and wheel | ubuntu-latest / Python 3.12 | success |
| Clean venv install smoke (Linux) | ubuntu-latest / Python 3.12 | success (import + `/health` from installed wheel, `PYTHONPATH` unset) |
| C15 tests (Windows) | windows-latest / Python 3.12 | success (33 passed, 1 skipped; Linux lock applied) |
| Inherited suite baseline (recorded, not omitted) | ubuntu-latest / Python 3.12 | success (not omitted) |

Windows WeasyPrint `--check-pdf` exited non-zero with `OSError: cannot load library 'libgobject-2.0-0'` and the GTK/Pango hint. The step is `continue-on-error`; **Windows PDF is not claimed**.

| OS | Status |
| --- | --- |
| Linux / Python 3.12 | executed (local + CI) |
| Windows / Python 3.12 | executed (CI tests; PDF native missing as diagnosed) |
| macOS | **untested** (no runner) |
| Python 3.11 | declared `requires-python`, not matrixed (cost) |

## A05 — secrets and lock coherence

- `.env` gitignored; `.env.example` has empty `LOCAL_AUTH_TOKEN`, loopback hosts, `REDIS_ENABLED=false`.
- `uploads/`, `reports/`, `logs/`, `data/` gitignored.
- `setup.py` is a shim (`setup()` only). `requirements.txt` is `-c constraints/linux-py3.txt` + `.` — no second package list.
- `tests/c15_packaging/test_dependency_sync.py` fails if those diverge.

## Residual

- C09: `frontend/app.py` still does `from components.*`. `streamlit run` of the packaged `frontend/app.py` puts that directory on `sys.path`, so the import works after wheel install without editing C09.
- C08: PDF probe is in `c15_local.pdf_env.probe_weasyprint`; `results_generator.py` is not C15-owned.
- C03: `tests/test_nbr14653.py` still uses `grep` (not portable). C15 did not edit it.
- WeasyPrint future HarfBuzz-Subset requirement (deprecation warning only on this Linux).
