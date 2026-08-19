"""
Spleen CT segmentation using the pretrained MONAI Model Zoo bundle
"spleen_ct_segmentation" (3D UNet, trained on the Medical Segmentation
Decathlon Task09_Spleen dataset).

Weights are fetched on first use via `monai.bundle.download` and cached
under MODEL_DIR so subsequent requests / container restarts don't
re-download them (as long as the volume/cache dir persists).
"""

import os
import time
from pathlib import Path
from threading import Lock

import nibabel as nib
import numpy as np
import torch
from monai.bundle import download
from monai.inferers import sliding_window_inference
from monai.networks.layers import Norm
from monai.networks.nets import UNet
from monai.transforms import (
    AsDiscreted,
    Compose,
    EnsureChannelFirstd,
    EnsureTyped,
    LoadImaged,
    Orientationd,
    ScaleIntensityRanged,
    Spacingd,
)

from app.preprocessing import remap_mask_to_original, safe_pixdim
from app.progress import NULL_PROGRESS, Progress

BUNDLE_NAME = "spleen_ct_segmentation"
MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/app/models"))
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

DEFAULT_PIXDIM = (1.5, 1.5, 2.0)
ROI_SIZE = (96, 96, 96)
SW_OVERLAP = 0.5
OUTPUT_CHANNELS = 2
# Circuit breaker for pathologically large volumes; typical real scans stay under this untouched.
MAX_RESAMPLED_VOXELS = 20_000_000

_model = None
_model_lock = Lock()


def _weights_path() -> Path:
    return MODEL_DIR / BUNDLE_NAME / "models" / "model.pt"


def get_model() -> UNet:
    """Lazily download the pretrained bundle weights and build the network.

    Thread-safe: the first request pays the (one-time) download + load
    cost, everyone else reuses the cached module-level instance.
    """
    global _model
    if _model is not None:
        return _model

    with _model_lock:
        if _model is not None:
            return _model

        weights_path = _weights_path()
        if not weights_path.exists():
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            download(name=BUNDLE_NAME, bundle_dir=str(MODEL_DIR))

        net = UNet(
            spatial_dims=3,
            in_channels=1,
            out_channels=2,
            channels=(16, 32, 64, 128, 256),
            strides=(2, 2, 2, 2),
            num_res_units=2,
            norm=Norm.BATCH,
        ).to(DEVICE)
        state_dict = torch.load(weights_path, map_location=DEVICE)
        net.load_state_dict(state_dict)
        net.eval()
        _model = net
        return _model


def _pre_transforms(pixdim: tuple[float, float, float]) -> Compose:
    return Compose(
        [
            LoadImaged(keys="image", image_only=False),
            EnsureChannelFirstd(keys="image"),
            Orientationd(keys="image", axcodes="RAS"),
            Spacingd(keys="image", pixdim=pixdim, mode="bilinear"),
            ScaleIntensityRanged(
                keys="image", a_min=-57, a_max=164, b_min=0.0, b_max=1.0, clip=True
            ),
            EnsureTyped(keys="image"),
        ]
    )


def run_inference(
    input_path: str, output_path: str, progress: Progress = NULL_PROGRESS
) -> dict:
    """Run spleen segmentation on a NIfTI file and write a mask NIfTI file
    co-registered with the *original* input volume (same shape/affine),
    so the frontend can overlay it voxel-for-voxel without extra resampling.

    `progress` is notified as each stage begins, and per sliding-window
    patch during inference, so a queued job can report where it has got to.
    """
    start = time.time()
    progress.stage("loading_model" if _weights_path().exists() else "downloading_weights")
    net = get_model()

    progress.stage("preprocessing")
    pixdim = safe_pixdim(input_path, DEFAULT_PIXDIM, MAX_RESAMPLED_VOXELS, OUTPUT_CHANNELS)
    pre = _pre_transforms(pixdim)

    data = pre({"image": input_path})
    image = data["image"].unsqueeze(0).to(DEVICE)

    progress.stage("inference")
    predictor = progress.wrap_predictor(net, tuple(image.shape[2:]), ROI_SIZE, SW_OVERLAP)
    with torch.inference_mode():
        logits = sliding_window_inference(
            inputs=image,
            roi_size=ROI_SIZE,
            sw_batch_size=1,
            predictor=predictor,
            overlap=SW_OVERLAP,
        )

    progress.stage("postprocessing")
    # No softmax: it is monotonic per voxel, so it cannot change which channel
    # wins the argmax below - it only allocates a second copy of the logits.
    data["pred"] = logits[0].cpu()
    del logits
    # The resampled input is not read again; on a small host it is worth the
    # explicit drop before the mask is built.
    data.pop("image", None)
    del image
    data = Compose([AsDiscreted(keys="pred", argmax=True)])(data)
    mask_resampled = np.asarray(data["pred"][0]).astype(np.uint8)
    mask_affine = np.asarray(data["pred"].affine, dtype=np.float64)

    original = nib.load(input_path)
    mask = remap_mask_to_original(
        mask_resampled, mask_affine, original.affine, original.shape[:3]
    )
    progress.stage("writing_mask")
    nib.save(nib.Nifti1Image(mask, original.affine, original.header), output_path)

    voxel_volume_mm3 = float(abs(np.linalg.det(original.affine[:3, :3])))
    voxel_count = int(mask.sum())
    volume_ml = voxel_count * voxel_volume_mm3 / 1000.0
    elapsed_ms = (time.time() - start) * 1000

    return {
        "voxel_count": voxel_count,
        "volume_ml": round(volume_ml, 2),
        "inference_time_ms": round(elapsed_ms, 1),
    }
