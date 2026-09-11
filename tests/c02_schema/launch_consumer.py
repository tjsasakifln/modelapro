"""Fresh-process consumer of the shipped C02 API.

Synthetic MP/1 fixture (not C01). Prints primary observables for two-run
equality checks.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.preprocessing import fit_dataset, transform_subject  # noqa: E402

from tests.c02_schema.fixtures import mp1_bundle, mp1_request_spec  # noqa: E402


def main() -> int:
    train_areas = [10.0, 20.0, 30.0]
    expected_mean = (10.0 + 20.0 + 30.0) / 3.0
    rows = [
        {"row_id": "t1", "bairro": "Centro", "area": train_areas[0], "valor": 100.0, "id_imovel": "A1"},
        {"row_id": "t2", "bairro": "Norte", "area": train_areas[1], "valor": 200.0, "id_imovel": "A2"},
        {"row_id": "t3", "bairro": "Sul", "area": train_areas[2], "valor": 300.0, "id_imovel": "A3"},
        {"row_id": "t4", "bairro": "Centro", "area": None, "valor": 150.0, "id_imovel": "A4"},
        {"row_id": "h1", "bairro": "ZonaReservada", "area": 1_000_000.0, "valor": 999.0, "id_imovel": "H1"},
    ]
    spec = mp1_request_spec(
        missing_policy={"target": "never_impute", "predictors": "mean"},
        roles={
            "valor": "target",
            "bairro": "predictor",
            "area": "predictor",
            "id_imovel": "identifier",
        },
    )
    prepared = fit_dataset(mp1_bundle(rows), spec, train_row_ids=["t1", "t2", "t3", "t4"])
    subject = transform_subject(
        {"bairro": "Centro", "area": "80,00"},
        prepared.feature_schema,
        prepared.encoder_state,
    )
    area_bv = next(bv for bv in prepared.encoder_state["base_variables"] if bv["original_name"] == "area")
    numeric = all(str(dt).startswith(("float", "int", "Float", "Int")) or dt.kind in "fiub" for dt in subject.X.dtypes)
    print(f"numeric={numeric}")
    print(f"supported={subject.supported}")
    print(f"train_mean={area_bv['train_mean']}")
    print(f"imputed_mean={area_bv['impute_value']}")
    print(f"expected_mean={expected_mean}")
    print(f"columns={list(subject.X.columns)}")
    print(f"held_out_in_categories={'ZonaReservada' in (next(bv for bv in prepared.encoder_state['base_variables'] if bv['original_name']=='bairro').get('categories') or [])}")
    print(f"dataset_sha256={prepared.dataset_sha256}")
    ok = (
        numeric
        and subject.supported is True
        and area_bv["train_mean"] == expected_mean
        and area_bv["impute_value"] == expected_mean
    )
    print(f"ok={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
