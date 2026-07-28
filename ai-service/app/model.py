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
    Invertd,
    LoadImaged,
    Orientationd,
    ScaleIntensityRanged,
    Spacingd,
)

from app.preprocessing import safe_pixdim

BUNDLE_NAME = "spleen_ct_segmentation"
MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/app/models"))
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

DEFAULT_PIXDIM = (1.5, 1.5, 2.0)
OUTPUT_CHANNELS = 2
# Circuit breaker for pathologically large volumes; typical real scans stay under this untouched.
MAX_RESAMPLED_VOXELS = 20_000_000

_model = None
_model_lock = Lock()


def _weights_path() -> Path:
    return MODEL_DIR / BUNDLE_NAME / "models" / "model.pt"


def is_model_loaded() -> bool:
    return _model is not None


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


def run_inference(input_path: str, output_path: str) -> dict:
    """Run spleen segmentation on a NIfTI file and write a mask NIfTI file
    co-registered with the *original* input volume (same shape/affine),
    so the frontend can overlay it voxel-for-voxel without extra resampling.
    """
    start = time.time()
    net = get_model()
    pixdim = safe_pixdim(input_path, DEFAULT_PIXDIM, MAX_RESAMPLED_VOXELS, OUTPUT_CHANNELS)
    pre = _pre_transforms(pixdim)

    data = pre({"image": input_path})
    image = data["image"].unsqueeze(0).to(DEVICE)

    with torch.no_grad():
        logits = sliding_window_inference(
            inputs=image,
            roi_size=(96, 96, 96),
            sw_batch_size=1,
            predictor=net,
            overlap=0.5,
        )
        probs = torch.softmax(logits, dim=1)

    data["pred"] = probs[0].cpu()

    # Argmax before invert (not after) - avoids inverting a full-precision probability tensor.
    post = Compose(
        [
            AsDiscreted(keys="pred", argmax=True),
            Invertd(
                keys="pred",
                transform=pre,
                orig_keys="image",
                nearest_interp=True,
                to_tensor=True,
            ),
        ]
    )
    data = post(data)
    mask = np.asarray(data["pred"][0]).astype(np.uint8)

    original = nib.load(input_path)
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
