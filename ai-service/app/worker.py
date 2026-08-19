"""RQ worker entrypoint.

Run with:  python -m app.worker

Two things this adds on top of a stock `rq worker`:

* a dead letter queue - when a job has burned every attempt, an envelope
  describing it (organ, file, attempts, traceback) is written to Redis so
  it can be inspected and replayed instead of only existing as a log line;
* a janitor that reclaims job payload directories once they age out.
"""

import logging
import os
import socket
import sys
import threading
import time
import traceback
from typing import Any

from rq import Worker
from rq.job import Job

from app import jobstore
from app.queueing import (
    DLQ_INDEX_KEY,
    QUEUE_NAME,
    dead_letter,
    get_queue,
    get_redis,
    is_dead_lettered,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ai-service.worker")

JANITOR_INTERVAL_SECONDS = int(os.environ.get("JANITOR_INTERVAL_SECONDS", "3600"))

# RQ runs the retry scheduler inside one worker, guarded by a Redis lock, and
# only re-checks whether that scheduler is still alive during its maintenance
# pass. If the worker holding the lock dies (a container restart will do it),
# the replacement cannot take the lock until the stale one expires, and
# delayed retries sit in the scheduled registry until the next pass notices.
# RQ's default pass is every 10 minutes; a minute is a much better ceiling on
# how long a retry can be stranded.
MAINTENANCE_INTERVAL_SECONDS = int(os.environ.get("MAINTENANCE_INTERVAL_SECONDS", "60"))

# This process deliberately never imports torch/MONAI. RQ runs each job in a
# forked work horse, and glibc's OpenMP runtime (libgomp, which torch pulls
# in on Linux) is not fork-safe: if the parent has already started OpenMP
# threads, the child deadlocks the first time it enters a parallel region -
# silently, at 0% CPU, until the job timeout kills it. Preloading the weights
# here to save a per-job load would reintroduce exactly that. The model is
# loaded inside each horse instead, from the cache under MODEL_DIR.


def _has_attempts_left(job: Job) -> bool:
    """Whether RQ is going to give this job another go.

    Both hooks below run *before* `handle_job_failure`, which is what
    decrements `retries_left` and decides between requeueing and failing,
    so the value read here is still the pre-decrement one: > 0 means a
    retry is coming, 0/None means this was the last attempt.
    """
    retries_left = getattr(job, "retries_left", None)
    return bool(retries_left)


def dead_letter_handler(job: Job, exc_type: Any, exc_value: Any, tb: Any) -> bool:
    """RQ exception handler: dead letter jobs that have run out of attempts."""
    try:
        if _has_attempts_left(job):
            logger.info("Job %s failed but will be retried", job.id)
            return True

        error = f"{getattr(exc_type, '__name__', exc_type)}: {exc_value}"
        dead_letter(
            job,
            error=error,
            exc_type=getattr(exc_type, "__name__", str(exc_type)),
            traceback_text="".join(traceback.format_exception(exc_type, exc_value, tb)),
        )
        logger.error("Job %s dead lettered: %s", job.id, error)
    except Exception:
        logger.exception("Failed to dead letter job %s", getattr(job, "id", "?"))
    # Keep the chain going so RQ's own FailedJobRegistry still gets it.
    return True


def work_horse_killed_handler(job: Job, retpid: int, ret_val: int, rusage: Any) -> None:
    """Catch failures no exception handler ever sees.

    If the work horse is killed outright - an OOM kill on a big volume is
    the realistic case - nothing raised inside Python, so `dead_letter_handler`
    is never invoked.
    """
    try:
        if _has_attempts_left(job):
            logger.warning("Work horse for job %s was killed; will retry", job.id)
            return
        if is_dead_lettered(job.id):
            return
        dead_letter(
            job,
            error=(
                f"Work horse terminated unexpectedly (exit status {ret_val}). "
                "The process was most likely killed for running out of memory."
            ),
            exc_type="WorkHorseKilled",
        )
        logger.error("Job %s dead lettered after its work horse was killed", job.id)
    except Exception:
        logger.exception("Failed to dead letter killed job %s", getattr(job, "id", "?"))


def _janitor() -> None:
    while True:
        time.sleep(JANITOR_INTERVAL_SECONDS)
        try:
            # Dead lettered jobs keep their input so they can be replayed.
            keep = {jid.decode() if isinstance(jid, bytes) else jid
                    for jid in get_redis().lrange(DLQ_INDEX_KEY, 0, -1)}
            removed = jobstore.prune(keep=keep)
            if removed:
                logger.info("Janitor reclaimed %d expired job director%s",
                            removed, "y" if removed == 1 else "ies")
        except Exception:
            logger.exception("Janitor pass failed")


def healthcheck() -> int:
    """Exit status for `python -m app.worker --health`.

    A worker container serves no HTTP, so "is the port answering" says
    nothing about it. What matters is that this container's worker is
    registered in Redis with a live heartbeat - which RQ keeps refreshing
    even while a job is running.
    """
    try:
        hostname = socket.gethostname()
        for worker in Worker.all(connection=get_redis()):
            if worker.hostname == hostname:
                return 0
        print(f"No live worker registered for {hostname}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Health check failed: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    jobstore.JOB_DIR.mkdir(parents=True, exist_ok=True)

    # Daemon thread: it goes away with the process, and RQ installs its own
    # signal handlers once work() starts, so there is nothing to unwind.
    threading.Thread(target=_janitor, daemon=True).start()

    worker = Worker(
        [get_queue()],
        connection=get_redis(),
        exception_handlers=[dead_letter_handler],
        work_horse_killed_handler=work_horse_killed_handler,
        maintenance_interval=MAINTENANCE_INTERVAL_SECONDS,
    )
    logger.info("Worker %s listening on queue '%s'", worker.name, QUEUE_NAME)

    # with_scheduler=True is what makes the backoff between retry attempts
    # actually fire; without it a delayed retry sits in the scheduled
    # registry forever.
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    if "--health" in sys.argv:
        raise SystemExit(healthcheck())
    main()
