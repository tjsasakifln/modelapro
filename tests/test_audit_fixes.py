"""
Regression tests for the high-severity audit findings fixed in this change:

1. websocket_notifier.send_notification must be able to serialize a
   'completed' payload containing datetime, numpy scalar types and
   non-finite floats (the real shape produced by worker.py/statsmodels)
   instead of raising and being swallowed by process_file's generic except.
2. (worker.py offloading find_best_model to a thread) - not directly
   unit-testable without a running event loop + long search; covered by
   code inspection / asyncio.to_thread usage.
3. OptimalCombinationFinder must pre-filter transformations that are
   domain-valid for the training column but domain-invalid for the
   avaliando's specific raw value (e.g. idade=0 with ln chosen), instead of
   silently tanking that candidate's ranking via a swallowed exception in
   add_precision_and_extrapolation.
4. The exhaustive / combinations_tested / message fields must be
   propagated by find_best_model's message and be renderable in the PDF
   report (generate_pdf_report accepts and does not choke on them).
"""
import asyncio
import json
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from modules.websocket_notifier import _json_safe
from modules.optimal_combination import OptimalCombinationFinder
from modules.results_generator import ResultsGenerator


class TestWebsocketJsonSafety:
    def test_json_safe_round_trips_datetime_numpy_and_nonfinite_floats(self):
        payload = {
            "status": "completed",
            "timestamp": datetime.now(),
            "r2": np.float64(0.87),
            "condition_number": np.float32(12.3),
            "n": np.int64(42),
            "flag": np.bool_(True),
            "worst_p": float("nan"),
            "amplitude_pct": float("inf"),
            "nested": {"arr": np.array([1.0, 2.0, 3.0])},
        }

        serialized = json.dumps(_json_safe(payload))

        # Must be valid JSON per RFC 8259 (no bare Infinity/NaN tokens).
        assert "Infinity" not in serialized
        assert "NaN" not in serialized

        round_tripped = json.loads(serialized)
        assert round_tripped["status"] == "completed"
        assert round_tripped["worst_p"] is None
        assert round_tripped["amplitude_pct"] is None
        assert round_tripped["n"] == 42
        assert round_tripped["nested"]["arr"] == [1.0, 2.0, 3.0]

    def test_send_notification_delivers_realistic_completed_payload(self):
        # No pytest-asyncio in this project's dependencies; drive the
        # coroutine directly with asyncio.run rather than adding a new
        # test-only dependency.
        from modules.websocket_notifier import WebSocketNotifier

        class FakeWebSocket:
            def __init__(self):
                self.sent = []

            async def send_text(self, text):
                self.sent.append(text)

        notifier = WebSocketNotifier()
        notifier.active_connections = []
        ws = FakeWebSocket()
        notifier.active_connections.append(ws)

        try:
            payload = {
                "status": "completed",
                "timestamp": datetime.now(),
                "model_metrics": {
                    "r2": np.float64(0.9),
                    "condition_number": np.float64(15.2),
                    "f_pvalue": np.float64(0.001),
                },
            }
            asyncio.run(notifier.send_notification(payload))

            assert len(ws.sent) == 1
            decoded = json.loads(ws.sent[0])
            assert decoded["status"] == "completed"
        finally:
            notifier.active_connections = []


