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
        from tests.c14_batch.conftest import make_frozen_project, make_request_spec, make_subject

        frozen = make_frozen_project(project_id="proj-c16")
        result = evaluate_batch(
            frozen,
            [
                make_subject("s1", area=100.0, bairro="Centro"),
                make_subject("s2", area=120.0, bairro="Sul"),
            ],
            make_request_spec(),
        )
        assessments = result.get("assessments") if isinstance(result, dict) else getattr(result, "assessments", None)
        if assessments is None and isinstance(result, dict):
            assessments = result.get("items")
        assert assessments is not None
        assert len(list(assessments)) == 2
        points = [
            (item.get("value") or {}).get("point") if isinstance(item, dict) else None
            for item in assessments
        ]
        assert all(p is not None for p in points)
