from pydantic import BaseModel


class SegmentationResponse(BaseModel):
    mask_base64: str
    voxel_count: int
    volume_ml: float
    inference_time_ms: float
    model_name: str = "spleen_ct_segmentation"


class HealthResponse(BaseModel):
    status: str
    device: str
    model_loaded: bool
