"""Segmentation metrics, kept apart from the script that runs them so they
can be tested without a model, a service or a dataset."""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CaseMetrics:
    dice: float
    iou: float
    predicted_ml: float
    truth_ml: float

    @property
    def volume_error_ml(self) -> float:
        return self.predicted_ml - self.truth_ml

    @property
    def volume_error_pct(self) -> float:
        """Signed, as a percentage of the true volume.

        Undefined when the organ is not in the ground truth at all, which is
        a real case for the whole-body model: not every scan contains every
        structure.
        """
        if self.truth_ml == 0:
            return float("nan")
        return 100.0 * self.volume_error_ml / self.truth_ml


def dice(prediction: np.ndarray, truth: np.ndarray) -> float:
    """Dice similarity coefficient of two binary masks.

    Two empty masks score 1.0: the model was asked for an organ that is not
    in the scan and correctly found none of it. Scoring that 0 would punish
    the right answer, and averaging it in would drag an otherwise good run
    down for the wrong reason.
    """
    prediction = prediction.astype(bool)
    truth = truth.astype(bool)

    total = prediction.sum() + truth.sum()
    if total == 0:
        return 1.0
    return float(2.0 * np.logical_and(prediction, truth).sum() / total)


def iou(prediction: np.ndarray, truth: np.ndarray) -> float:
    """Intersection over union, with the same convention for two empties."""
    prediction = prediction.astype(bool)
    truth = truth.astype(bool)

    union = np.logical_or(prediction, truth).sum()
    if union == 0:
        return 1.0
    return float(np.logical_and(prediction, truth).sum() / union)


def volume_ml(mask: np.ndarray, affine: np.ndarray) -> float:
    """Volume of a binary mask in millilitres.

    Same arithmetic the AI service reports with, so a difference between this
    and the number on the scan page means a real disagreement rather than two
    ways of rounding.
    """
    voxel_volume_mm3 = float(abs(np.linalg.det(affine[:3, :3])))
    return float(mask.astype(bool).sum()) * voxel_volume_mm3 / 1000.0


def score_case(
    prediction: np.ndarray, truth: np.ndarray, affine: np.ndarray
) -> CaseMetrics:
    return CaseMetrics(
        dice=dice(prediction, truth),
        iou=iou(prediction, truth),
        predicted_ml=volume_ml(prediction, affine),
        truth_ml=volume_ml(truth, affine),
    )
