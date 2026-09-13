"""Labeled MP/1 contract simulators. Tests only — never imported by production."""

from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, List, Optional

from modules.result_contract import SCHEMA_VERSION, empty_value_block, make_issue

SIMULATOR_MARK = "C10_CONTRACT_SIMULATOR"


def label_simulator(name: str):
    def deco(fn: Callable) -> Callable:
        fn.contract_simulator = True
        fn.simulator_label = f"{SIMULATOR_MARK}:{name}"
        return fn

    return deco


class CallLog:
    def __init__(self) -> None:
        self.events: List[tuple] = []

    def record(self, name: str, **kwargs: Any) -> None:
        self.events.append((name, kwargs))

    def names(self) -> List[str]:
        return [name for name, _ in self.events]

    def first(self, name: str) -> Optional[dict]:
        for event_name, payload in self.events:
            if event_name == name:
                return payload
        return None


class LabeledJobStore:
    contract_simulator = True
    simulator_label = f"{SIMULATOR_MARK}:JobStore"

    def __init__(self) -> None:
        self.jobs: Dict[str, dict] = {}
        self.snapshots: Dict[str, dict] = {}
        self.artifacts: Dict[tuple, bytes] = {}
        self.idempotency: Dict[str, str] = {}
        self.transitions: List[tuple] = []

    def create(self, idempotency_key=None, project_id=None, payload=None):
        if idempotency_key and idempotency_key in self.idempotency:
            job_id = self.idempotency[idempotency_key]
            job = self.jobs[job_id]
            return {"job_id": job_id, "state": job["state"], "created": False}
        job_id = str(uuid.uuid4())
        access_token = f"C10_TEST_TOKEN_{uuid.uuid4()}"
        self.jobs[job_id] = {
            "schema_version": SCHEMA_VERSION,
            "job_id": job_id,
            "project_id": project_id,
            "state": "queued",
            "stage": None,
            "progress": None,
            "result_available": False,
            "artifact_states": {},
            "issues": [],
            "calculation_state": None,
            "access_token": access_token,
            "payload": payload or {},
        }
        if idempotency_key:
            self.idempotency[idempotency_key] = job_id
        return {
            "job_id": job_id,
            "state": "queued",
            "created": True,
            "access_token": access_token,
        }

    def get(self, job_id):
        job = self.jobs.get(job_id)
        return dict(job) if job is not None else None

    def get_by_idempotency_key(self, key):
        job_id = self.idempotency.get(key)
        return self.get(job_id) if job_id else None

    def verify_access(self, job_id, access_token):
        job = self.jobs.get(job_id)
        return bool(job and job.get("access_token") == access_token)

    def update_transition(self, job_id, expected_state, new_state, patch=None):
        job = self.jobs[job_id]
        if job["state"] != expected_state:
            if job["state"] == new_state:
                if patch:
                    job.update(patch)
                return dict(job)
            raise RuntimeError(
                f"invalid transition {job['state']} (expected {expected_state}) -> {new_state}"
            )
        job["state"] = new_state
        if patch:
            job.update(patch)
        self.transitions.append((job_id, expected_state, new_state))
        return dict(job)

    def save_snapshot(self, job_id, snapshot):
        self.snapshots[job_id] = snapshot
        job = self.jobs[job_id]
        job["result_available"] = True

    def get_snapshot(self, job_id):
        return self.snapshots.get(job_id)

    def save_artifact(self, job_id, name, data):
        self.artifacts[(job_id, name)] = data

    def get_artifact(self, job_id, name):
        return self.artifacts.get((job_id, name))

    def list_by_state(self, state):
        return [dict(job) for job in self.jobs.values() if job.get("state") == state]

    def interrupt_stale_running(self):
        n = 0
        for job in self.jobs.values():
            if job.get("state") == "running":
                job["state"] = "interrupted"
                job["stage"] = "interrupted"
                job.setdefault("issues", []).append(
                    make_issue(
                        "INTERRUPTED_ON_RESTART",
                        "Job was running when the process restarted",
                        origin="c10.doubles",
                    )
                )
                n += 1
        return n


