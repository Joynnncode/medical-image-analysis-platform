"""A stand-in for the real AI service, for tests about the platform rather
than the model.

The real service spends minutes in torch and needs hundreds of megabytes to
answer one request, which makes it a bad thing to put in a suite meant to run
on every change. This speaks the same HTTP contract as
`ai-service/app/main.py` on the synchronous path (`/health`, `/organs`,
`POST /segment`) and returns a real NIfTI mask, so everything downstream of
inference - the API's orchestration, storage, DTOs, the mask a viewer would
load - is exercised for real. Only the inference itself is faked.

Two things are deliberately faithful rather than convenient:

  * The organ registry is loaded from `ai-service/app/organs.py` itself, so a
    new organ shows up here without anyone remembering to update the stub.
  * Concurrency is bounded by a Semaphore(1) that answers 503 with a
    Retry-After, which is what the real service does and what the API has a
    separate code path for.

`POST /__control` flips behaviour (mode, delay) so a test can ask for a busy
or failing service without racing anything. It is prefixed to keep it
visibly not part of the contract under test.
"""

import base64
import importlib.util
import tempfile
import threading
import time
from pathlib import Path

import nibabel as nib
import numpy as np
from fastapi import FastAPI, Form, HTTPException, UploadFile
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent
ORGANS_PATH = REPO_ROOT / "ai-service" / "app" / "organs.py"


def _load_real_organ_registry():
    """Import the service's own organs.py by path.

    It imports nothing heavy (a dataclass and nothing else), so this costs
    nothing, and it means the stub cannot drift from the real organ list.
    """
    spec = importlib.util.spec_from_file_location("stub_organs", ORGANS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ORGANS, module.DEFAULT_ORGAN


ORGANS, DEFAULT_ORGAN = _load_real_organ_registry()

app = FastAPI(title="AI service stub")

_inference_slot = threading.Semaphore(1)


class Control(BaseModel):
    """How the stub should answer the next /segment call."""

    # "ok"    - segment normally
    # "busy"  - answer 503 as if another run held the slot
    # "fail"  - answer 500 as if inference raised
    mode: str = "ok"
    # Seconds to spend "inferring". Lets a test hold the slot open while it
    # sends a second request.
    delay_seconds: float = 0.0


_control = Control()


@app.get("/health")
def health():
    return {"status": "ok", "device": "cpu", "model_loaded": True}


@app.get("/organs")
def organs():
    return {
        "organs": [
            {"key": key, "display_name": spec.display_name}
            for key, spec in ORGANS.items()
        ],
        "default": DEFAULT_ORGAN,
    }


@app.get("/__control")
def get_control():
    return _control


@app.post("/__control")
def set_control(control: Control):
    global _control
    _control = control
    return _control


def _fake_mask(volume_shape: tuple[int, int, int]) -> np.ndarray:
    """A centred box of 1s, sized as a fraction of the volume.

    The shape is what matters downstream: the frontend overlays the mask on
    the original voxel grid, so a mask that does not match the input shape is
    the bug most worth catching. The contents just have to be a plausible
    binary blob.
    """
    mask = np.zeros(volume_shape, dtype=np.uint8)
    slices = tuple(
        slice(max(1, size // 4), max(2, size - size // 4)) for size in volume_shape
    )
    mask[slices] = 1
    return mask


@app.post("/segment")
def segment(file: UploadFile, organ: str = Form(default=DEFAULT_ORGAN)):
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

    if _control.mode == "busy" or not _inference_slot.acquire(blocking=False):
        raise HTTPException(
            status_code=503,
            detail="Another segmentation is already running. Try again shortly.",
            headers={"Retry-After": "30"},
        )

    try:
        if _control.mode == "fail":
            raise HTTPException(status_code=500, detail="Segmentation failed")

        started = time.time()
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / "input.nii.gz"
            output_path = Path(tmp_dir) / "mask.nii.gz"
            input_path.write_bytes(file.file.read())

            original = nib.load(str(input_path))
            mask = _fake_mask(original.shape[:3])
            nib.save(
                nib.Nifti1Image(mask, original.affine, original.header),
                str(output_path),
            )

            if _control.delay_seconds:
                time.sleep(_control.delay_seconds)

            mask_bytes = output_path.read_bytes()

            # Same arithmetic as app/model.py, so a test can check the numbers
            # the API reports against the mask it hands back.
            voxel_volume_mm3 = float(abs(np.linalg.det(original.affine[:3, :3])))
            voxel_count = int(mask.sum())
            volume_ml = voxel_count * voxel_volume_mm3 / 1000.0
    finally:
        _inference_slot.release()

    return {
        "mask_base64": base64.b64encode(mask_bytes).decode("ascii"),
        "voxel_count": voxel_count,
        "volume_ml": round(volume_ml, 2),
        "inference_time_ms": round((time.time() - started) * 1000, 1),
        "model_name": spec.model_name,
        "organ": organ,
        "organ_display_name": spec.display_name,
    }
