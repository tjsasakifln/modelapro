"""C05-A05: cancel, progress, counters, local profile, cache key, reuse."""
import time

import numpy as np
import pandas as pd
import pytest

from modules.optimal_combination import (
    build_search_cache_key,
    clear_search_cache,
    search_models,
)

from tests.c05_search.helpers import make_prepared, request_spec


def _frame(n_vars=4, n=24, seed=0):
    rng = np.random.RandomState(seed)
    data = {f"x{i}": rng.uniform(1.0, 9.0, n) for i in range(n_vars)}
    data["y"] = 4 * data["x0"] + 10 + rng.normal(0, 0.4, n)
    return pd.DataFrame(data)


def test_cancel_stops_before_global_completion():
    df = _frame(n_vars=2, n=24)
    prepared = make_prepared(df, "y")
    spec = request_spec("y", search_policy={"mode": "exact", "budget": 10_000})

    t_full0 = time.perf_counter()
    full = search_models(prepared, None, spec)
    t_full = time.perf_counter() - t_full0
    possible = full["search_audit"]["possible"]
    assert full["search_audit"]["evaluated"] == possible
    assert possible > 20

    events = []

    def progress(payload):
        events.append(dict(payload))

    def cancel_requested():
        return (events[-1].get("evaluated") or 0) >= 8 if events else False

    t0 = time.perf_counter()
    cancelled = search_models(
        prepared, None, spec, progress_callback=progress, cancel_requested=cancel_requested
    )
    t_cancel = time.perf_counter() - t0

    audit = cancelled["search_audit"]
    assert audit["cancelled"] is True
    assert audit["evaluated"] < possible
    assert audit["evaluated"] <= audit["generated"]
    assert audit["rejected"] <= audit["evaluated"]
    assert audit["coverage"]["exact_optimum_guaranteed"] is False
    assert audit["objective"]["full_objective_evaluated_on"] == "partial"
    codes = [i["code"] for i in cancelled["issues"]]
    assert "search_cancelled" in codes
    assert t_cancel <= t_full + 0.5


def test_progress_is_non_decreasing_and_in_unit_interval():
    df = _frame(n_vars=2, n=18)
    prepared = make_prepared(df, "y")
    spec = request_spec("y", search_policy={"mode": "exact", "budget": 500})
    values = []

    def progress(payload):
        values.append(payload.get("progress"))

    result = search_models(prepared, None, spec, progress_callback=progress)
    numeric = [v for v in values if v is not None]
    assert numeric, "progress_callback must fire with a numeric progress"
    assert all(0.0 <= v <= 1.0 for v in numeric)
    assert numeric == sorted(numeric)
    assert numeric[-1] == pytest.approx(1.0)
    assert result["search_audit"]["evaluated"] == result["search_audit"]["possible"]


def test_profile_records_local_before_after_without_speed_claim():
    df = _frame(n_vars=2, n=18)
    prepared = make_prepared(df, "y")
    spec = request_spec("y")
    result = search_models(prepared, None, spec)
    profile = result["search_audit"]["profile"]
    assert profile["elapsed_s"] >= 0
    assert "rss_bytes_before" in profile
    assert "rss_bytes_after" in profile
    assert profile["host"] == "this_process_only"
    assert "other machines" in profile["disclaimer"]


def test_two_identical_runs_same_winner():
    df = _frame(n_vars=2, n=18, seed=7)
    prepared = make_prepared(df, "y")
    spec = request_spec("y", search_policy={"mode": "exact", "budget": 500, "seed": 7})
    a = search_models(prepared, None, spec)
    b = search_models(prepared, None, spec)
    assert a["winner"]["candidate_id"] == b["winner"]["candidate_id"]
    assert a["search_audit"]["evaluated"] == b["search_audit"]["evaluated"]


def test_cache_key_includes_subject_when_selection_depends_on_it():
    df = _frame(n_vars=2, n=18)
    prepared = make_prepared(df, "y")
    spec = request_spec("y")
    d1, c1 = build_search_cache_key(prepared, None, spec)
    subject = {"raw_values": {"x0": 3.0, "x1": 4.0}, "X": None, "issues": [], "supported": True}
    d2, c2 = build_search_cache_key(prepared, subject, spec)
    assert d1 != d2
    assert c2["subject"] == {"x0": 3.0, "x1": 4.0}
    assert "dataset_sha256" in c2
    assert "search_policy" in c2
    assert "evaluation_policy" in c2
    assert "feature_schema" in c2
    assert "code_version" in c2
    assert "y_transformations" in c2
    assert "sample_fingerprint" in c2


def test_cache_hit_on_second_run_when_enabled():
    clear_search_cache()
    df = _frame(n_vars=2, n=18)
    prepared = make_prepared(df, "y")
    spec = request_spec("y", search_policy={"mode": "exact", "budget": 200, "use_cache": True})
    a = search_models(prepared, None, spec)
    b = search_models(prepared, None, spec)
    assert b["search_audit"]["cache_hit"] is True
    assert a["winner"]["candidate_id"] == b["winner"]["candidate_id"]


def test_cache_does_not_reuse_result_when_y_differs():
    clear_search_cache()
    rng = np.random.RandomState(0)
    x = rng.uniform(1.0, 5.0, 18)
    df_a = pd.DataFrame({"x0": x, "x1": rng.uniform(1.0, 5.0, 18), "y": np.exp(x)})
    df_b = pd.DataFrame({"x0": x, "x1": df_a["x1"], "y": np.log(x) * 1000})
    spec = request_spec("y", search_policy={"mode": "exact", "budget": 200, "use_cache": True})
    a = search_models(make_prepared(df_a, "y"), None, spec)
    b = search_models(make_prepared(df_b, "y"), None, spec)
    assert b["search_audit"].get("cache_hit") is not True
    assert a["winner"]["candidate_id"] != b["winner"]["candidate_id"] or (
        a["winner"]["metrics"]["original_rmse"] != b["winner"]["metrics"]["original_rmse"]
    )
    d1, c1 = build_search_cache_key(make_prepared(df_a, "y"), None, spec)
    d2, c2 = build_search_cache_key(make_prepared(df_b, "y"), None, spec)
    assert d1 != d2
    assert c1["sample_fingerprint"] != c2["sample_fingerprint"]