class LabeledProjectStore:
    contract_simulator = True
    simulator_label = f"{SIMULATOR_MARK}:ProjectStore"

    def __init__(self) -> None:
        self.projects: Dict[str, List[str]] = {}
        self.revisions: Dict[tuple, dict] = {}

    def save_revision(self, project_id, revision_payload):
        rev = str(uuid.uuid4())
        self.projects.setdefault(project_id, []).append(rev)
        payload = dict(revision_payload)
        self.revisions[(project_id, rev)] = payload
        return rev

    def load_revision(self, project_id, revision_id=None):
        if project_id not in self.projects or not self.projects[project_id]:
            return None
        if revision_id is None:
            revision_id = self.projects[project_id][-1]
        return self.revisions.get((project_id, revision_id))

    def list(self):
        return [
            {"project_id": pid, "revision_ids": list(revs)}
            for pid, revs in self.projects.items()
        ]


class LabeledTaskRunner:
    contract_simulator = True
    simulator_label = f"{SIMULATOR_MARK}:LocalTaskRunner"

    def __init__(self, auto_run: bool = True) -> None:
        self.auto_run = auto_run
        self.queue: Dict[str, Callable] = {}
        self.submitted: List[str] = []
        self._cancelled = set()

    def submit(self, job_id, callable_job):
        self.submitted.append(job_id)
        self.queue[job_id] = callable_job
        if self.auto_run and job_id not in self._cancelled:
            callable_job()

    def run(self, job_id):
        if job_id in self._cancelled:
            return
        self.queue[job_id]()

    def cancel(self, job_id):
        self._cancelled.add(job_id)
        return True

    def is_cancelled(self, job_id):
        return job_id in self._cancelled

    def cancelled_ids(self):
        return set(self._cancelled)


def _parse_csv(file_bytes: bytes):
    text = file_bytes.decode("utf-8")
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    header = [c.strip() for c in lines[0].split(",")]
    rows = []
    for line in lines[1:]:
        parts = [p.strip() for p in line.split(",")]
        row = {}
        for key, value in zip(header, parts):
            try:
                row[key] = float(value) if "." in value or value.isdigit() else value
            except ValueError:
                row[key] = value
        rows.append(row)
    return header, rows


