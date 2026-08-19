"""HTTP surface of the AI service.

Segmentation is a job, not a request. `POST /jobs` only accepts the volume
and puts it on the queue - it returns in the time it takes to write the
upload to disk, whatever the model then spends. Callers follow
`GET /jobs/{id}` for progress and collect the mask from
`GET /jobs/{id}/mask` once it reports `completed`.

The API process deliberately never imports the models: inference happens
in the worker (see app/worker.py), so this one stays small and responsive.
"""

import logging

from fastapi import FastAPI, Form, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from redis.exceptions import RedisError
from rq import Worker

from app import jobs, jobstore
from app.organs import DEFAULT_ORGAN, ORGANS
from app.queueing import (
    MAX_QUEUE_DEPTH,
    QUEUE_NAME,
    dlq_list,
    dlq_size,
    get_queue,
    get_redis,
)
from app.schemas import (
    DeadLetterList,
    HealthResponse,
    JobResponse,
    MessageResponse,
    OrganInfo,
    OrgansResponse,
    QueueStats,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-service")

MAX_UPLOAD_BYTES = 200 * 1024 * 1024

app = FastAPI(
    title="Medical Image Analysis - AI Service",
    description=(
        "Queues and runs CT/MRI segmentation jobs. "
        "Educational/demo use only - not a medical device."
    ),
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health(response: Response) -> HealthResponse:
    try:
        redis = get_redis()
        redis.ping()
        queue = get_queue()
        stats = QueueStats(
            queued=queue.count,
            scheduled=queue.scheduled_job_registry.count,
            started=queue.started_job_registry.count,
            workers=Worker.count(connection=redis),
            dead_lettered=dlq_size(),
            max_queue_depth=MAX_QUEUE_DEPTH,
        )
    except RedisError as exc:
        logger.error("Redis health check failed: %s", exc)
        response.status_code = 503
        return HealthResponse(status="degraded", redis="unavailable", queue=QUEUE_NAME)

    return HealthResponse(status="ok", redis="ok", queue=QUEUE_NAME, stats=stats)


@app.get("/organs", response_model=OrgansResponse)
def organs() -> OrgansResponse:
    return OrgansResponse(
        organs=[
            OrganInfo(key=key, display_name=spec.display_name)
            for key, spec in ORGANS.items()
        ],
        default=DEFAULT_ORGAN,
    )


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------


@app.post("/jobs", response_model=JobResponse, status_code=202)
async def create_job(
    file: UploadFile, organ: str = Form(default=DEFAULT_ORGAN)
) -> JobResponse:
    filename = file.filename or ""
    if not (filename.endswith(".nii") or filename.endswith(".nii.gz")):
        raise HTTPException(
            status_code=400, detail="Only .nii or .nii.gz files are supported"
        )

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit",
        )

    try:
        state = jobs.enqueue(contents, filename, organ)
    except jobs.UnknownOrganError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except jobs.QueueFullError as exc:
        # 503 + Retry-After: the caller should back off, not hammer us.
        raise HTTPException(
            status_code=503, detail=str(exc), headers={"Retry-After": "30"}
        ) from exc
    except RedisError as exc:
        logger.exception("Could not enqueue job")
        raise HTTPException(status_code=503, detail="Job queue is unavailable") from exc

    return JobResponse(**state)


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    job = jobs.fetch(job_id)
    if job is None:
        # The Redis record may have expired while the job is still on
        # record as dead lettered.
        state = jobs.describe_missing(job_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"No such job: {job_id}")
        return JobResponse(**state)

    return JobResponse(**jobs.describe(job))


@app.get("/jobs/{job_id}/mask")
def get_job_mask(job_id: str) -> FileResponse:
    if not jobstore.has_mask(job_id):
        raise HTTPException(
            status_code=404,
            detail=f"No mask available for job {job_id} (not finished, or already collected)",
        )
    return FileResponse(
        jobstore.mask_path(job_id),
        media_type="application/gzip",
        filename="mask.nii.gz",
    )


@app.delete("/jobs/{job_id}", response_model=MessageResponse)
def delete_job(job_id: str) -> MessageResponse:
    """Drop a job and its payload. Callers do this once they have the mask."""
    jobs.delete(job_id)
    return MessageResponse(message=f"Job {job_id} deleted")


@app.post("/jobs/{job_id}/cancel", response_model=MessageResponse)
def cancel_job(job_id: str) -> MessageResponse:
    if not jobs.cancel(job_id):
        raise HTTPException(
            status_code=409, detail=f"Job {job_id} is not cancellable (missing or finished)"
        )
    return MessageResponse(message=f"Job {job_id} cancelled")


# --------------------------------------------------------------------------
# Dead letter queue
# --------------------------------------------------------------------------
#
# Operator-facing. Not exposed through the public API - reachable only
# inside the compose network / cluster.


@app.get("/dlq", response_model=DeadLetterList)
def list_dead_letters(
    limit: int = Query(default=50, ge=1, le=500), offset: int = Query(default=0, ge=0)
) -> DeadLetterList:
    entries = dlq_list(limit=limit, offset=offset)
    for entry in entries:
        entry["replayable"] = jobstore.has_input(entry["job_id"])
    return DeadLetterList(total=dlq_size(), entries=entries)


@app.post("/dlq/{job_id}/replay", response_model=JobResponse)
def replay_dead_letter(job_id: str) -> JobResponse:
    try:
        return JobResponse(**jobs.replay(job_id))
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"Job {job_id} is not in the dead letter queue"
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except jobs.UnknownOrganError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/dlq/{job_id}", response_model=MessageResponse)
def discard_dead_letter(job_id: str) -> MessageResponse:
    jobs.delete(job_id)
    return MessageResponse(message=f"Dead lettered job {job_id} discarded")