class TestAvaliandoDomainPreFilter:
    def test_transformation_invalid_for_avaliando_value_is_excluded_from_search(self):
        """
        idade is strictly positive in the training sample (so ln/sqrt are
        domain-valid options there), but the avaliando's idade is 0 - domain
        invalid for ln/sqrt/inv_sqrt. Those options must be pre-filtered out
        of the search space entirely, not silently fail per-candidate later.
        """
        np.random.seed(1)
        n = 30
        idade = np.random.uniform(1, 50, n)
        y = 100 - 2 * idade + np.random.normal(0, 1, n)
        df = pd.DataFrame({"idade": idade, "y": y})

        finder = OptimalCombinationFinder()
        transformed_df, vars_options = finder._build_variable_options(
            df, ["idade"], avaliando_raw={"idade": 0.0}
        )

        for opt in vars_options["idade"]:
            assert not opt.startswith("ln("), "ln(idade) must be excluded: ln(0) is undefined"
            assert not opt.startswith("sqrt("), "sqrt(idade) must be excluded: Transformer rejects sqrt at value <= 0, and 0 is not > 0"
            assert not opt.startswith("inv_sqrt("), "inv_sqrt(idade) must be excluded: inv_sqrt(0) is undefined"
            assert not opt.startswith("inverse("), "inverse(idade) must be excluded: 1/0 is undefined"
            assert not opt.startswith("inv_sqr("), "inv_sqr(idade) must be excluded: 1/0**2 is undefined"

        # Linear must still be offered.
        assert "idade" in vars_options["idade"]

    def test_full_search_does_not_crash_and_does_not_bottom_rank_on_zero_avaliando(self):
        """
        saldo is a variable that takes both negative and positive (but
        never zero) values in the training sample, so ln/sqrt/inv_sqrt are
        never domain-valid options for it at all (they fail the training
        column's own domain check) while inverse/inv_sqr ARE domain-valid
        training-column options (only "not equal to zero" is required).
        The avaliando's saldo is exactly 0: within the sample's [min, max]
        range (so item 4 should legitimately reach the top grau, no
        extrapolation at all) yet domain-invalid specifically for
        inverse/inv_sqr (1/0 is undefined). Pre-fix, a candidate that
        happened to pick inverse(saldo) or inv_sqr(saldo) would silently
        fail in add_precision_and_extrapolation and get item 4 stuck at the
        provisional 0 - while a candidate using saldo linearly would not.
        Post-fix, inverse/inv_sqr must never be offered as options for
        saldo at all, so every candidate's item 4 is computed consistently.
        """
        np.random.seed(2)
        n = 30
        saldo = np.concatenate([
            np.random.uniform(-20, -1, n // 2),
            np.random.uniform(1, 20, n // 2),
        ])
        y = 100 + 3 * saldo + np.random.normal(0, 1, n)
        df = pd.DataFrame({"saldo": saldo, "y": y})

        finder = OptimalCombinationFinder()
        result = finder.find_best_model(
            df, "y", degree=1, avaliando_raw={"saldo": 0.0}
        )

        assert result.success is True
        assert result.best_model is not None
        vr = result.best_model.validation_result
        assert vr is not None
        # No swallowed-exception warning should have been recorded: the
        # domain-invalid options were pre-filtered out of the search space,
        # so add_precision_and_extrapolation's except branch should never
        # have been hit for the winning candidate.
        assert not any(
            "Não foi possível calcular grau de precisão" in w for w in vr.warnings
        )
        # item 4 must have been FINALIZED, and since saldo=0 falls squarely
        # within [sample_min, sample_max] (no extrapolation at all), it
        # should reach the top grau (3) - not the provisional/failure 0
        # that a swallowed inverse(saldo)/inv_sqr(saldo) exception would
        # have left it at.
        item4 = next(i for i in vr.item_scores if i.item == 4)
        assert item4.grau_achieved == 3
        assert vr.grau_fundamentacao is not None


class TestExhaustiveDisclosurePropagation:
    def test_pdf_report_accepts_exhaustive_fields_without_error(self):
        np.random.seed(3)
        n = 20
        x1 = np.linspace(1, 10, n)
        y = 3 * x1 + np.random.normal(0, 0.5, n)
        df = pd.DataFrame({"x1": x1, "y": y})

        finder = OptimalCombinationFinder()
        result = finder.find_best_model(
            df, "y", degree=1, avaliando_raw={"x1": float(np.median(x1))}
        )
        assert result.success is True

        pdf_bytes = ResultsGenerator.generate_pdf_report(
            result.best_model,
            target_col="y",
            avaliando_raw={"x1": float(np.median(x1))},
            exhaustive=result.exhaustive,
            combinations_tested=result.combinations_tested,
            search_message=result.message,
        )
        assert pdf_bytes is not None
        assert pdf_bytes[:4] == b"%PDF"
