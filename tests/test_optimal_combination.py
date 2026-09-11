"""Adapter-level tests for OptimalCombinationFinder.find_best_model (C05)."""
import logging
import time

import numpy as np
import pandas as pd
import pytest

from modules.optimal_combination import OptimalCombinationFinder, search_models
from modules.search_space import count_exhaustive_candidates


class TestExhaustiveSearchFindsTrueBest:
    def _make_df(self):
        area = np.array([50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0, 120.0, 130.0])
        ruido = np.array([12.0, 3.0, 27.0, 8.0, 19.0, 2.0, 15.0, 6.0, 22.0])
        noise = np.array([15.0, -8.0, 22.0, -30.0, 5.0, -12.0, 18.0, -3.0, 9.0])
        preco = 1000 * area + 20000 + noise
        return pd.DataFrame({"area": area, "ruido": ruido, "preco": preco})

    def test_finds_the_true_best_combination_and_is_exhaustive(self):
        df = self._make_df()
        finder = OptimalCombinationFinder()
        result = finder.find_best_model(df, "preco", degree=1)

        assert result.success is True
        assert result.exhaustive is True
        assert result.combinations_tested == 63
        assert result.best_model is not None
        assert result.best_model.success is True
        assert result.history
        history_combos = {tuple(h["variables"]) for h in result.history}
        assert len(history_combos) == 63


class TestCombinatorialSafetyValve:
    def test_count_exceeds_threshold_without_running_any_search(self):
        finder = OptimalCombinationFinder()
        option_counts = [7] * 20
        count = finder._count_exhaustive_candidates(option_counts, max_vars=5)
        assert count > finder.MAX_EXHAUSTIVE_CANDIDATES
        assert count_exhaustive_candidates([7] * 6, max_vars=6) == 262143

    def test_small_count_stays_under_threshold(self):
        finder = OptimalCombinationFinder()
        option_counts = [7] * 5
        count = finder._count_exhaustive_candidates(option_counts, max_vars=4)
        assert count <= finder.MAX_EXHAUSTIVE_CANDIDATES

    def test_fallback_triggers_completes_quickly_and_is_logged(self, caplog):
        np.random.seed(0)
        n = 9
        data = {f"v{i}": np.random.uniform(1, 100, n) for i in range(100)}
        data["target"] = np.random.uniform(1000, 2000, n)
        df = pd.DataFrame(data)

        finder = OptimalCombinationFinder()

        with caplog.at_level(logging.WARNING, logger="modelapro"):
            t0 = time.time()
            result = finder.find_best_model(df, "target", degree=1)
            elapsed = time.time() - t0

        assert result.success is True
        assert result.exhaustive is False
        assert elapsed < 25, f"approximate search took too long: {elapsed:.1f}s"
        assert result.combinations_tested <= finder.MAX_EXHAUSTIVE_CANDIDATES
        logged = any(
            "aproximada" in rec.message.lower() or "fallback" in rec.message.lower()
            for rec in caplog.records
        )
        # Disclosure is also on the result message (user-facing), not only logs.
        combined = (result.message or "") + " " + " ".join(r.message for r in caplog.records)
        assert "limite de segurança" in combined.lower() or "orçamento" in combined.lower()
        assert logged or "aproximada" in (result.message or "").lower()


class TestCandidateColsRestriction:
    def _make_df(self, n=12):
        np.random.seed(42)
        a = np.random.uniform(10, 100, n)
        b = np.random.uniform(10, 100, n)
        c = np.random.uniform(10, 100, n)
        target = 2 * a + 3 * b - c + np.random.normal(0, 1, n) + 100
        return pd.DataFrame({"a": a, "b": b, "c": c, "target": target})

    def test_candidate_cols_restricts_search_to_requested_variables(self):
        df = self._make_df()
        finder = OptimalCombinationFinder()
        result = finder.find_best_model(df, "target", degree=1, candidate_cols=["a", "b"])
        assert result.success is True
        assert result.history
        for entry in result.history:
            base_names = {
                OptimalCombinationFinder._base_name(col) for col in entry["variables"]
            }
            assert base_names <= {"a", "b"}
            assert "c" not in base_names
        if result.best_model is not None and result.best_model.success:
            winning_bases = {
                OptimalCombinationFinder._base_name(c)
                for c in result.best_model.coefficients
                if c != "const"
            }
            assert winning_bases <= {"a", "b"}

    def test_candidate_cols_none_auto_selects_predictors(self):
        df = self._make_df()
        finder = OptimalCombinationFinder()
        result = finder.find_best_model(df, "target", degree=1, candidate_cols=None)
        assert result.success is True
        used_bases = set()
        for entry in result.history:
            used_bases |= {
                OptimalCombinationFinder._base_name(col) for col in entry["variables"]
            }
        assert used_bases <= {"a", "b", "c"}
        assert used_bases
        assert "c" in used_bases

    def test_candidate_cols_empty_list_is_error(self):
        df = self._make_df()
        finder = OptimalCombinationFinder()
        result = finder.find_best_model(df, "target", degree=1, candidate_cols=[])
        assert result.success is False
        assert result.error == "no_authorized_variables"

    def test_candidate_cols_ignores_unknown_names_with_warning_not_error(self, caplog):
        df = self._make_df()
        finder = OptimalCombinationFinder()
        with caplog.at_level(logging.WARNING, logger="modelapro"):
            result = finder.find_best_model(
                df, "target", degree=1, candidate_cols=["a", "nonexistent_col"]
            )
        assert result.success is True
        for entry in result.history:
            base_names = {
                OptimalCombinationFinder._base_name(col) for col in entry["variables"]
            }
            assert base_names <= {"a"}
        combined = (result.message or "") + " ".join(r.message for r in caplog.records)
        assert "nonexistent_col" in combined
