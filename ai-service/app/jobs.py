"""Job lifecycle: enqueue, inspect, cancel, replay.

Sits between the HTTP layer and RQ so that both the public endpoints and
the dead letter replay path go through exactly one definition of "start a
segmentation job".
"""

import logging
import uuid
from typing import Any

from rq.exceptions import NoSuchJobError
from rq.job import Job, JobStatus

from app import jobstore
from app.organs import ORGANS
from app.progress import stage_label
from app.queueing import (
    FAILURE_TTL_SECONDS,
    JOB_TIMEOUT_SECONDS,
    MAX_ATTEMPTS,
    MAX_QUEUE_DEPTH,
    RESULT_TTL_SECONDS,
    dlq_discard,
    dlq_entry,
    get_queue,
    get_redis,
    is_dead_lettered,
    queue_depth,
    retry_policy,
)

logger = logging.getLogger("ai-service.jobs")

# Referenced by name so the API process never has to import torch/MONAI
# just to put a job on the queue.
TASK = "app.tasks.run_segmentation"

# What the outside world sees, independent of RQ's internal vocabulary.
STATUS_MAP = {
    JobStatus.QUEUED: "queued",
    JobStatus.DEFERRED: "queued",
    JobStatus.SCHEDULED: "retrying",
    JobStatus.STARTED: "running",
    JobStatus.FINISHED: "completed",
    JobStatus.FAILED: "failed",
    JobStatus.STOPPED: "failed",
    JobStatus.CANCELED: "canceled",
}

TERMINAL_STATUSES = {"completed", "failed", "canceled"}


class QueueFullError(Exception):
    """Backlog is at its configured ceiling; shed load instead of queueing."""


class UnknownOrganError(Exception):
    pass


def enqueue(content: bytes, file_name: str, organ: str) -> dict[str, Any]:
    if organ not in ORGANS:
        raise UnknownOrganError(f"Unknown organ '{organ}'. Available: {', '.join(ORGANS)}")

    depth = queue_depth()
    if depth >= MAX_QUEUE_DEPTH:
        raise QueueFullError(f"Segmentation backlog is full ({depth} jobs). Try again shortly.")

    job_id = uuid.uuid4().hex
    jobstore.create(job_id, content, {"organ": organ, "file_name": file_name})

    try:
        job = get_queue().enqueue(
            TASK,
            job_id,
            job_id=job_id,
            job_timeout=JOB_TIMEOUT_SECONDS,
            result_ttl=RESULT_TTL_SECONDS,
            failure_ttl=FAILURE_TTL_SECONDS,
            retry=retry_policy(),
            meta={
                "organ": organ,
                "file_name": file_name,
                "stage": "queued",
                "stage_label": stage_label("queued"),
                "progress": 0,
                "attempt": 0,
                "max_attempts": MAX_ATTEMPTS,
            },
        )
    except Exception:
        # Don't leave the payload behind for a job that never made it onto
        # the queue - nothing would ever come along to collect it.
        jobstore.delete(job_id)
        raise

    logger.info("Enqueued segmentation job %s (organ=%s, %d bytes)", job_id, organ, len(content))
    return describe(job)


def fetch(job_id: str) -> Job | None:
    try:
        return Job.fetch(job_id, connection=get_redis())
    except (NoSuchJobError, ValueError):
        return None


def describe(job: Job) -> dict[str, Any]:
    meta = job.get_meta(refresh=True) or {}
    rq_status = job.get_status(refresh=True)
    status = STATUS_MAP.get(rq_status, str(rq_status))
    dead_lettered = is_dead_lettered(job.id)

    result = job.return_value() if status == "completed" else None
    error = None
    if status == "failed":
        entry = dlq_entry(job.id)
        error = (entry or {}).get("error") or _first_line(job.latest_result())

    progress = int(meta.get("progress", 0))
    stage = meta.get("stage") or "queued"
    if status == "completed":
        stage, progress = "done", 100
    elif status == "failed":
        stage = "failed"

    return {
        "job_id": job.id,
        "status": status,
        "dead_lettered": dead_lettered,
        "progress": progress,
        "stage": stage,
        "stage_label": stage_label(stage),
        "attempt": int(meta.get("attempt", 0)),
        "max_attempts": int(meta.get("max_attempts", MAX_ATTEMPTS)),
        "organ": meta.get("organ", ""),
        "file_name": meta.get("file_name", ""),
        "enqueued_at": _iso(job.enqueued_at),
        "started_at": _iso(job.started_at),
        "ended_at": _iso(job.ended_at),
        "error": error,
        "result": result,
        "mask_available": jobstore.has_mask(job.id),
    }


