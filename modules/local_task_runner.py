"""Bounded in-process runner for local jobs with cooperative cancel.

Identity must already be persisted in JobStore before ``submit``. There is
no mid-search resume: an abandoned ``running`` job becomes ``interrupted``.
"""

from __future__ import annotations

import inspect
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional, Set

from modules.job_store import (
    InvalidTransition,
    JobNotFound,
    JobStore,
    StaleState,
    TERMINAL_STATES,
    make_issue,
)

WorkFn = Callable[..., Any]


def _accepts_cancel_requested(fn: WorkFn) -> bool:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    for param in signature.parameters.values():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True
    return "cancel_requested" in signature.parameters


def _accepts_argument(fn: WorkFn, name: str) -> bool:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    return accepts_kwargs or name in signature.parameters


class RunnerClosed(RuntimeError):
    pass


class LocalTaskRunner:
    """Run submitted callables with a concurrency cap and cooperative cancel.

    Public MP/1 methods: ``submit(job_id, callable)``, ``cancel(job_id)``.
    """

    def __init__(
        self,
        job_store: Optional[JobStore] = None,
        *,
        max_workers: int = 1,
        max_queue: int = 8,
        timeout_seconds: Optional[float] = None,
        min_free_disk_bytes: int = 64 * 1024 * 1024,
        recover_abandoned: bool = True,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        if max_queue < 0 or min_free_disk_bytes < 0:
            raise ValueError("max_queue and min_free_disk_bytes must be non-negative")
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive or None")
        self.store = job_store if job_store is not None else JobStore.default()
        self._max_workers = max_workers
        self._max_queue = max_queue
        self._timeout_seconds = timeout_seconds
        self._min_free_disk_bytes = min_free_disk_bytes
        self._lock = threading.RLock()
        self._accepting = True
        self._flags: Dict[str, threading.Event] = {}
        self._running: Set[str] = set()
        self._submitted: Set[str] = set()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="c11-runner",
        )
        if recover_abandoned:
            recover = getattr(self.store, "recover_on_open", None)
            if callable(recover):
                recover(live_job_ids=self.live_job_ids())
            else:
                self.store.recover_abandoned(live_job_ids=self.live_job_ids())

    def submit(self, job_id: str, callable: WorkFn) -> str:
        """Queue work for an already-persisted job. Does not create identity."""
        if callable is None or not hasattr(callable, "__call__"):
            raise TypeError("callable is required")
        with self._lock:
            if not self._accepting:
                raise RunnerClosed("runner is shut down")
            job = self.store.get(job_id)
            if job is None:
                raise JobNotFound(job_id)
            if job["state"] == "cancelled":
                return job_id
            if job["state"] != "queued":
                raise InvalidTransition(
                    f"submit requires queued job, found {job['state']!r}"
                )
            if job_id in self._submitted:
                raise InvalidTransition(f"job {job_id} is already submitted")
            if len(self._submitted) >= self._max_workers + self._max_queue:
                raise RuntimeError("local job queue is full")
            if shutil.disk_usage(self.store.root).free < self._min_free_disk_bytes:
                raise RuntimeError("insufficient free disk space for a new local job")
            flag = self._flags.setdefault(job_id, threading.Event())
            if flag.is_set():
                try:
                    self.store.update_transition(job_id, "queued", "cancelled")
                except (StaleState, InvalidTransition):
                    pass
                return job_id
            self._submitted.add(job_id)
            self._executor.submit(self._run, job_id, callable)
        return job_id

    def cancel(self, job_id: str) -> Dict[str, Any]:
        job = self.store.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        with self._lock:
            flag = self._flags.setdefault(job_id, threading.Event())
            flag.set()
        if job["state"] == "queued":
            try:
                updated = self.store.update_transition(job_id, "queued", "cancelled")
                return updated
            except StaleState:
                job = self.store.get(job_id) or job
            except InvalidTransition:
                job = self.store.get(job_id) or job
        if job["state"] == "succeeded" or job.get("calculation_finished"):
            self._record_cancel_after_completion(job_id)
            return self.store.get(job_id) or job
        if job["state"] in TERMINAL_STATES:
            return job
        return self.store.get(job_id) or job

    def cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            flag = self._flags.get(job_id)
        if flag and flag.is_set():
            return True
        job = self.store.get(job_id)
        return bool(job and job.get("state") == "cancelled")

    def is_cancelled(self, job_id: str) -> bool:
        return self.cancel_requested(job_id)

    def cancelled_ids(self) -> Set[str]:
        with self._lock:
            flagged = {job_id for job_id, flag in self._flags.items() if flag.is_set()}
        return flagged

    def live_job_ids(self) -> Set[str]:
        with self._lock:
            return set(self._running)

    def shutdown(self, *, wait: bool = True, cancel_inflight: bool = False) -> None:
        with self._lock:
            self._accepting = False
            inflight = list(self._submitted)
        if cancel_inflight:
            for job_id in inflight:
                try:
                    self.cancel(job_id)
                except JobNotFound:
                    pass
        self._executor.shutdown(wait=wait)
        self.store.recover_abandoned(live_job_ids=self.live_job_ids())

    def _run(self, job_id: str, fn: WorkFn) -> None:
        try:
            if self.cancel_requested(job_id):
                self._try_transition(
                    job_id,
                    "queued",
                    "cancelled",
                    issues=[
                        make_issue(
                            code="cancelled_before_start",
                            message="Job cancelled while queued; callable was not started.",
                            origin="c11.runner",
                            affected_ids=[job_id],
                        )
                    ],
                )
                return
            try:
                self.store.update_transition(job_id, "queued", "running")
            except (StaleState, InvalidTransition):
                return
            with self._lock:
                self._running.add(job_id)
            kwargs = {}
            if _accepts_cancel_requested(fn):
                kwargs["cancel_requested"] = lambda: self.cancel_requested(job_id)
            started = time.monotonic()
            deadline = started + self._timeout_seconds if self._timeout_seconds else None
            if deadline is not None and _accepts_argument(fn, "deadline_monotonic"):
                kwargs["deadline_monotonic"] = deadline
            try:
                result = fn(**kwargs) if kwargs else fn()
            except Exception as exc:
                if self.cancel_requested(job_id):
                    self._finish_cancelled(job_id)
                else:
                    self._try_transition(
                        job_id,
                        "running",
                        "failed",
                        issues=[
                            make_issue(
                                code="callable_error",
                                message=f"Job callable raised {type(exc).__name__}: {exc}",
                                severity="error",
                                origin="c11.runner",
                                affected_ids=[job_id],
                            )
                        ],
                    )
                return
            if deadline is not None and time.monotonic() > deadline:
                # Python cannot safely kill a running worker thread.  A callable
                # accepting deadline_monotonic can stop itself; otherwise record a
                # bounded failure once it returns, preserving persisted evidence.
                self._try_transition(
                    job_id, "running", "failed",
                    issues=[make_issue(
                        code="job_timeout",
                        severity="error",
                        origin="c11.runner",
                        affected_ids=[job_id],
                        message="Job exceeded its configured cooperative timeout.",
                        evidence={"timeout_seconds": self._timeout_seconds},
                    )],
                )
                return
            self._finish_from_result(job_id, result)
        finally:
            with self._lock:
                self._running.discard(job_id)
                self._submitted.discard(job_id)

    def _finish_from_result(self, job_id: str, result: Any) -> None:
        job = self.store.get(job_id)
        if job is None or job["state"] in TERMINAL_STATES:
            if job is not None and self.cancel_requested(job_id) and job["state"] == "succeeded":
                self._record_cancel_after_completion(job_id)
            return
        outcome = None
        if isinstance(result, dict):
            outcome = result.get("outcome")
        cancelled = self.cancel_requested(job_id)
        snapshot = self.store.get_snapshot(job_id)
        if cancelled and job.get("calculation_finished") and snapshot is not None:
            self._try_transition(job_id, "running", "succeeded")
            self._record_cancel_after_completion(job_id)
            return
        if cancelled:
            self._finish_cancelled(job_id)
            return
        if outcome == "failed":
            self._try_transition(job_id, "running", "failed")
            return
        if outcome == "cancelled":
            self._finish_cancelled(job_id)
            return
        if snapshot is not None or outcome == "succeeded" or job.get("calculation_finished"):
            if snapshot is None and outcome == "succeeded":
                self._try_transition(
                    job_id,
                    "running",
                    "failed",
                    issues=[
                        make_issue(
                            code="succeeded_without_snapshot",
                            message="Callable claimed success without a stored snapshot.",
                            severity="error",
                            origin="c11.runner",
                            affected_ids=[job_id],
                        )
                    ],
                )
                return
            self._try_transition(job_id, "running", "succeeded")
            return
        self._try_transition(
            job_id,
            "running",
            "failed",
            issues=[
                make_issue(
                    code="callable_returned_without_terminal_state",
                    message="Callable returned while running without a snapshot or outcome.",
                    severity="error",
                    origin="c11.runner",
                    affected_ids=[job_id],
                )
            ],
        )

    def _finish_cancelled(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None:
            return
        if job.get("calculation_finished") and job["state"] == "running":
            issues = [
                make_issue(
                    code="cancel_after_calculation",
                    message="Cancel requested after calculation had already finished.",
                    origin="c11.runner",
                    affected_ids=[job_id],
                    evidence={"calculation_finished": True},
                )
            ]
            if self.store.get_snapshot(job_id) is not None:
                self._try_transition(job_id, "running", "succeeded", issues=issues)
                return
        self._try_transition(
            job_id,
            "running",
            "cancelled",
            issues=[
                make_issue(
                    code="cancelled_running",
                    message="Cooperative cancel stopped the job between safe units.",
                    origin="c11.runner",
                    affected_ids=[job_id],
                    evidence={
                        "calculation_finished": bool(job.get("calculation_finished")),
                    },
                )
            ],
        )

    def _record_cancel_after_completion(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None:
            return
        if not (job["state"] == "succeeded" or job.get("calculation_finished")):
            return
        try:
            self.store.append_issues(
                job_id,
                [
                    make_issue(
                        code="cancel_after_completion",
                        message="Cancel requested after the job had already succeeded.",
                        origin="c11.runner",
                        affected_ids=[job_id],
                        evidence={"calculation_finished": True},
                    )
                ],
            )
        except JobNotFound:
            return

    def _try_transition(
        self,
        job_id: str,
        expected: str,
        new_state: str,
        issues: Optional[list] = None,
    ) -> None:
        patch = {"issues": issues} if issues else None
        try:
            self.store.update_transition(job_id, expected, new_state, patch=patch)
        except (StaleState, InvalidTransition, JobNotFound):
            return
