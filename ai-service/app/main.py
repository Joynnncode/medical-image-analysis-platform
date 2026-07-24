import base64
import logging
import tempfile
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
async def segment(
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

    with tempfile.TemporaryDirectory() as tmp_dir:
        input_path = Path(tmp_dir) / "input.nii.gz"
        output_path = Path(tmp_dir) / "mask.nii.gz"

        contents = await file.read()
        input_path.write_bytes(contents)

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

    return SegmentationResponse(
        mask_base64=base64.b64encode(mask_bytes).decode("ascii"),
        voxel_count=stats["voxel_count"],
        volume_ml=stats["volume_ml"],
        inference_time_ms=stats["inference_time_ms"],
        model_name=spec.model_name,
        organ=organ,
        organ_display_name=spec.display_name,
    )