def make_peers(log: CallLog, *, point: float = 150000.0, pdf_error: bool = False, ingest_error: bool = False):
    """Return a full labeled peer map. Distinct from real imported callables."""

    @label_simulator("ingest_market")
    def ingest_market(file_bytes, filename, request_spec):
        log.record(
            "ingest_market",
            filename=filename,
            target_col=request_spec.get("target_col"),
            roles=dict(request_spec.get("roles") or {}),
            candidate_cols=request_spec.get("candidate_cols"),
        )
        if ingest_error:
            return {
                "schema_version": SCHEMA_VERSION,
                "raw_frame": None,
                "parsed_frame": None,
                "column_map": {},
                "row_ledger": {},
                "input_sha256": "0" * 64,
                "issues": [make_issue("INGEST_FAIL", "labeled ingest failure", origin="c10.doubles")],
            }
        header, rows = _parse_csv(file_bytes)
        row_ids = [f"r{i+1}" for i in range(len(rows))]
        return {
            "schema_version": SCHEMA_VERSION,
            "raw_frame": rows,
            "parsed_frame": rows,
            "column_map": {name: name for name in header},
            "row_ledger": {
                "received": len(rows),
                "observed_target": len(rows),
                "rows": [
                    {
                        "row_id": rid,
                        "observed_target": True,
                        "disposition": "kept",
                        "missing_before": [],
                        "changes": [],
                        "reasons": [],
                    }
                    for rid in row_ids
                ],
            },
            "input_sha256": __import__("hashlib").sha256(file_bytes).hexdigest(),
            "issues": [],
            "row_ids": row_ids,
        }

    @label_simulator("fit_dataset")
    def fit_dataset(input_bundle, request_spec, train_row_ids=None):
        log.record("fit_dataset", train_row_ids=train_row_ids)
        rows = list(input_bundle.get("parsed_frame") or [])
        row_ids = list(input_bundle.get("row_ids") or [f"r{i+1}" for i in range(len(rows))])
        if train_row_ids is not None:
            row_ids = [str(r) for r in train_row_ids]
        return {
            "X": [{"area": r.get("area", 0)} for r in rows],
            "y": [r.get("preco") for r in rows],
            "row_ids": row_ids,
            "base_frame": rows,
            "feature_schema": {
                "version": "MP/1-test",
                "columns": {
                    "area": {
                        "original_name": "area",
                        "role": "predictor",
                        "kind": "numeric",
                        "unit": "m2",
                        "group_id": None,
                        "categories": None,
                        "reference_category": None,
                    },
                    "bairro": {
                        "original_name": "bairro",
                        "role": "predictor",
                        "kind": "categorical",
                        "unit": None,
                        "group_id": "g_bairro",
                        "categories": ["centro", "sul", "norte"],
                        "reference_category": "centro",
                    },
                },
                "groups": {"g_bairro": {"columns": ["bairro_sul", "bairro_norte"], "base_variable": "bairro"}},
                "target": {"column": "preco", "unit": ""},
            },
            "encoder_state": {"version": "MP/1-test", "fitted_on": list(row_ids)},
            "sample_ledger": {
                "used_row_ids": list(row_ids),
                "excluded_row_ids": [],
                "n_used": len(row_ids),
            },
            "issues": [],
            "dataset_sha256": "d" * 64,
        }

    @label_simulator("transform_subject")
    def transform_subject(subject_raw, feature_schema, encoder_state):
        log.record("transform_subject", subject_raw=dict(subject_raw or {}))
        return {
            "X": [{"area": subject_raw.get("area")}],
            "raw_values": dict(subject_raw or {}),
            "issues": [],
            "supported": True,
        }

    @label_simulator("search_models")
    def search_models(prepared_dataset, subject_design, request_spec, progress_callback=None, cancel_requested=None):
        log.record("search_models", n_rows=len(prepared_dataset.get("row_ids") or []))
        if cancel_requested and cancel_requested():
            from backend.worker import JobCancelled

            raise JobCancelled("cancelled in labeled search_models")
        if progress_callback:
            progress_callback(0.5)
        used = list(prepared_dataset.get("row_ids") or [])
        winner = {
            "candidate_id": "cand-1",
            "status": "fitted",
            "candidate_spec": {
                "candidate_id": "cand-1",
                "features": ["area", "bairro_sul", "bairro_norte"],
                "base_variables": ["area", "bairro"],
                "feature_groups": {"g_bairro": ["bairro_sul", "bairro_norte"]},
                "x_transformations": {"area": "identity"},
                "y_transformation": "identity",
                "intercept": True,
            },
            "model_object": None,
            "coefficients": {"const": 40000.0, "area": 1000.0},
            "feature_schema": prepared_dataset.get("feature_schema"),
            "encoder_state": prepared_dataset.get("encoder_state"),
            "used_row_ids": used,
            "excluded_row_ids": [],
            "base_frame": prepared_dataset.get("base_frame"),
            "diagnostics": {"rank": 3, "free_parameters": 3},
            "target_transform_state": {"name": "identity"},
            "model_sha256": "m" * 64,
            "issues": [],
        }
        return {
            "winner": winner,
            "alternatives": [],
            "search_audit": {
                "possible": 4,
                "generated": 4,
                "evaluated": 4,
                "rejected": 0,
                "reasons": [],
                "coverage": 1.0,
                "budget": request_spec.get("search_policy", {}).get("budget"),
                "objective": request_spec.get("search_policy", {}).get("objective"),
                "enumeration": "exhaustive_labeled",
                "ranking_complete": True,
            },
            "issues": [],
        }

    @label_simulator("evaluate_fitted")
    def evaluate_fitted(candidate_fit, subject_design, request_spec):
        log.record("evaluate_fitted", candidate_id=candidate_fit.get("candidate_id"))
        value = empty_value_block()
        value["point"] = float(point)
        value["mean_ci80"] = {"lower": float(point) * 0.9, "upper": float(point) * 1.1}
        value["arbitration_interval"] = {"lower": float(point) * 0.85, "upper": float(point) * 1.15}
        return {
            "candidate_id": candidate_fit.get("candidate_id"),
            "subject_id": "subject-1",
            "subject_raw": (subject_design or {}).get("raw_values"),
            "value": value,
            "normative": None,
            "statistical": {"r2": 0.8},
            "model_eligibility": {"status": "review_required", "reasons": ["labeled_simulator"]},
            "used_row_ids": list(candidate_fit.get("used_row_ids") or []),
            "issues": [],
        }

    @label_simulator("assess_normative")
    def assess_normative(context):
        log.record("assess_normative", has_predict=callable(context.get("predict_original")))
        return {
            "edition": "NBR 14653-2:2011",
            "rule_sources": [{"item": "table-1", "status": "pending"}],
            "verification_status": "pending",
            "fundamentacao": {"grade": 2, "points": 8, "items": []},
            "precisao": {"status": "classified", "grade": 2, "amplitude_pct": 11.0},
            "documentary": {"status": "declared", "verified": False},
            "issues": [],
        }

    @label_simulator("evaluate_procedure")
    def evaluate_procedure(input_bundle, request_spec, fit_select_predictor, seed):
        log.record("evaluate_procedure", seed=seed)
        predictor = fit_select_predictor(input_bundle.get("row_ids"), seed)
        return {"seed": seed, "predictor": predictor, "issues": []}

    @label_simulator("render_report")
    def render_report(snapshot, report_context):
        log.record(
            "render_report",
            used=list(report_context.get("used_row_ids") or []),
            reference_date=report_context.get("reference_date"),
        )
        if pdf_error:
            raise RuntimeError("labeled PDF failure")
        return b"%PDF-C10-SIMULATOR\n"

    @label_simulator("build_evidence_bundle")
    def build_evidence_bundle(snapshot, input_bundle, prepared_dataset, artifacts, output_dir):
        log.record("build_evidence_bundle", n_artifacts=len(artifacts or {}))
        return {"schema_version": SCHEMA_VERSION, "files": list((artifacts or {}).keys())}

    @label_simulator("recommend_next_actions")
    def recommend_next_actions(snapshot, feature_schema=None):
        log.record("recommend_next_actions", job_id=snapshot.get("job_id"))
        return [
            {
                "code": "review_issuance",
                "priority": "high",
                "reason": "issuance remains draft",
                "next_step": "professional_review",
                "evidence_refs": [],
                "limitations": ["labeled_simulator"],
            }
        ]

    @label_simulator("evaluate_batch")
    def evaluate_batch(frozen_project, subjects, request_spec, progress_callback=None, cancel_requested=None):
        log.record("evaluate_batch", n=len(subjects or []))
        return {
            "assessments": [{"subject_id": i, "status": "labeled"} for i, _ in enumerate(subjects or [])],
            "failures": [],
        }

    @label_simulator("fit_candidate")
    def fit_candidate(prepared_dataset, candidate_spec, request_spec):
        log.record("fit_candidate")
        raise AssertionError("fit_candidate should not be required when search returns a winner")

    return {
        "ingest_market": ingest_market,
        "fit_dataset": fit_dataset,
        "transform_subject": transform_subject,
        "search_models": search_models,
        "fit_candidate": fit_candidate,
        "evaluate_fitted": evaluate_fitted,
        "assess_normative": assess_normative,
        "evaluate_procedure": evaluate_procedure,
        "render_report": render_report,
        "build_evidence_bundle": build_evidence_bundle,
        "recommend_next_actions": recommend_next_actions,
        "evaluate_batch": evaluate_batch,
        "fit_target_transform": None,
        "transform_target": None,
        "inverse_target_prediction": None,
    }


def install_labeled_runtime(
    *,
    auto_run: bool = True,
    point: float = 150000.0,
    pdf_error: bool = False,
    ingest_error: bool = False,
    peers=None,
):
    from backend.api import bind_runtime

    log = CallLog()
    store = LabeledJobStore()
    projects = LabeledProjectStore()
    runner = LabeledTaskRunner(auto_run=auto_run)
    peer_map = peers if peers is not None else make_peers(
        log, point=point, pdf_error=pdf_error, ingest_error=ingest_error
    )
    bind_runtime(job_store=store, project_store=projects, task_runner=runner, peers=peer_map)
    return store, projects, runner, log, peer_map
