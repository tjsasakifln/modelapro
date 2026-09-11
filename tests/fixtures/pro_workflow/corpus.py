"""Deterministic synthetic corpus for the eight P04 situation families.

Generators only. No product imports. Files written under data/ are labelled
synthetic in SYNTHETIC.md.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from . import ols_oracle as oracle

FIXTURES_DIR = Path(__file__).resolve().parent
DATA_DIR = FIXTURES_DIR / "data"
SEED = 20260911
CAMPAIGN_ID = "MP-PRO-20260911/P04"

# Identity OLS slope used when a case pins area-only.
S01_SLOPE = 8000.0
S01_INTERCEPT = 0.0
S01_SUL_ADD = 40000.0
S01_NOISE_SD = 2500.0
S01_N = 48
S01_SUBJECT_AREA = 73.5  # not on the 50, 51, … grid

S02_MISSING_AT = (0, 8, 16, 24, 32)
S02_N = 36
S02_SLOPE = 10000.0

S05_N = 40
S05_OUTLIER_INDEX = 7
S05_OUTLIER_PRICE = 2_400_000.0

S06_AREA_MIN = 50.0
S06_AREA_MAX = 100.0
S06_SLOPE = 1000.0
S06_SUBJECT_EXTENDED = 150.0  # faixa ampliada, price outside sample
S06_SUBJECT_IN = 90.0
S06_SUBJECT_OUTSIDE = 250.0

S08_N = 210
S08_MISSING_AT = 9


def fmt_ptbr(value: float) -> str:
    formatted = f"{value:,.2f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _rng(seed: int = SEED) -> np.random.Generator:
    return np.random.default_rng(int(seed))


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[Dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def s01_identity_noise_category(*, seed: int = SEED) -> Dict[str, Any]:
    """OLS identity with Gaussian noise and a three-level bairro."""
    rng = _rng(seed)
    rows: List[Dict[str, Any]] = []
    bairros = ("Centro", "Norte", "Sul")
    for i in range(S01_N):
        area = 50.0 + i
        bairro = bairros[i % 3]
        noise = float(rng.normal(0.0, S01_NOISE_SD))
        extra = S01_SUL_ADD if bairro == "Sul" else 0.0
        preco = S01_INTERCEPT + S01_SLOPE * area + extra + noise
        rows.append(
            {
                "id": f"IM-{i + 1:03d}",
                "area": f"{area:.2f}",
                "bairro": bairro,
                "preco": f"{preco:.4f}",
            }
        )
    areas = [50.0 + i for i in range(S01_N)]
    rng2 = _rng(seed)
    y = []
    for i, area in enumerate(areas):
        extra = S01_SUL_ADD if bairros[i % 3] == "Sul" else 0.0
        y.append(S01_INTERCEPT + S01_SLOPE * area + extra + float(rng2.normal(0.0, S01_NOISE_SD)))
    fit_area = oracle.fit_ols(y, {"area": areas})
    pred_area = oracle.predict_intervals(fit_area, {"area": S01_SUBJECT_AREA})
    encoded = oracle.encode_treatment([r["bairro"] for r in rows], column="bairro")
    cols = {"area": areas, **encoded["columns"]}
    fit_cat = oracle.fit_ols(y, cols)
    x0_cat = {"area": S01_SUBJECT_AREA, **{name: 0.0 for name in encoded["dummy_names"]}}
    # subject bairro Centro is the lexicographic first of {Centro, Norte, Sul} → all zeros
    pred_cat = oracle.predict_intervals(fit_cat, x0_cat)
    return {
        "id": "S01",
        "family": "ols_identity_noise_category",
        "rows": rows,
        "fieldnames": ["id", "area", "bairro", "preco"],
        "subject": {"area": S01_SUBJECT_AREA, "bairro": "Centro"},
        "oracle_area_only": {
            "fit": {k: fit_area[k] for k in ("coefficients", "n", "p", "df", "sigma2")},
            "prediction": pred_area,
        },
        "oracle_area_bairro": {
            "fit": {k: fit_cat[k] for k in ("coefficients", "n", "p", "df", "sigma2")},
            "prediction": pred_cat,
            "encoding": {k: encoded[k] for k in ("reference", "levels", "dummy_names", "convention")},
        },
        "notes": "Search is not forced. Area-only spec is the pinned OLS comparison.",
    }


def s02_ptbr_and_missing(*, n: int = S02_N) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    missing = set(S02_MISSING_AT)
    for i in range(n):
        area = 50.0 + 2.0 * i
        preco = S02_SLOPE * area
        rows.append(
            {
                "id": f"PT-{i + 1:03d}",
                "bairro": "Centro",
                "area": fmt_ptbr(area),
                "preco": "" if i in missing else fmt_ptbr(preco),
            }
        )
    observed = [S02_SLOPE * (50.0 + 2.0 * i) for i in range(n) if i not in missing]
    areas_obs = [50.0 + 2.0 * i for i in range(n) if i not in missing]
    fit = oracle.fit_ols(observed, {"area": areas_obs})
    pred = oracle.predict_intervals(fit, {"area": S01_SUBJECT_AREA})
    return {
        "id": "S02",
        "family": "ptbr_csv_excel_missing_target",
        "rows": rows,
        "fieldnames": ["id", "bairro", "area", "preco"],
        "delimiter": ";",
        "locale": "pt-BR",
        "n_received": n,
        "n_observed_target": n - len(missing),
        "missing_indices": list(missing),
        "subject": {"area": S01_SUBJECT_AREA, "bairro": "Centro"},
        "oracle_area_only": {
            "fit": {k: fit[k] for k in ("coefficients", "n", "p", "df", "sigma2")},
            "prediction": pred,
        },
    }


def s02_csv_bytes(case: Optional[Dict[str, Any]] = None) -> bytes:
    case = case or s02_ptbr_and_missing()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=case["fieldnames"], delimiter=";")
    writer.writeheader()
    for row in case["rows"]:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def s02_excel_bytes(case: Optional[Dict[str, Any]] = None) -> bytes:
    """Numeric Excel equivalent of the pt-BR CSV (same observed targets)."""
    import pandas as pd

    case = case or s02_ptbr_and_missing()
    records = []
    missing = set(case["missing_indices"])
    for i, row in enumerate(case["rows"]):
        area = 50.0 + 2.0 * i
        price = None if i in missing else S02_SLOPE * area
        rec = {"id": row["id"], "bairro": row["bairro"], "area": area, "preco": price}
        records.append(rec)
    frame = pd.DataFrame.from_records(records)
    buf = io.BytesIO()
    frame.to_excel(buf, index=False, engine="openpyxl")
    return buf.getvalue()


def s03_discrepant_unit_date() -> Dict[str, Any]:
    """Market in m2 / 2024-06-01; subject unit and date left pending or conflicting."""
    rows = []
    for i in range(24):
        area = 60.0 + i
        rows.append({
            "id": f"U-{i + 1:03d}",
            "area": f"{area:.2f}",
            "preco": f"{10000.0 * area:.2f}",
            "data": "2024-06-01",
        })
    return {
        "id": "S03",
        "family": "discrepant_unit_date_policy",
        "rows": rows,
        "fieldnames": ["id", "area", "preco", "data"],
        "market_unit": "m2",
        "subject_conflicting_unit": "ft2",
        "reference_date": "2024-06-01",
        "inspection_date": "2025-01-15",
        "subject": {"area": 85.0},
        "expected": {
            "unknown_unit_is_pending": True,
            "do_not_assume_brl": True,
            "conflicting_aliases_are_errors": True,
        },
    }


def s04_holdout_reserve_category(*, n: int = 40, seed: int = 17) -> Dict[str, Any]:
    # Product row_ids are generated as R000000.. (modules.data_loader._make_row_id).
    # The independent holdout shuffles those ids, not the display identifier column.
    width = max(6, len(str(max(n - 1, 0))))
    ids = [f"R{i:0{width}d}" for i in range(n)]
    reserved = set(map(str, oracle.holdout_reserved_ids(ids, seed=seed, test_size=0.2)))
    rows = []
    areas = []
    y = []
    train_ids = []
    for i, rid in enumerate(ids):
        area = 55.0 + i
        in_reserve = rid in reserved
        bairro = "Industrial" if in_reserve else ("Centro" if i % 2 == 0 else "Sul")
        preco = 9000.0 * area + (30000.0 if bairro == "Sul" else 0.0)
        rows.append({"id": f"HO-{i + 1:03d}", "area": f"{area:.2f}", "bairro": bairro, "preco": f"{preco:.2f}"})
        if not in_reserve:
            areas.append(area)
            y.append(preco)
            train_ids.append(rid)
    fit = oracle.fit_ols(y, {"area": areas})
    pred = oracle.predict_intervals(fit, {"area": 80.0})
    train_levels = sorted({r["bairro"] for r, rid in zip(rows, ids) if rid not in reserved})
    return {
        "id": "S04",
        "family": "holdout_reserve_only_category",
        "rows": rows,
        "fieldnames": ["id", "area", "bairro", "preco"],
        "product_row_ids": ids,
        "reserved_ids": sorted(reserved),
        "train_ids": train_ids,
        "train_levels": train_levels,
        "reserve_only_category": "Industrial",
        "holdout_seed": seed,
        "test_size": 0.2,
        "subject_known": {"area": 80.0, "bairro": "Centro"},
        "subject_unknown": {"area": 80.0, "bairro": "Industrial"},
        "oracle_train_area_only": {
            "fit": {k: fit[k] for k in ("coefficients", "n", "p", "df", "sigma2")},
            "prediction": pred,
        },
    }


def s05_influence(*, n: int = S05_N, seed: int = SEED) -> Dict[str, Any]:
    rng = _rng(seed)
    rows = []
    areas = []
    y = []
    for i in range(n):
        area = 50.0 + i
        noise = float(rng.normal(0.0, 800.0))
        preco = 1000.0 * area + noise
        if i == S05_OUTLIER_INDEX:
            preco = S05_OUTLIER_PRICE
        rid = f"INF-{i + 1:03d}"
        rows.append({"id": rid, "area": f"{area:.2f}", "preco": f"{preco:.4f}"})
        areas.append(area)
        y.append(preco)
    fit = oracle.fit_ols(y, {"area": areas})
    cooks = oracle.cook_distance(fit)
    outlier_id = rows[S05_OUTLIER_INDEX]["id"]
    top = int(np.argmax(cooks))
    y_excl = [v for i, v in enumerate(y) if i != S05_OUTLIER_INDEX]
    a_excl = [v for i, v in enumerate(areas) if i != S05_OUTLIER_INDEX]
    fit_excl = oracle.fit_ols(y_excl, {"area": a_excl})
    pred_all = oracle.predict_intervals(fit, {"area": 70.0})
    pred_excl = oracle.predict_intervals(fit_excl, {"area": 70.0})
    return {
        "id": "S05",
        "family": "influence_justified_exclusion",
        "rows": rows,
        "fieldnames": ["id", "area", "preco"],
        "outlier_id": outlier_id,
        "outlier_index": S05_OUTLIER_INDEX,
        "cook_argmax_index": top,
        "cook_argmax_id": rows[top]["id"],
        "subject": {"area": 70.0},
        "oracle_report_only": {"prediction": pred_all, "n": fit["n"]},
        "oracle_reviewed_exclusion": {"prediction": pred_excl, "n": fit_excl["n"]},
    }


def s06_boundary() -> Dict[str, Any]:
    rows = []
    areas = []
    y = []
    for i in range(26):
        area = S06_AREA_MIN + 2.0 * i  # 50..100
        rows.append({"id": f"BD-{i + 1:03d}", "area": f"{area:.2f}", "preco": f"{S06_SLOPE * area:.2f}"})
        areas.append(area)
        y.append(S06_SLOPE * area)
    fit = oracle.fit_ols(y, {"area": areas})
    subjects = {
        "in_sample": S06_SUBJECT_IN,
        "extended": S06_SUBJECT_EXTENDED,
        "outside_extended": S06_SUBJECT_OUTSIDE,
    }
    classified = {}
    for name, area in subjects.items():
        pred = oracle.predict_intervals(fit, {"area": area})
        classified[name] = {
            "area": area,
            "prediction": pred,
            "faixa": oracle.faixa_ampliada(area, S06_AREA_MIN, S06_AREA_MAX),
            "efeito": oracle.efeito_monetario(pred["point"], min(y), max(y)),
        }
    return {
        "id": "S06",
        "family": "boundary_extrapolation",
        "rows": rows,
        "fieldnames": ["id", "area", "preco"],
        "sample_area_min": S06_AREA_MIN,
        "sample_area_max": S06_AREA_MAX,
        "classified": classified,
        "probe": {"faixa_low": oracle.FAIXA_LOW, "faixa_high": oracle.FAIXA_HIGH, "nbr_status": "pending"},
    }


def s07_project_batch() -> Dict[str, Any]:
    """Same DGP as S02 without missing targets — used for save/restore/batch."""
    rows = []
    for i in range(24):
        area = 50.0 + 2.0 * i
        bairro = "Centro" if i % 2 == 0 else "Sul"
        rows.append({
            "id": f"PR-{i + 1:03d}",
            "bairro": bairro,
            "area": f"{area:.2f}",
            "preco": f"{10000.0 * area:.2f}",
        })
    return {
        "id": "S07",
        "family": "saved_restored_batch",
        "rows": rows,
        "fieldnames": ["id", "bairro", "area", "preco"],
        "subjects": [
            {"subject_id": "s1", "area": 73.5, "bairro": "Centro"},
            {"subject_id": "s2", "area": 81.0, "bairro": "Sul"},
            {"subject_id": "s3", "area": 90.0, "bairro": "Industrial"},
        ],
    }


def s08_report_dossier(*, n: int = S08_N) -> Dict[str, Any]:
    rows = []
    areas_obs = []
    y_obs = []
    for i in range(n):
        area = 50.0 + i * 0.5
        missing = i == S08_MISSING_AT
        preco = 10000.0 * area
        rows.append(
            {
                "id": f"DO-{i + 1:03d}",
                "bairro": "Centro",
                "area": fmt_ptbr(area),
                "preco": "" if missing else fmt_ptbr(preco),
            }
        )
        if not missing:
            areas_obs.append(area)
            y_obs.append(preco)
    fit = oracle.fit_ols(y_obs, {"area": areas_obs})
    pred = oracle.predict_intervals(fit, {"area": S01_SUBJECT_AREA})
    return {
        "id": "S08",
        "family": "report_dossier_210plus",
        "rows": rows,
        "fieldnames": ["id", "bairro", "area", "preco"],
        "delimiter": ";",
        "n_received": n,
        "n_observed_target": n - 1,
        "subject": {"area": S01_SUBJECT_AREA, "bairro": "Centro"},
        "oracle_area_only": {
            "fit": {k: fit[k] for k in ("coefficients", "n", "p", "df", "sigma2")},
            "prediction": pred,
        },
    }


def rows_to_csv_bytes(rows: Sequence[Dict[str, Any]], fieldnames: Sequence[str], *, delimiter: str = ",") -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(fieldnames), delimiter=delimiter)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def catalog() -> List[Dict[str, Any]]:
    return [
        {"id": "S01", "family": "ols_identity_noise_category", "builder": "s01_identity_noise_category"},
        {"id": "S02", "family": "ptbr_csv_excel_missing_target", "builder": "s02_ptbr_and_missing"},
        {"id": "S03", "family": "discrepant_unit_date_policy", "builder": "s03_discrepant_unit_date"},
        {"id": "S04", "family": "holdout_reserve_only_category", "builder": "s04_holdout_reserve_category"},
        {"id": "S05", "family": "influence_justified_exclusion", "builder": "s05_influence"},
        {"id": "S06", "family": "boundary_extrapolation", "builder": "s06_boundary"},
        {"id": "S07", "family": "saved_restored_batch", "builder": "s07_project_batch"},
        {"id": "S08", "family": "report_dossier_210plus", "builder": "s08_report_dossier"},
    ]


def materialize(data_dir: Optional[Path] = None) -> Dict[str, str]:
    """Write the small committed CSVs and a catalog JSON. S08 is generated too."""
    target = Path(data_dir) if data_dir is not None else DATA_DIR
    target.mkdir(parents=True, exist_ok=True)
    written: Dict[str, str] = {}
    cases = {
        "S01": s01_identity_noise_category(),
        "S02": s02_ptbr_and_missing(),
        "S03": s03_discrepant_unit_date(),
        "S04": s04_holdout_reserve_category(),
        "S05": s05_influence(),
        "S06": s06_boundary(),
        "S07": s07_project_batch(),
        "S08": s08_report_dossier(),
    }
    for cid, case in cases.items():
        delim = case.get("delimiter", ",")
        path = target / f"{cid.lower()}_{case['family']}.csv"
        text = rows_to_csv_bytes(case["rows"], case["fieldnames"], delimiter=delim)
        path.write_bytes(text)
        written[cid] = str(path)
        meta = {k: v for k, v in case.items() if k not in {"rows"}}
        # numpy types → json
        meta_path = target / f"{cid.lower()}_oracle.json"

        def _default(obj: Any) -> Any:
            if isinstance(obj, (np.floating, np.integer)):
                return float(obj) if isinstance(obj, np.floating) else int(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            raise TypeError(type(obj))

        meta_path.write_text(json.dumps(meta, indent=2, default=_default, ensure_ascii=False), encoding="utf-8")
    (target / "catalog.json").write_text(
        json.dumps({"campaign_id": CAMPAIGN_ID, "synthetic": True, "cases": catalog(), "seed": SEED}, indent=2),
        encoding="utf-8",
    )
    (target / "s02_ptbr.csv").write_bytes(s02_csv_bytes())
    return written


def pinned_identity_spec(**overrides: Any) -> Dict[str, Any]:
    """RequestSpec that pins identity OLS on `area` without changing search defaults globally."""
    spec = {
        "schema_version": "MP/1",
        "target_col": "preco",
        "candidate_cols": ["area"],
        "roles": {"preco": "target", "area": "predictor", "id": "identifier", "bairro": "excluded"},
        "units": {"area": "m2", "preco": ""},
        "import_options": {"locale": "en-US", "delimiter": ",", "encoding": "utf-8"},
        "missing_policy": {"target": "never_impute", "predictors": "complete_case"},
        "outlier_policy": {"mode": "report_only", "reviewed_exclusions": []},
        "search_policy": {
            "mode": "exact",
            "budget": 16,
            "objective": "aic",
            "seed": 17,
            # After P01 SEALED, target_degree is a grade alias, not a ranking knob.
            "y_transformations": ["identity"],
        },
        "evaluation_policy": {"method": "none", "partitions": None, "groups": None, "seed": 17},
        "reference_date": "2024-06-01",
        "inspection_date": "2024-06-15",
        "target_unit": "",
        "applicant": "synthetic-p04",
        "purpose": "independent-oracle-corpus",
    }
    spec.update(overrides)
    return spec


if __name__ == "__main__":
    written = materialize()
    print("wrote", json.dumps(written, indent=2))
