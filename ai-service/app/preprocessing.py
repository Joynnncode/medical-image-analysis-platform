"""Keeps inference memory within a free-tier host's budget.

Real CT volumes vary a lot in size. The bundles' published pixel spacing
is tuned for segmentation quality, not memory - on a large volume it can
resample to tens of millions of voxels, which (multiplied by however many
output channels the model predicts) is enough to OOM a small instance.
This scales the target spacing coarser, only when needed, to cap the
resampled tensor size.
"""

import nibabel as nib


def safe_pixdim(
    input_path: str,
    default_pixdim: tuple[float, float, float],
    max_voxels: int,
    output_channels: int = 1,
) -> tuple[float, float, float]:
    img = nib.load(input_path)
    shape = img.shape[:3]
    zooms = img.header.get_zooms()[:3]

    resampled_voxels = 1.0
    for size, orig_spacing, target_spacing in zip(shape, zooms, default_pixdim):
        resampled_voxels *= size * float(orig_spacing) / target_spacing

    budget = max_voxels / output_channels
    if resampled_voxels <= budget:
        return default_pixdim

    scale = (resampled_voxels / budget) ** (1 / 3)
    return tuple(round(p * scale, 3) for p in default_pixdim)
