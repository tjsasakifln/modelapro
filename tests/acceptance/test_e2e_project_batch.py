"""E2E project revision + batch against MP/1 stores when present."""
from __future__ import annotations

from _helpers import try_export


class TestE2EProjectBatch:
    def test_project_revision_roundtrip(self):
        Store = try_export("modules.project_store", "ProjectStore")
        assert Store is not None, "UNMET_DEPENDENCY:C11 ProjectStore"
        store = Store()
        revision_id = store.save_revision("proj-c16", {
            "schema_version": "MP/1",
            "project_id": "proj-c16",
            "revision_id": None,
            "input_sha256": "0" * 64,
            "dataset_sha256": "1" * 64,
            "request_spec": {"schema_version": "MP/1", "target_col": "preco"},
            "feature_schema": {},
            "encoder_state": {},
            "model_spec": {},
            "model_state": {},
            "model_scope": "population_model",
            "subject_constraints": {},
            "domain": {},
            "sample_ledger": {},
            "normative_version": "pending",
            "artifact_refs": {},
            "provenance": {"synthetic": True},
        })
        loaded = store.load_revision("proj-c16", revision_id)
        assert loaded is not None
        assert loaded.get("project_id") == "proj-c16"

    def test_batch_returns_per_subject_assessment(self):
        evaluate_batch = try_export("modules.valuation_batch", "evaluate_batch")
        assert evaluate_batch is not None, "UNMET_DEPENDENCY:C14 evaluate_batch"
        result = evaluate_batch(
            {"schema_version": "MP/1", "project_id": "proj-c16", "revision_id": "r1"},
            [{"subject_id": "s1", "area": 100}, {"subject_id": "s2", "area": 120}],
            {"schema_version": "MP/1", "target_col": "preco"},
        )
        assessments = result.get("assessments") if isinstance(result, dict) else getattr(result, "assessments", None)
        assert assessments is not None
        assert len(list(assessments)) == 2
