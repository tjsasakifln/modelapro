"""Synthetic fixtures for P01. Labeled as synthetic; not market accuracy evidence."""

from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import pytest

from backend.api import bind_runtime, reset_runtime
from modules.job_store import JobStore
from modules.local_task_runner import LocalTaskRunner
from modules.project_store import ProjectStore
from modules.websocket_notifier import WebSocketNotifier

SYNTHETIC_LABEL = "SYNTHETIC P01 — not market evidence"
SEED = 20260911
N = 36
# Documented identity OLS: preco = 200000 + 3500*area + 40000*bairro_Sul + e
BETA_CONST = 200000.0
BETA_AREA = 3500.0
BETA_SUL = 40000.0
SIGMA = 2500.0
MEAN_CI_LEVEL = 0.80


def documented_identity_ols_frame(n: int = N, seed: int = SEED) -> pd.DataFrame:
    """n>=30 identity OLS with intercept and one category dummy. Documented DGP."""
    rng = np.random.default_rng(seed)
    area = np.linspace(50.0, 180.0, n)
    sul = np.array([0.0, 1.0] * (n // 2) + ([0.0] if n % 2 else []))[:n]
    error = rng.normal(0.0, SIGMA, n)
    preco = BETA_CONST + BETA_AREA * area + BETA_SUL * sul + error
    return pd.DataFrame(
        {
            "id": [f"P01-{i + 1:03d}" for i in range(n)],
            "area": area,
            "bairro": np.where(sul == 1.0, "Sul", "Centro"),
            "bairro_Sul": sul,
            "preco": preco,
        }
    )


def documented_csv_bytes(n: int = N, seed: int = SEED) -> bytes:
    frame = documented_identity_ols_frame(n=n, seed=seed)
    lines = ["id;bairro;area;preco"]
    for _, row in frame.iterrows():
        lines.append(
            f"{row['id']};{row['bairro']};{row['area']:.6f};{row['preco']:.6f}"
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def documented_request_spec(**overrides):
    spec = {
        "schema_version": "MP/1",
        "target_col": "preco",
        "candidate_cols": ["area", "bairro"],
        "roles": {
            "preco": "target",
            "area": "predictor",
            "bairro": "predictor",
            "id": "identifier",
        },
        "units": {"area": "m2", "preco": "BRL"},
        "import_options": {"locale": "en-US", "delimiter": ";", "encoding": "utf-8"},
        "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
        "outlier_policy": {"mode": "report_only", "reviewed_exclusions": []},
        "search_policy": {
            "mode": "exact",
            "budget": 32,
            "objective": "original_scale_error",
            "seed": SEED,
            "y_transformations": ["identity"],
            "minimum_fundamentacao_grade": None,
            "model_scope": "population_model",
        },
        "evaluation_policy": {
            "method": "none",
            "partitions": None,
            "groups": None,
            "seed": SEED,
        },
        "reference_date": "2024-06-01",
        "inspection_date": "2024-06-15",
        "target_unit": "BRL",
        "applicant": SYNTHETIC_LABEL,
        "purpose": "p01-synthetic-acceptance",
    }
    spec.update(overrides)
    return spec


def independent_ols_oracle(X: np.ndarray, y: np.ndarray, x0: np.ndarray, level: float = MEAN_CI_LEVEL):
    """Oracle: numpy.linalg.lstsq + independent t interval. Does not call production helpers."""
    from scipy import stats

    beta, residuals, rank, _s = np.linalg.lstsq(X, y, rcond=None)
    n, p = X.shape
    fitted = X @ beta
    resid = y - fitted
    df = n - p
    ssr = float(np.dot(resid, resid))
    scale = ssr / df
    sigma = float(np.sqrt(scale))
    xtx = X.T @ X
    xtx_inv = np.linalg.inv(xtx)
    quad = float(x0 @ xtx_inv @ x0)
    se_mean = sigma * np.sqrt(quad)
    se_pred = sigma * np.sqrt(1.0 + quad)
    tcrit = float(stats.t.ppf(1.0 - (1.0 - level) / 2.0, df))
    point = float(x0 @ beta)
    return {
        "beta": beta,
        "point": point,
        "sigma": sigma,
        "scale": scale,
        "df": df,
        "rank": int(rank),
        "xtx_inv": xtx_inv,
        "mean_ci80": {"lower": point - tcrit * se_mean, "upper": point + tcrit * se_mean},
        "prediction_interval": {
            "lower": point - tcrit * se_pred,
            "upper": point + tcrit * se_pred,
        },
        "se_mean": float(se_mean),
        "se_pred": float(se_pred),
        "tcrit": tcrit,
        "feature_order": None,
    }


def _shutdown_runner():
    from backend.api import RuntimeBindings

    runner = RuntimeBindings.task_runner
    if runner is not None and hasattr(runner, "shutdown"):
        try:
            runner.shutdown(wait=True)
        except Exception:
            pass


@pytest.fixture
def isolated_p01_runtime(tmp_path, monkeypatch):
    _shutdown_runner()
    reset_runtime()
    JobStore.reset_default()
    WebSocketNotifier().reset_connections()
    store_root = tmp_path / "p01-store"
    store_root.mkdir()
    monkeypatch.setenv("MODELA_STORE_ROOT", str(store_root))
    monkeypatch.setenv("MODELA_SKIP_DOTENV", "1")
    monkeypatch.setenv("MP_CODE_SHA", "p01-test")
    store = JobStore.configure_default(store_root, recover_abandoned=True)
    projects = ProjectStore(store.root)
    runner = LocalTaskRunner(store, max_workers=1, recover_abandoned=False)
    bind_runtime(job_store=store, project_store=projects, task_runner=runner, reset_submissions=True)
    yield {"root": store_root, "job_store": store, "project_store": projects, "runner": runner}
    _shutdown_runner()
    reset_runtime()
    JobStore.reset_default()
    WebSocketNotifier().reset_connections()
