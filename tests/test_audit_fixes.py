"""
Transversal regression tests owned by C16.

Oracles are independent (math.sqrt, RFC 8259 JSON, PDF magic). They do
not copy the audited Transformer's `<= 0` sqrt rejection.
"""
import asyncio
import json
import math
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from modules.websocket_notifier import _json_safe
from modules.optimal_combination import OptimalCombinationFinder
from modules.results_generator import ResultsGenerator
from modules.transformations import Transformer


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
        from modules.websocket_notifier import WebSocketNotifier

        class FakeWebSocket:
            def __init__(self):
                self.sent = []

            async def send_text(self, text):
                self.sent.append(text)

        notifier = WebSocketNotifier()
        notifier.reset_connections()
        ws = FakeWebSocket()
        notifier._ensure_state()
        notifier._by_job.setdefault("job_ws_scope", []).append(ws)
        notifier._ws_job[id(ws)] = "job_ws_scope"
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
            # Unscoped payloads are not broadcast; results are read via GET /jobs/{id}/result.
            assert len(ws.sent) == 0
            payload_scoped = dict(payload)
            payload_scoped["job_id"] = "job_ws_scope"
            asyncio.run(notifier.send_notification(payload_scoped))
            assert len(ws.sent) == 1
            decoded = json.loads(ws.sent[0])
            assert decoded.get("job_id") == "job_ws_scope" or decoded.get("status") in {
                "completed",
                "progress",
                "error",
            }
        finally:
            notifier.active_connections = []


class TestSqrtZeroIsDefined:
    """C16-A02 / F12: sqrt(0) is 0. The inherited assertion that required
    rejecting sqrt at value <= 0 copied a defective domain rule and is
    corrected here to mathematical truth.
    """

    def test_apply_transformation_sqrt_of_zero_is_zero(self):
        series = pd.Series([0.0, 1.0, 4.0])
        transformed, success = Transformer.apply_transformation(series, "sqrt")
        expected = [math.sqrt(0.0), math.sqrt(1.0), math.sqrt(4.0)]
        assert success is True
        np.testing.assert_allclose(
            np.asarray(transformed, dtype=float), expected, rtol=0, atol=0
        )

    def test_search_space_keeps_sqrt_when_avaliando_is_zero(self):
        np.random.seed(1)
        n = 30
        idade = np.random.uniform(1, 50, n)
        y = 100 - 2 * idade + np.random.normal(0, 1, n)
        df = pd.DataFrame({"idade": idade, "y": y})

        finder = OptimalCombinationFinder()
        _transformed_df, vars_options = finder._build_variable_options(
            df, ["idade"], avaliando_raw={"idade": 0.0}
        )

        options = vars_options["idade"]
        assert "idade" in options
        assert any(opt.startswith("sqrt(") for opt in options), (
            "sqrt(0) == 0 is defined; sqrt must remain in the search space "
            "when the avaliando value is 0"
        )
        assert not any(opt.startswith("ln(") for opt in options), (
            "ln(0) is undefined; ln must stay excluded"
        )
        assert not any(opt.startswith("inv_sqrt(") for opt in options)
        assert not any(opt.startswith("inverse(") for opt in options)
        assert not any(opt.startswith("inv_sqr(") for opt in options)


class TestAvaliandoDomainPreFilter:
    def test_ln_and_inverse_invalid_for_zero_avaliando_are_excluded(self):
        np.random.seed(1)
        n = 30
        idade = np.random.uniform(1, 50, n)
        y = 100 - 2 * idade + np.random.normal(0, 1, n)
        df = pd.DataFrame({"idade": idade, "y": y})

        finder = OptimalCombinationFinder()
        _transformed_df, vars_options = finder._build_variable_options(
            df, ["idade"], avaliando_raw={"idade": 0.0}
        )

        for opt in vars_options["idade"]:
            assert not opt.startswith("ln("), "ln(idade) must be excluded: ln(0) is undefined"
            assert not opt.startswith("inv_sqrt("), "inv_sqrt(0) is undefined"
            assert not opt.startswith("inverse("), "inverse(0) is undefined"
            assert not opt.startswith("inv_sqr("), "inv_sqr(0) is undefined"

        assert "idade" in vars_options["idade"]

    def test_full_search_does_not_crash_and_does_not_bottom_rank_on_zero_avaliando(self):
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
        assert not any(
            "Não foi possível calcular grau de precisão" in w for w in vr.warnings
        )
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
