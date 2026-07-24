"""Quick standalone smoke test: builds a synthetic CT-like NIfTI volume and
runs it through the real inference pipeline (download weights, preprocess,
sliding-window inference, invert, save) to catch integration bugs before
wiring up the rest of the stack. Not a correctness test of segmentation
quality - just "does the pipeline run end-to-end".
"""

import sys
import tempfile
from pathlib import Path

import nibabel as nib
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from app.model import run_inference  # noqa: E402

def main():
    rng = np.random.default_rng(0)
    volume = rng.integers(low=-200, high=300, size=(64, 64, 48)).astype(np.float32)
    affine = np.diag([1.5, 1.5, 2.0, 1.0])

    with tempfile.TemporaryDirectory() as tmp:
        input_path = Path(tmp) / "synthetic.nii.gz"
        output_path = Path(tmp) / "mask.nii.gz"
        nib.save(nib.Nifti1Image(volume, affine), input_path)

        print("Running inference on synthetic volume...")
        stats = run_inference(str(input_path), str(output_path))
        print("Stats:", stats)

        mask_img = nib.load(output_path)
        mask = mask_img.get_fdata()
        print("Output mask shape:", mask.shape, "unique values:", np.unique(mask))
        assert mask.shape == volume.shape, "Mask shape must match original input shape"
        print("SMOKE_TEST_OK")


if __name__ == "__main__":
    main()
