import io
import logging
import threading

import pytest

from modules.config_manager import Config, default_runtime_root, validate_config
from modules.local_task_runner import LocalTaskRunner
from modules.logging_manager import DropClientDataFilter


def test_runtime_root_is_per_user_and_shared_host_is_rejected():
    assert "modelapro" in default_runtime_root().lower()
    with pytest.raises(ValueError, match="Non-loopback"):
        validate_config(Config(API_HOST="0.0.0.0", DATA_DIR="x", UPLOAD_DIR="x", REPORTS_DIR="x", JOBS_DIR="x", PROJECTS_DIR="x", LOG_DIR="x"))


def test_log_filter_redacts_message_arguments_and_extras():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(DropClientDataFilter())
    logger = logging.getLogger("test.c04.redaction")
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.info("contact=%s cpf=%s token=%s", "ana@example.com", "123.456.789-09", "secret-value", extra={"payload": "private"})
    output = stream.getvalue()
    assert "ana@example.com" not in output and "123.456.789-09" not in output
    assert "secret-value" not in output and "[REDACTED]" in output


def test_runner_enforces_queue_and_passes_cooperative_deadline(tmp_path):
    from modules.job_store import JobStore

    job_store = JobStore(tmp_path / "store", recover_abandoned=False)
    jobs = [job_store.create() for _ in range(2)]
    runner = LocalTaskRunner(job_store, max_workers=1, max_queue=0, min_free_disk_bytes=0, recover_abandoned=False)
    release = threading.Event()
    runner.submit(jobs[0]["job_id"], lambda deadline_monotonic: (release.wait(), {"outcome": "cancelled"})[1])
    with pytest.raises(RuntimeError, match="queue is full"):
        runner.submit(jobs[1]["job_id"], lambda: None)
    release.set()
    runner.shutdown(wait=True)
