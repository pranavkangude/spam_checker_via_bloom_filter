"""In-memory background jobs for long benchmarks and experiments (B7).

A benchmark can take tens of seconds, which is too long to hold a normal
request open. start() runs the work in a daemon thread and returns a job id;
the page polls GET /api/jobs/<id> for progress and the final result.

Rules:
  * one job at a time (two benchmarks at once would distort each other's
    timings) -> a second start() raises ConflictError "JOB_RUNNING"
  * only the newest MAX_JOBS jobs are remembered
  * jobs live in memory only: restarting the server forgets them (the saved
    results stay in SQLite)
"""
from __future__ import annotations

import logging
import threading
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Callable

from services.errors import ConflictError, NotFoundError, ServiceError, ValidationError

log = logging.getLogger(__name__)

MAX_JOBS = 50
_lock = threading.Lock()
_jobs: "OrderedDict[str, dict]" = OrderedDict()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _snapshot(job: dict) -> dict:
    """Copy of the public fields (caller holds _lock)."""
    snap = {k: v for k, v in job.items() if not k.startswith("_")}
    snap["progress"] = dict(job["progress"])
    return snap


def _finish(job: dict, result=None, error=None, exc=None) -> None:
    with _lock:
        job["status"] = "error" if error else "done"
        job["result"] = result
        job["error"] = error
        job["_exc"] = exc
        job["finished_at"] = _now()


def _run(job: dict, fn: Callable) -> None:
    def progress(label: str, done: int, total: int) -> None:
        with _lock:
            job["progress"] = {"label": label, "done": done, "total": total}

    try:
        result = fn(progress)
    except ServiceError as exc:
        _finish(job, error={"code": exc.code, "message": exc.message}, exc=exc)
    except ValueError as exc:
        err = ValidationError(str(exc))
        _finish(job, error={"code": err.code, "message": err.message}, exc=err)
    except Exception as exc:                        # unexpected: log it, keep the server alive
        log.exception("Job %s failed", job["job_id"])
        _finish(job, error={"code": "INTERNAL_ERROR",
                            "message": "The job failed. Check the terminal."}, exc=exc)
    else:
        with _lock:
            job["progress"]["done"] = job["progress"]["total"]
        _finish(job, result=result)


def start(kind: str, fn: Callable, wait: bool = False) -> dict:
    """Run fn(progress) in the background and return the job snapshot.

    fn receives progress(label, done, total) and returns the JSON-ready result.
    With wait=True the call blocks until the job ends and re-raises its error,
    so a caller can treat it like a normal synchronous call.
    """
    with _lock:
        if any(j["status"] == "running" for j in _jobs.values()):
            raise ConflictError(
                "Another benchmark or experiment is still running; wait for it to finish",
                code="JOB_RUNNING",
            )
        job = {
            "job_id": uuid.uuid4().hex[:12], "kind": kind, "status": "running",
            "progress": {"label": "starting", "done": 0, "total": 0},
            "result": None, "error": None, "created_at": _now(), "finished_at": None,
            "_exc": None,
        }
        thread = threading.Thread(target=_run, args=(job, fn), daemon=True,
                                  name=f"job-{job['job_id']}")
        job["_thread"] = thread
        _jobs[job["job_id"]] = job
        while len(_jobs) > MAX_JOBS:                # forget the oldest finished job
            oldest = next((jid for jid, j in _jobs.items() if j["status"] != "running"), None)
            if oldest is None:
                break
            del _jobs[oldest]
    thread.start()
    if wait:
        thread.join()
        if job["_exc"] is not None:
            raise job["_exc"]
    with _lock:
        return _snapshot(job)


def get(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise NotFoundError("Unknown job id (the server may have restarted)")
        return _snapshot(job)


def join_all(timeout: float = 60.0) -> None:
    """Wait for running jobs (used by tests and clean shutdown)."""
    with _lock:
        threads = [j["_thread"] for j in _jobs.values() if j["status"] == "running"]
    for t in threads:
        t.join(timeout)


def reset() -> None:
    """Forget all finished jobs (tests)."""
    join_all()
    with _lock:
        _jobs.clear()
