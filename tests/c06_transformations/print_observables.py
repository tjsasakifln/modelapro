"""Fresh-consumer launch of the shipped C06 entry points (not pytest)."""
import json

import numpy as np
import pandas as pd

from modules.transformations import Transformer
from modules.target_transform import (
    fit_target_transform,
    inverse_target_prediction,
    transform_target,
)


def main():
    sqrt_series, sqrt_ok = Transformer.apply_transformation(
        pd.Series([0.0, 1.0, 4.0]), "sqrt"
    )
    sqrt_vals = ",".join(
        str(int(v)) if float(v).is_integer() else str(v)
        for v in sqrt_series.to_numpy(dtype=float)
    )

    y = np.array([2.0, 4.0, 8.0])
    ident_state = fit_target_transform(y, "identity")
    ident_inv = inverse_target_prediction(np.array([2.0, 4.0, 8.0]), ident_state)

    log_state = fit_target_transform(y, "log")
    z = transform_target(y, log_state)
    log_inv = inverse_target_prediction(z, log_state)

    payload = {
        "sqrt_success": bool(sqrt_ok),
        "sqrt": sqrt_vals,
        "identity_point": [float(v) for v in np.asarray(ident_inv["point"], dtype=float)],
        "identity_estimand": ident_inv["estimand"],
        "log_point": [float(v) for v in np.asarray(log_inv["point"], dtype=float)],
        "log_estimand": log_inv["estimand"],
        "log_limitations": list(log_inv["limitations"]),
        "log_mean_ci80": log_inv["value"]["mean_ci80"],
    }
    print(json.dumps(payload, sort_keys=True))
    print("sqrt_line=" + sqrt_vals)


if __name__ == "__main__":
    main()
