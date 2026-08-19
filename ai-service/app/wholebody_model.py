"""Multi-organ segmentation using the pretrained MONAI Model Zoo bundle
"wholeBody_ct_segmentation" (SegResNet, 105 labels: background + 104
anatomical structures). We run the model once and extract whichever single
label the caller asked for, matching the bundle's own published inference
pipeline (see configs/inference.json in the downloaded bundle) so results
match what the bundle authors verified - just reimplemented directly
instead of driven through MONAI's ConfigParser.

Uses the "low-res" (3mm) checkpoint by default: the bundle ships both a
1.5mm (`model.pt`) and 3mm (`model_lowres.pt`) trained checkpoint of the
same architecture; low-res is much faster on CPU, which matters for
running this on a laptop or a free-tier host.
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
from monai.networks.nets import SegResNet
from monai.transforms import (
    AsDiscreted,
    Compose,
    EnsureChannelFirstd,
    EnsureTyped,
    Invertd,
    LoadImaged,
    NormalizeIntensityd,
    Orientationd,
    ScaleIntensityd,
    Spacingd,
)

from app.progress import NULL_PROGRESS, Progress

BUNDLE_NAME = "wholeBody_ct_segmentation"
MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/app/models"))
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

PIXDIM = (3.0, 3.0, 3.0)
ROI_SIZE = (96, 96, 96)
SW_OVERLAP = 0.25
WEIGHTS_FILE = "model_lowres.pt"
NUM_LABELS = 105

_model = None
_model_lock = Lock()


def _weights_path() -> Path:
    return MODEL_DIR / BUNDLE_NAME / "models" / WEIGHTS_FILE


def get_model() -> SegResNet:
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

        net = SegResNet(
            spatial_dims=3,
            in_channels=1,
            out_channels=NUM_LABELS,
            init_filters=32,
            blocks_down=(1, 2, 2, 4),
            blocks_up=(1, 1, 1),
            dropout_prob=0.2,
        ).to(DEVICE)
        state_dict = torch.load(weights_path, map_location=DEVICE)
        net.load_state_dict(state_dict)
        net.eval()
        _model = net
        return _model


def _pre_transforms() -> Compose:
    return Compose(
        [
            LoadImaged(keys="image", image_only=False),
            EnsureTyped(keys="image"),
            EnsureChannelFirstd(keys="image"),
            Orientationd(keys="image", axcodes="RAS"),
            Spacingd(keys="image", pixdim=PIXDIM, mode="bilinear"),
            NormalizeIntensityd(keys="image", nonzero=True),
            ScaleIntensityd(keys="image", minv=-1.0, maxv=1.0),
        ]
    )


def run_inference(
    input_path: str,
    output_path: str,
    label_index: int,
    progress: Progress = NULL_PROGRESS,
) -> dict:
    """Segment the full body, keep only `label_index`, and write a binary
    mask NIfTI co-registered with the original input volume.

    `progress` is notified as each stage begins, and per sliding-window
    patch during inference, so a queued job can report where it has got to.
    """
    start = time.time()
    progress.stage("loading_model" if _weights_path().exists() else "downloading_weights")
    net = get_model()

    progress.stage("preprocessing")
    pre = _pre_transforms()

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
            mode="gaussian",
            padding_mode="replicate",
        )

    progress.stage("postprocessing")
    # No softmax: monotonic per voxel, so the argmax in the post transforms
    # below is unchanged, and this avoids a second copy of a 105-channel
    # volume - the largest single allocation in this pipeline.
    data["pred"] = logits[0].cpu()
    del logits

    # Match the bundle's own postprocessing order: argmax to a discrete
    # label map *before* inverting back to original spacing/orientation,
    # using nearest-neighbor interpolation (bilinear would invent
    # nonsense intermediate label values between e.g. liver=5 and
    # stomach=6).
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
    labels = np.asarray(data["pred"][0]).astype(np.uint8)
    mask = (labels == label_index).astype(np.uint8)

    original = nib.load(input_path)
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
