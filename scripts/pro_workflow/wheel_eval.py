#!/usr/bin/env python3
"""Build the committed wheel and evaluate one job outside the checkout.

No editable install. PYTHONPATH is empty in the evaluation process.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


EVAL_SCRIPT = r"""
import os, sys
from pathlib import Path
assert not os.environ.get("PYTHONPATH"), os.environ.get("PYTHONPATH")
import backend, modules
from backend.worker import compose_valuation_job, resolve_peers
from modules.evidence_bundle import MANIFEST_NAME, reproduce_from_bundle
from modules.job_store import JobStore

expected = 735000.0
csv = (
    "id;bairro;area;preco\n"
    + "\n".join(
        f"IM-{i:02d};Centro;{50+2*i:.2f};{(50+2*i)*10000:.2f}".replace(".", ",")
        for i in range(24)
    )
).encode()
spec = {
    "schema_version": "MP/1",
    "target_col": "preco",
    "candidate_cols": ["area"],
    "roles": {"preco": "target", "area": "predictor", "id": "identifier", "bairro": "excluded"},
    "units": {"area": "m2", "preco": ""},
    "import_options": {"locale": "pt-BR", "delimiter": ";", "encoding": "utf-8"},
    "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
    "outlier_policy": {"mode": "report_only", "reviewed_exclusions": []},
    "search_policy": {
        "mode": "exact", "budget": 16, "objective": "aic", "seed": 17,
        "y_transformations": ["identity"],
    },
    "evaluation_policy": {"method": "none", "partitions": None, "groups": None, "seed": 17},
    "reference_date": "2024-06-01",
    "inspection_date": "2024-06-15",
    "target_unit": "",
    "applicant": "p04-wheel-eval",
    "purpose": "install-eval",
}
root = Path(sys.argv[1])
store = JobStore(root)
rec = store.create(payload={"filename": "mercado.csv"})
ctx = compose_valuation_job(
    job_id=rec["job_id"],
    file_bytes=csv,
    filename="mercado.csv",
    request_spec=spec,
    subject_raw={"area": 73.5},
    project_id=None,
    peers=resolve_peers(),
    job_store=store,
)
snap = ctx["snapshot"]
point = snap["value"]["point"]
assert point is not None and abs(float(point) - expected) < 1.0, point
pdf = ctx["artifact_bytes"].get("report.pdf") or store.get_artifact(rec["job_id"], "report.pdf")
assert pdf and pdf[:4] == b"%PDF"
evidence = root / "jobs" / rec["job_id"] / "evidence"
assert (evidence / MANIFEST_NAME).is_file()
repro = reproduce_from_bundle(evidence)
assert repro.get("point") is not None
assert abs(float(repro["point"]) - expected) < 1.0, repro
integrity = (repro.get("integrity") or {}).get("ok")
assert integrity is True, repro
# P01 SEALED: dossier splits integrity vs interval reconstruction.
if repro.get("ok") is not True:
    limits = " ".join(repro.get("limitations") or [])
    assert "interval" in limits.lower() or "t_crit" in limits.lower(), repro
ver = backend.__version__ if hasattr(backend, "__version__") else "n/a"
print("wheel_eval_ok", point, repro.get("point"), backend.__file__, modules.__file__, ver)
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    log = args.output
    log.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="p04-wheel-") as tmp:
        tmp_path = Path(tmp)
        dist = tmp_path / "dist"
        dist.mkdir()
        build = subprocess.run(
            [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(dist)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        log.write_text(build.stdout + "\n" + build.stderr, encoding="utf-8")
        if build.returncode != 0:
            return build.returncode
        wheels = list(dist.glob("modelapro-*.whl"))
        if not wheels:
            log.write_text(log.read_text(encoding="utf-8") + "\nno wheel\n", encoding="utf-8")
            return 1
        venv_dir = tmp_path / "venv"
        venv.create(venv_dir, with_pip=True)
        python = venv_python(venv_dir)
        constraint = ROOT / "constraints" / "linux-py3.txt"
        install_cmd = [str(python), "-m", "pip", "install", str(wheels[0])]
        if constraint.is_file():
            install_cmd = [str(python), "-m", "pip", "install", "-c", str(constraint), str(wheels[0])]
        installed = subprocess.run(install_cmd, capture_output=True, text=True, check=False)
        with log.open("a", encoding="utf-8") as handle:
            handle.write("\n--- install ---\n")
            handle.write(installed.stdout)
            handle.write(installed.stderr)
        if installed.returncode != 0:
            return installed.returncode
        store = tmp_path / "store"
        store.mkdir()
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["MODELA_SKIP_DOTENV"] = "1"
        eval_path = tmp_path / "eval.py"
        eval_path.write_text(EVAL_SCRIPT, encoding="utf-8")
        ran = subprocess.run(
            [str(python), str(eval_path), str(store)],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        with log.open("a", encoding="utf-8") as handle:
            handle.write("\n--- eval ---\n")
            handle.write(ran.stdout)
            handle.write(ran.stderr)
            handle.write(f"\nwheel={wheels[0]}\n")
        return ran.returncode


if __name__ == "__main__":
    raise SystemExit(main())
