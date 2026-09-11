import os
import sys

import pytest

from modules.job_store import JobStore
from modules.project_store import ProjectStore
from modules.websocket_notifier import WebSocketNotifier

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture
def store_root(tmp_path):
    root = tmp_path / "c11-store"
    root.mkdir()
    return root


@pytest.fixture
def job_store(store_root):
    JobStore.reset_default()
    WebSocketNotifier().reset_connections()
    store = JobStore.configure_default(store_root, recover_abandoned=True)
    yield store
    WebSocketNotifier().reset_connections()
    JobStore.reset_default()


@pytest.fixture
def project_store(job_store):
    return ProjectStore(job_store.root)


def sample_snapshot(job_id, project_id=None):
    return {
        "schema_version": "MP/1",
        "job_id": job_id,
        "project_id": project_id,
        "input_sha256": "a" * 64,
        "code_sha": "b" * 40,
        "reference_date": None,
        "generated_at": "2026-09-11T00:00:00+00:00",
        "target": {"column": "preco", "unit": "BRL", "estimand": "subject_value"},
        "value": {
            "point": 1234.5,
            "mean_ci80": {"lower": 1000.0, "upper": 1500.0},
            "prediction_interval": None,
            "arbitration_interval": None,
            "admissible_interval": None,
        },
        "sample": {
            "received": 10,
            "observed_target": 10,
            "prepared": 10,
            "used": 10,
            "excluded": 0,
            "used_row_ids": ["r1"],
            "excluded_row_ids": [],
        },
        "validation": {
            "fundamentacao": {"grade": None, "points": None},
            "precisao": {"status": "not_computed", "grade": None},
            "statistical": {},
            "documentary": {},
            "issuance": {"status": "draft", "reasons": ["c11 persistence fixture"]},
        },
        "issues": [],
        "model": {"spec": "ols"},
        "search": {},
        "alternatives": [],
        "next_actions": [],
        "provenance": {"origin": "tests.c11_persistence"},
    }
