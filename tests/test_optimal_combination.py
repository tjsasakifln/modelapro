import itertools
import logging
import time

import numpy as np
import pandas as pd
import pytest

from modules.optimal_combination import OptimalCombinationFinder
from modules.model_builder import ModelBuilder
from modules.transformations import Transformer


class TestExhaustiveSearchFindsTrueBest:
    """
    Small, fully controlled case designed to PROVE exhaustiveness, not just
    exercise the code path: 2 base variables (area, plus 'ruido' - a
    variable with no real relationship to the target) and n=9 rows, so
    max_vars = max(1, n // 3 - 1) = 2. The full search space (linear + every
    domain-valid transform per variable, subsets of size 1 and 2) is exactly
    63 candidates.

    This test independently re-enumerates that same 63-candidate space with
    plain itertools (NOT by calling OptimalCombinationFinder's private
    iterator - that would just test the iterator against itself) and
    brute-forces the true best r2_adjusted achievable in it. It then asserts
    find_best_model actually returns that same optimum and the same
    candidate count, and that OptimalCombinationResult.exhaustive is True -
    i.e. this is a controlled, hand-verifiable proof that the search really
    is exhaustive over the documented space, not a sample/heuristic.
    """

    NON_LINEAR = ['ln', 'sqrt', 'inverse', 'sqr', 'inv_sqr', 'inv_sqrt']

    def _make_df(self):
        area = np.array([50., 60., 70., 80., 90., 100., 110., 120., 130.])
        # Uncorrelated "ruido" (noise): no real relationship to price, but
        # still a fully domain-valid (positive, nonzero) candidate variable
        # that a genuinely exhaustive search must consider transforms of.
        ruido = np.array([12., 3., 27., 8., 19., 2., 15., 6., 22.])
        noise = np.array([15., -8., 22., -30., 5., -12., 18., -3., 9.])
        preco = 1000 * area + 20000 + noise
        return pd.DataFrame({'area': area, 'ruido': ruido, 'preco': preco})

    def _brute_force_best_r2_adjusted(self, df):
        """
        Independently re-derives the documented search space (base variable
        x {linear, every domain-valid transform}, all subsets of size
        1..max_vars) with plain itertools, fits every one of those
        candidates with the same ModelBuilder call the finder uses
        internally, and returns:
          - best_r2adj: the best r2_adjusted found
          - best_combo: the exact column-name tuple that achieved it
          - count: total candidate count
          - fitted: the set of all column-tuples that fit successfully
        - the "manual"/ground-truth answer to compare the finder against,
        including WHICH combination wins, not merely its score (a finder
        that silently substituted or skipped candidates could still land on
        the same best score by coincidence, so the score alone does not
        prove exhaustiveness).
        """
        builder = ModelBuilder()
        y = df['preco']
        n = len(df)

        tdf = df.copy()
        vars_options = {}
        for col in ['area', 'ruido']:
            opts = [col]  # linear / no transformation
            for t in self.NON_LINEAR:
                transformed, ok = Transformer.apply_transformation(df[col], t)
                if ok:
                    name = f'{t}({col})'
                    tdf[name] = transformed
                    opts.append(name)
            vars_options[col] = opts

        max_vars = max(1, n // 3 - 1)
        base_vars = list(vars_options.keys())

        best_r2adj = -float('inf')
        best_combo = None
        count = 0
        fitted = set()
        for k in range(1, max_vars + 1):
            for subset in itertools.combinations(base_vars, k):
                option_lists = [vars_options[v] for v in subset]
                for choice in itertools.product(*option_lists):
                    count += 1
                    choice = tuple(choice)
                    X_subset = tdf[list(choice)]
                    r = builder.build_model(X_subset, y, degree=1, remove_outliers=True)
                    if r.success and r.model_metrics:
                        fitted.add(choice)
                        if r.model_metrics.r2_adjusted > best_r2adj:
                            best_r2adj = r.model_metrics.r2_adjusted
                            best_combo = choice
        return best_r2adj, best_combo, count, fitted

    def test_finds_the_true_best_combination_and_is_exhaustive(self):
        df = self._make_df()

        expected_best_r2adj, expected_combo, expected_count, expected_fitted = (
            self._brute_force_best_r2_adjusted(df)
        )
        # Sanity check on the fixture itself: the search space here must be
        # small (so this test stays fast) but non-trivial (more than just
        # "one obvious candidate"), otherwise the "proof" is vacuous.
        assert expected_count == 63
        assert expected_combo is not None

        finder = OptimalCombinationFinder()
        result = finder.find_best_model(df, 'preco', degree=1)

        assert result.success is True
        assert result.exhaustive is True
        assert result.combinations_tested == expected_count
        assert result.best_model is not None
        assert result.best_model.success is True
        assert result.best_model.model_metrics.r2_adjusted == pytest.approx(
            expected_best_r2adj, abs=1e-9
        )

        # Not just the same SCORE - the exact same WINNING combination
        # (a finder that enumerated a different set of 63 candidates but
        # happened to land on a tying score would still pass a score-only
        # check; this does not).
        winning_cols = tuple(c for c in result.best_model.coefficients if c != 'const')
        assert set(winning_cols) == set(expected_combo)

        # And the full set of candidates actually explored (as recorded in
        # the returned history) must match the independently-enumerated
        # search space exactly - the actual proof of exhaustiveness: no
        # candidate skipped, none substituted, none invented.
        history_combos = {tuple(h["variables"]) for h in result.history}
        assert history_combos == expected_fitted


class TestCombinatorialSafetyValve:
    """
    The valve bounds candidate COUNT (via a cheap DP, no model fit) before
    any search runs. These tests confirm (a) the counting itself correctly
    flags an oversized space without doing any real work, and (b) when
    find_best_model actually hits that situation it falls back instead of
    hanging, finishes quickly, marks exhaustive=False, and logs why.
    """

    def test_count_exceeds_threshold_without_running_any_search(self):
        finder = OptimalCombinationFinder()
        # 20 candidate base variables x 7 options each (linear + all 6
        # transforms), up to 5 variables per model: a plausible worst-case
        # shape. This only exercises the DP counter - no DataFrame, no
        # model fit, so it is inherently fast regardless of the numbers
        # involved.
        option_counts = [7] * 20
        count = finder._count_exhaustive_candidates(option_counts, max_vars=5)
        assert count > finder.MAX_EXHAUSTIVE_CANDIDATES

    def test_small_count_stays_under_threshold(self):
        # Contrast case: a realistic real-estate-appraisal-sized space (a
        # handful of variables) never trips the valve.
        finder = OptimalCombinationFinder()
        option_counts = [7] * 5
        count = finder._count_exhaustive_candidates(option_counts, max_vars=4)
        assert count <= finder.MAX_EXHAUSTIVE_CANDIDATES

    def test_fallback_triggers_completes_quickly_and_is_logged(self, caplog):
        """
        With enough candidate base variables that the true exhaustive space
        exceeds MAX_EXHAUSTIVE_CANDIDATES, find_best_model must fall back to
        the documented correlation-pruning heuristic instead of hanging,
        report exhaustive=False, and log an explanatory message. n is kept
        tiny (9 rows) purely to bound this test's wall-clock time - the
        combinatorial explosion being tested comes from the variable COUNT
        (100 candidate base variables), not from the row count.
        """
        np.random.seed(0)
        n = 9
        data = {f'v{i}': np.random.uniform(1, 100, n) for i in range(100)}
        data['target'] = np.random.uniform(1000, 2000, n)
        df = pd.DataFrame(data)

        finder = OptimalCombinationFinder()

        with caplog.at_level(logging.WARNING, logger="modelapro"):
            t0 = time.time()
            result = finder.find_best_model(df, 'target', degree=1)
            elapsed = time.time() - t0

        assert result.success is True
        assert result.exhaustive is False
        # Generous ceiling (observed locally at ~1-2s): proves the valve
        # actually bounds runtime instead of attempting the true exhaustive
        # space (which would be hundreds of thousands of OLS fits).
        assert elapsed < 25, f"safety valve fallback took too long: {elapsed:.1f}s"

        fallback_logged = any(
            "fallback" in rec.message.lower() and "limite de segurança" in rec.message.lower()
            for rec in caplog.records
        )
        assert fallback_logged, "expected a logged explanation of the combinatorial fallback"


class TestCandidateColsRestriction:
    """
    candidate_cols lets the caller (the user's free choice of which market
    variables to bring in) restrict the search to an explicit subset of base
    variables. None/empty must keep the old behavior (every column except
    the target is a candidate).
    """

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
        assert result.history, "expected at least one candidate to be tested"

        for entry in result.history:
            base_names = {
                OptimalCombinationFinder._base_name(col) for col in entry["variables"]
            }
            # No combination in the history may use a base variable outside
            # the requested candidate_cols (target itself is never a base
            # variable candidate).
            assert base_names <= {"a", "b"}
            assert "c" not in base_names

        # The winning model itself must also respect the restriction.
        if result.best_model is not None and result.best_model.success:
            winning_bases = {
                OptimalCombinationFinder._base_name(c)
                for c in result.best_model.coefficients
                if c != "const"
            }
            assert winning_bases <= {"a", "b"}

    def test_candidate_cols_none_keeps_old_behavior_all_columns_candidates(self):
        df = self._make_df()
        finder = OptimalCombinationFinder()

        result = finder.find_best_model(df, "target", degree=1, candidate_cols=None)

        assert result.success is True
        used_bases = set()
        for entry in result.history:
            used_bases |= {
                OptimalCombinationFinder._base_name(col) for col in entry["variables"]
            }
        # With no restriction, the search must be free to explore every
        # non-target column - i.e. it isn't silently limited to a subset.
        assert used_bases <= {"a", "b", "c"}
        assert used_bases, "expected some candidates to be tested"
        # At least one of the base variables outside any hypothetical
        # restriction must have been explored, proving 'c' is reachable
        # when candidate_cols is not passed.
        assert "c" in used_bases

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

        assert any(
            "nonexistent_col" in rec.message for rec in caplog.records
        ), "expected a warning about the unknown candidate_cols entry"
