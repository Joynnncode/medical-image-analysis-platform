import base64
import logging
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from app.model import DEVICE, is_model_loaded, run_inference
from app.schemas import HealthResponse, SegmentationResponse

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

ALLOWED_SUFFIXES = {".nii", ".gz"}


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok", device=str(DEVICE), model_loaded=is_model_loaded()
    )


@app.post("/segment", response_model=SegmentationResponse)
async def segment(file: UploadFile) -> SegmentationResponse:
    filename = file.filename or ""
    if not (filename.endswith(".nii") or filename.endswith(".nii.gz")):
        raise HTTPException(
            status_code=400, detail="Only .nii or .nii.gz files are supported"
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        input_path = Path(tmp_dir) / "input.nii.gz"
        output_path = Path(tmp_dir) / "mask.nii.gz"

        contents = await file.read()
        input_path.write_bytes(contents)

        try:
            stats = run_inference(str(input_path), str(output_path))
        except Exception:
            logger.exception("Segmentation failed")
            raise HTTPException(status_code=500, detail="Segmentation failed")

        mask_bytes = output_path.read_bytes()

    return SegmentationResponse(
        mask_base64=base64.b64encode(mask_bytes).decode("ascii"),
        voxel_count=stats["voxel_count"],
        volume_ml=stats["volume_ml"],
        inference_time_ms=stats["inference_time_ms"],
    )
