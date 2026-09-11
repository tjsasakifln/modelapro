#!/usr/bin/env python3
"""C14 benchmark: N individual (preprocess+fit+evaluate) vs N reused evaluates.

Conditions are printed with the measurements. This script does not claim a
productivity multiplier; it only reports what was timed on this machine.
Synthetic data, identified as such.
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.valuation_batch import evaluate_batch  # noqa: E402
from tests.c14_batch.conftest import (  # noqa: E402
    expected_point,
    make_frozen_project,
    make_request_spec,
    make_subject,
)


def _rss_mb() -> float:
    if tracemalloc.is_tracing():
        current, _peak = tracemalloc.get_traced_memory()
        return current / (1024.0 * 1024.0)
    return 0.0


def _fit_ols(n: int, seed: int):
    rng = np.random.default_rng(seed)
    area = rng.uniform(60.0, 180.0, size=n)
    bairro_sul = rng.integers(0, 2, size=n).astype(float)
    noise = rng.normal(0.0, 8000.0, size=n)
    y = 100000.0 + 2500.0 * area + 20000.0 * bairro_sul + noise
    X = pd.DataFrame({"area": area, "bairro_Sul": bairro_sul})
    Xc = sm.add_constant(X, has_constant="add")
    model = sm.OLS(y, Xc).fit()
    return model, Xc, y


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", type=int, default=40, help="number of subjects")
    parser.add_argument("--seed", type=int, default=20260911)
    parser.add_argument("--fit-rows", type=int, default=80)
    args = parser.parse_args()

    n = args.n
    seed = args.seed
    print("C14 benchmark conditions")
    print(f"  N subjects: {n}")
    print(f"  seed: {seed}")
    print(f"  fit_rows: {args.fit_rows}")
    print(f"  python: {sys.version.split()[0]}")
    print(f"  platform: {platform.platform()}")
    print(f"  machine: {platform.machine()}")
    print(f"  pid: {os.getpid()}")
    print("  data: synthetic identified (not market observations)")
    print("  phases timed: preprocess, fit, evaluate")
    print("  claim: none (no productivity multiplier)")

    rng = np.random.default_rng(seed)
    subjects = []
    for i in range(n):
        area = float(rng.uniform(70.0, 160.0))
        bairro = "Sul" if i % 2 else "Centro"
        subjects.append(make_subject(f"b{i}", area=area, bairro=bairro))

    frozen = make_frozen_project()
    spec = make_request_spec()

    tracemalloc.start()

    # --- Individual path: preprocess + fit + evaluate per subject ---
    t_pre = t_fit = t_eval = 0.0
    mem_peak_individual = 0.0
    individual_points = []
    for sub in subjects:
        t0 = time.perf_counter()
        frame = pd.DataFrame([sub["raw"]])
        _ = frame.copy()  # preprocess stand-in: copy/encode-ready frame
        t_pre += time.perf_counter() - t0

        t0 = time.perf_counter()
        model, _Xc, _y = _fit_ols(args.fit_rows, seed)
        t_fit += time.perf_counter() - t0

        t0 = time.perf_counter()
        dummy = 1.0 if sub["raw"]["bairro"] == "Sul" else 0.0
        x = [1.0, float(sub["raw"]["area"]), dummy]
        point = float(np.dot(model.params.to_numpy(), x))
        individual_points.append(point)
        t_eval += time.perf_counter() - t0
        mem_peak_individual = max(mem_peak_individual, _rss_mb())

    individual_total = t_pre + t_fit + t_eval

    # --- Reused path: one preprocess+fit, then evaluate_batch (frozen apply) ---
    t0 = time.perf_counter()
    _ = pd.DataFrame([s["raw"] for s in subjects]).copy()
    t_pre_r = time.perf_counter() - t0

    t0 = time.perf_counter()
    _model, _Xc, _y = _fit_ols(args.fit_rows, seed)
    t_fit_r = time.perf_counter() - t0

    t0 = time.perf_counter()
    batch = evaluate_batch(frozen, subjects, spec, max_workers=1)
    t_eval_r = time.perf_counter() - t0
    mem_peak_reused = _rss_mb()
    reused_total = t_pre_r + t_fit_r + t_eval_r

    tracemalloc.stop()

    succeeded = batch["summary"]["succeeded"]
    print("results")
    print(
        f"  individual_s  preprocess={t_pre:.6f} fit={t_fit:.6f} "
        f"evaluate={t_eval:.6f} total={individual_total:.6f} "
        f"mem_peak_mb={mem_peak_individual:.3f}"
    )
    print(
        f"  reused_s      preprocess={t_pre_r:.6f} fit={t_fit_r:.6f} "
        f"evaluate={t_eval_r:.6f} total={reused_total:.6f} "
        f"mem_peak_mb={mem_peak_reused:.3f}"
    )
    print(f"  batch_succeeded={succeeded}/{n} state={batch['state']}")
    if individual_total > 0 and reused_total > 0:
        ratio = individual_total / reused_total
        print(f"  observed_total_ratio_individual_over_reused={ratio:.4f} (measurement, not a claim)")
    # Numeric sanity: reused batch points match the frozen oracle, not the noisy refits.
    mismatches = 0
    for sub, item in zip(subjects, batch["items"]):
        oracle = expected_point(sub["raw"]["area"], sub["raw"]["bairro"])
        if item["value"]["point"] is None or abs(item["value"]["point"] - oracle) > 1e-6:
            mismatches += 1
    print(f"  reused_oracle_mismatches={mismatches}")
    return 0 if mismatches == 0 and succeeded == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
