import base64
import logging
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app import model as spleen_model
from app import wholebody_model
from app.organs import DEFAULT_ORGAN, ORGANS
from app.schemas import HealthResponse, OrganInfo, OrgansResponse, SegmentationResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-service")

app = FastAPI(
    title="Medical Image Analysis - AI Service",
    description="Runs CT/MRI segmentation models. Educational/demo use only - not a medical device.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# One inference at a time, stated rather than accidental.
#
# `segment` used to be an `async def` that called run_inference directly, so
# a multi-minute inference ran on the event loop and nothing else in the
# process was answered for its duration - /health and /organs included. That
# also serialised inference, but only as a side effect of the blocking.
#
# As a sync def, FastAPI runs it in the threadpool and the loop stays free,
# which means concurrency has to be bounded here instead. It is bounded at
# one because peak inference is ~438MB against a 512MB free-tier container:
# a second concurrent run does not fit.
_inference_slot = threading.Semaphore(1)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        device=str(spleen_model.DEVICE),
        model_loaded=spleen_model.is_model_loaded() or wholebody_model.is_model_loaded(),
    )


@app.get("/organs", response_model=OrgansResponse)
def organs() -> OrgansResponse:
    return OrgansResponse(
        organs=[
            OrganInfo(key=key, display_name=spec.display_name)
            for key, spec in ORGANS.items()
        ],
        default=DEFAULT_ORGAN,
    )


@app.post("/segment", response_model=SegmentationResponse)
def segment(
    file: UploadFile, organ: str = Form(default=DEFAULT_ORGAN)
) -> SegmentationResponse:
    filename = file.filename or ""
    if not (filename.endswith(".nii") or filename.endswith(".nii.gz")):
        raise HTTPException(
            status_code=400, detail="Only .nii or .nii.gz files are supported"
        )

    spec = ORGANS.get(organ)
    if spec is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown organ '{organ}'. Available: {', '.join(ORGANS)}",
        )

    # Refuse rather than queue. The caller holds an HTTP connection open for
    # the whole run, so waiting in line means two connections held for up to
    # twice as long and a client that cannot tell the difference between slow
    # and stuck. A 503 it can retry is more use than a queue it cannot see.
    if not _inference_slot.acquire(blocking=False):
        logger.info("Refused a segmentation: one is already running")
        raise HTTPException(
            status_code=503,
            detail="Another segmentation is already running. Try again shortly.",
            headers={"Retry-After": "30"},
        )

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / "input.nii.gz"
            output_path = Path(tmp_dir) / "mask.nii.gz"

            input_path.write_bytes(file.file.read())

            try:
                if spec.engine == "spleen":
                    stats = spleen_model.run_inference(str(input_path), str(output_path))
                else:
                    stats = wholebody_model.run_inference(
                        str(input_path), str(output_path), spec.label_index
                    )
            except Exception:
                logger.exception("Segmentation failed")
                raise HTTPException(status_code=500, detail="Segmentation failed")

            mask_bytes = output_path.read_bytes()
    finally:
        _inference_slot.release()

    return SegmentationResponse(
        mask_base64=base64.b64encode(mask_bytes).decode("ascii"),
        voxel_count=stats["voxel_count"],
        volume_ml=stats["volume_ml"],
        inference_time_ms=stats["inference_time_ms"],
        model_name=spec.model_name,
        organ=organ,
        organ_display_name=spec.display_name,
    )