def describe_missing(job_id: str) -> dict[str, Any] | None:
    """State for a job whose Redis record is gone but which we can still
    account for from the dead letter queue."""
    entry = dlq_entry(job_id)
    if entry is None:
        return None
    return {
        "job_id": job_id,
        "status": "failed",
        "dead_lettered": True,
        "progress": int(entry.get("progress", 0)),
        "stage": "failed",
        "stage_label": stage_label("failed"),
        "attempt": int(entry.get("attempts", 0)),
        "max_attempts": int(entry.get("max_attempts", MAX_ATTEMPTS)),
        "organ": entry.get("organ", ""),
        "file_name": entry.get("file_name", ""),
        "enqueued_at": entry.get("enqueued_at"),
        "started_at": None,
        "ended_at": entry.get("failed_at"),
        "error": entry.get("error"),
        "result": None,
        "mask_available": False,
    }


def cancel(job_id: str) -> bool:
    job = fetch(job_id)
    if job is None:
        return False
    status = STATUS_MAP.get(job.get_status(refresh=True))
    if status in TERMINAL_STATUSES:
        return False
    try:
        # Queued: drops out of the queue. Running: RQ signals the work horse.
        job.cancel()
    except Exception:
        logger.exception("Could not cancel job %s", job_id)
        return False
    return True


def delete(job_id: str) -> bool:
    """Forget a job entirely - Redis record, payload, DLQ entry.

    The API calls this once it has collected the mask, which is what keeps
    the shared volume from growing without bound.
    """
    job = fetch(job_id)
    if job is not None:
        try:
            job.delete()
        except Exception:
            logger.exception("Could not delete RQ record for job %s", job_id)
    dlq_discard(job_id)
    return jobstore.delete(job_id)


def replay(job_id: str) -> dict[str, Any]:
    """Re-run a dead lettered job, reusing its id and its stored input.

    Keeping the id means anything already tracking this job (the .NET API's
    poller, say) picks the replay up without being told about it.
    """
    entry = dlq_entry(job_id)
    if entry is None:
        raise KeyError(job_id)
    if not jobstore.has_input(job_id):
        raise FileNotFoundError(f"Input for job {job_id} is no longer on disk; cannot replay")

    meta = jobstore.read_meta(job_id)
    organ = meta.get("organ", "")
    if organ not in ORGANS:
        raise UnknownOrganError(f"Unknown organ '{organ}'")

    existing = fetch(job_id)
    if existing is not None:
        try:
            existing.delete()
        except Exception:
            logger.exception("Could not clear previous record for job %s", job_id)

    job = get_queue().enqueue(
        TASK,
        job_id,
        job_id=job_id,
        job_timeout=JOB_TIMEOUT_SECONDS,
        result_ttl=RESULT_TTL_SECONDS,
        failure_ttl=FAILURE_TTL_SECONDS,
        retry=retry_policy(),
        meta={
            "organ": organ,
            "file_name": meta.get("file_name", ""),
            "stage": "queued",
            "stage_label": stage_label("queued"),
            "progress": 0,
            "attempt": 0,
            "max_attempts": MAX_ATTEMPTS,
            "replayed_from_dlq": True,
        },
    )
    dlq_discard(job_id)
    logger.info("Replayed dead lettered job %s", job_id)
    return describe(job)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _first_line(result: Any) -> str | None:
    exc = getattr(result, "exc_string", None) if result is not None else None
    if not exc:
        return None
    lines = [line for line in exc.strip().splitlines() if line.strip()]
    return lines[-1] if lines else None
