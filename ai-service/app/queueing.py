"""Redis / RQ wiring for the segmentation job queue.

Segmentation used to run inline inside the `POST /segment` request, which
meant an HTTP connection (browser -> API -> here) was held open for the
whole of a multi-minute CPU inference, with nothing bounding how many of
those could pile up at once. Now the request only enqueues work: a pool of
RQ workers drains the `segmentation` queue, reports progress as it goes,
and anything that fails every attempt lands in a dead letter queue instead
of vanishing into the logs.
"""

import json
import os
import time
from typing import Any

from redis import Redis
from rq import Queue, Retry
from rq.job import Job

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = os.environ.get("SEGMENTATION_QUEUE", "segmentation")

# Hard ceiling on a single job. A work horse still stuck after this is
# killed by RQ and the failure follows the normal retry -> DLQ path.
JOB_TIMEOUT_SECONDS = int(os.environ.get("JOB_TIMEOUT_SECONDS", "1800"))
# How long a finished job's return value / failure info stays in Redis.
RESULT_TTL_SECONDS = int(os.environ.get("JOB_RESULT_TTL_SECONDS", "86400"))
FAILURE_TTL_SECONDS = int(os.environ.get("JOB_FAILURE_TTL_SECONDS", "604800"))

MAX_ATTEMPTS = max(1, int(os.environ.get("JOB_MAX_ATTEMPTS", "3")))
# Backoff between attempts, in seconds. Delayed retries are handled by the
# worker's built-in scheduler thread (see worker.py).
RETRY_INTERVALS = [
    int(part) for part in os.environ.get("JOB_RETRY_INTERVALS", "10,30").split(",") if part.strip()
]

# Refuse new work rather than letting an unbounded backlog build up - the
# whole point of moving off the synchronous path.
MAX_QUEUE_DEPTH = int(os.environ.get("MAX_QUEUE_DEPTH", "50"))

DLQ_INDEX_KEY = "medimg:dlq:index"      # list of job ids, newest first
DLQ_ENTRIES_KEY = "medimg:dlq:entries"  # hash of job id -> JSON envelope
DLQ_MAX_ENTRIES = int(os.environ.get("DLQ_MAX_ENTRIES", "500"))

_redis: Redis | None = None


def get_redis() -> Redis:
    """Process-wide Redis client (redis-py pools connections internally)."""
    global _redis
    if _redis is None:
        _redis = Redis.from_url(REDIS_URL)
    return _redis


def get_queue() -> Queue:
    return Queue(QUEUE_NAME, connection=get_redis())


def retry_policy() -> Retry | None:
    if MAX_ATTEMPTS <= 1:
        return None
    return Retry(max=MAX_ATTEMPTS - 1, interval=RETRY_INTERVALS or 0)


def attempt_number(job: Job) -> int:
    """1-based attempt this execution represents.

    RQ tracks `retries_left`, which it decrements only once an attempt has
    actually failed, so during a run it still holds the number of *further*
    attempts available.
    """
    retries_left = getattr(job, "retries_left", None)
    if retries_left is None:
        return 1
    return max(1, MAX_ATTEMPTS - int(retries_left))


def queue_depth() -> int:
    queue = get_queue()
    return queue.count + queue.started_job_registry.count + queue.scheduled_job_registry.count


# --------------------------------------------------------------------------
# Dead letter queue
# --------------------------------------------------------------------------
#
# RQ's own FailedJobRegistry expires with `failure_ttl` and holds only the
# traceback, so it isn't much use for working out *what* was being processed
# days later. The DLQ keeps a self-contained envelope (organ, filename,
# attempts, error, where the input file still lives) that an operator can
# inspect and replay.


def dead_letter(
    job: Job,
    error: str,
    exc_type: str = "",
    traceback_text: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a permanently failed job. Idempotent per job id."""
    redis = get_redis()
    if redis.hexists(DLQ_ENTRIES_KEY, job.id):
        return json.loads(redis.hget(DLQ_ENTRIES_KEY, job.id))

    job_meta = job.get_meta(refresh=True) if hasattr(job, "get_meta") else (job.meta or {})
    envelope = {
        "job_id": job.id,
        "organ": job_meta.get("organ") or (meta or {}).get("organ", ""),
        "file_name": job_meta.get("file_name") or (meta or {}).get("file_name", ""),
        "attempts": int(job_meta.get("attempt") or attempt_number(job)),
        "max_attempts": MAX_ATTEMPTS,
        "stage": job_meta.get("stage", ""),
        "progress": job_meta.get("progress", 0),
        "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
        "failed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "error": error,
        "exc_type": exc_type,
        "traceback": traceback_text[-8000:],
    }

    pipeline = redis.pipeline()
    pipeline.hset(DLQ_ENTRIES_KEY, job.id, json.dumps(envelope))
    pipeline.lrem(DLQ_INDEX_KEY, 0, job.id)
    pipeline.lpush(DLQ_INDEX_KEY, job.id)
    pipeline.execute()

    _trim_dlq()
    return envelope


def _trim_dlq() -> None:
    """Keep the DLQ bounded; drop the oldest envelopes past the cap."""
    redis = get_redis()
    overflow = redis.lrange(DLQ_INDEX_KEY, DLQ_MAX_ENTRIES, -1)
    if not overflow:
        return
    pipeline = redis.pipeline()
    pipeline.ltrim(DLQ_INDEX_KEY, 0, DLQ_MAX_ENTRIES - 1)
    pipeline.hdel(DLQ_ENTRIES_KEY, *overflow)
    pipeline.execute()


def dlq_entry(job_id: str) -> dict[str, Any] | None:
    raw = get_redis().hget(DLQ_ENTRIES_KEY, job_id)
    return json.loads(raw) if raw else None


def dlq_list(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    redis = get_redis()
    job_ids = redis.lrange(DLQ_INDEX_KEY, offset, offset + limit - 1)
    if not job_ids:
        return []
    raws = redis.hmget(DLQ_ENTRIES_KEY, job_ids)
    return [json.loads(raw) for raw in raws if raw]


def dlq_size() -> int:
    return get_redis().llen(DLQ_INDEX_KEY)


def dlq_discard(job_id: str) -> bool:
    redis = get_redis()
    pipeline = redis.pipeline()
    pipeline.hdel(DLQ_ENTRIES_KEY, job_id)
    pipeline.lrem(DLQ_INDEX_KEY, 0, job_id)
    removed, _ = pipeline.execute()
    return bool(removed)


def is_dead_lettered(job_id: str) -> bool:
    return bool(get_redis().hexists(DLQ_ENTRIES_KEY, job_id))
