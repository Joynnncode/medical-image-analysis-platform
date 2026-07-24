from pydantic import BaseModel


class SegmentationResponse(BaseModel):
    mask_base64: str
    voxel_count: int
    volume_ml: float
    inference_time_ms: float
    model_name: str
    organ: str
    organ_display_name: str


class HealthResponse(BaseModel):
    status: str
    device: str
    model_loaded: bool


class OrganInfo(BaseModel):
    key: str
    display_name: str


class OrgansResponse(BaseModel):
    organs: list[OrganInfo]
    default: str
