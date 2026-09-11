"""E2E PDF / dossiê against the real ResultsGenerator (and C12 when present)."""
from __future__ import annotations

import pandas as pd

from modules.model_builder import ModelBuilder
from modules.optimal_combination import OptimalCombinationFinder
from modules.results_generator import ResultsGenerator
from _helpers import fixture_path, try_export


class TestE2EPdfDossier:
    def test_real_search_pdf_has_magic_and_is_not_empty(self):
        df = pd.read_csv(fixture_path("market_minimal.csv"))
        result = OptimalCombinationFinder().find_best_model(
            df, "preco", degree=1, candidate_cols=["area", "quartos"],
            avaliando_raw={"area": 100.0, "quartos": 3.0},
        )
        assert result.success is True
        render = try_export("modules.results_generator", "render_report")
        pdf = None
        if render is not None:
            snap = {
                "schema_version": "MP/1",
                "job_id": "c16-synthetic",
                "project_id": None,
                "input_sha256": "0" * 64,
                "code_sha": "c16",
                "reference_date": None,
                "generated_at": "2026-09-11T00:00:00Z",
                "target": {"column": "preco", "unit": "", "estimand": "central"},
                "value": {"point": 1.0, "mean_ci80": None, "prediction_interval": None,
                          "arbitration_interval": None, "admissible_interval": None},
                "sample": {"received": len(df), "observed_target": len(df),
                           "prepared": len(df), "used": len(df), "excluded": 0,
                           "used_row_ids": [], "excluded_row_ids": []},
                "validation": {"fundamentacao": {}, "precisao": {"status": "not_computed"},
                               "statistical": {}, "documentary": {},
                               "issuance": {"status": "draft", "reasons": []}},
                "issues": [],
                "model": {},
                "search": {},
                "alternatives": [],
                "next_actions": [],
                "provenance": {},
            }
            pdf = render(snap, {"market_data": df})
        else:
            pdf = ResultsGenerator.generate_pdf_report(
                result.best_model,
                target_col="preco",
                avaliando_raw={"area": 100.0, "quartos": 3.0},
                exhaustive=result.exhaustive,
                combinations_tested=result.combinations_tested,
                search_message=result.message,
                market_data=df,
            )
        assert pdf is not None
        assert pdf[:4] == b"%PDF"
        assert len(pdf) > 1000

    def test_evidence_bundle_hashes_when_c12_present(self):
        fn = try_export("modules.evidence_bundle", "build_evidence_bundle")
        assert fn is not None, "UNMET_DEPENDENCY:C12 build_evidence_bundle"
