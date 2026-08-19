"""The unit of work an RQ worker executes.

Deliberately takes nothing but a job id: the volume itself lives in the
shared job store (see jobstore.py), so the queue payload stays a few bytes
and a retry re-reads the same input from disk rather than re-uploading it.
"""

import logging
from typing import Any

from rq import get_current_job

from app import jobstore
from app import model as spleen_model
from app import wholebody_model
from app.organs import ORGANS
from app.progress import JobProgress, Progress
from app.queueing import MAX_ATTEMPTS, attempt_number

logger = logging.getLogger("ai-service.tasks")


class PermanentJobError(Exception):
    """A failure that retrying cannot fix (bad organ, missing payload).

    Raising this skips the remaining attempts and sends the job straight
    to the dead letter queue.
    """


def run_segmentation(job_id: str) -> dict[str, Any]:
    job = get_current_job()
    attempt = attempt_number(job) if job is not None else 1
    logger.info("Starting segmentation job %s (attempt %d/%d)", job_id, attempt, MAX_ATTEMPTS)

    if job is not None:
        # Publish the attempt number before anything can fail, so a job that
        # dies early is still reported (and dead lettered) with the right count.
        job.meta.update({"attempt": attempt, "max_attempts": MAX_ATTEMPTS})
        job.save_meta()

    try:
        meta = jobstore.read_meta(job_id)
    except FileNotFoundError as exc:
        raise _permanent(job, f"Input payload for job {job_id} is missing") from exc

    organ = meta.get("organ", "")
    spec = ORGANS.get(organ)
    if spec is None:
        raise _permanent(job, f"Unknown organ '{organ}'")

    input_path = jobstore.input_path(job_id)
    if not input_path.exists():
        raise _permanent(job, f"Input volume for job {job_id} is missing")

    output_path = jobstore.mask_path(job_id)

    progress: Progress
    if job is None:
        progress = Progress()
    else:
        progress = JobProgress(
            job,
            extra={
                "organ": organ,
                "file_name": meta.get("file_name", ""),
                "attempt": attempt,
                "max_attempts": MAX_ATTEMPTS,
            },
        )
    progress.stage("starting")

    try:
        if spec.engine == "spleen":
            stats = spleen_model.run_inference(
                str(input_path), str(output_path), progress=progress
            )
        else:
            stats = wholebody_model.run_inference(
                str(input_path), str(output_path), spec.label_index, progress=progress
            )
    except Exception:
        # Let it propagate: RQ retries if attempts remain, and the worker's
        # exception handler dead letters it once they don't.
        logger.exception("Segmentation job %s failed on attempt %d", job_id, attempt)
        raise

    progress.stage("done")

    result = {
        "voxel_count": stats["voxel_count"],
        "volume_ml": stats["volume_ml"],
        "inference_time_ms": stats["inference_time_ms"],
        "model_name": spec.model_name,
        "organ": organ,
        "organ_display_name": spec.display_name,
        "mask_size_bytes": output_path.stat().st_size,
        "attempts": attempt,
    }
    logger.info(
        "Finished segmentation job %s: %d voxels, %.1f ms",
        job_id,
        result["voxel_count"],
        result["inference_time_ms"],
    )
    return result


def _permanent(job: Any, message: str) -> PermanentJobError:
    """Burn the remaining retries so a hopeless job fails once, not N times."""
    if job is not None:
        try:
            job.retries_left = 0
            job.save()
        except Exception:
            logger.warning("Could not clear retries for job %s", getattr(job, "id", "?"))
    return PermanentJobError(message)
