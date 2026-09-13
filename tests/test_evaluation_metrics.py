"""The arithmetic behind evaluation/evaluate.py.

Pure functions over arrays, so these need no stack and no model. They are
here rather than under evaluation/ so that one command runs everything.
"""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evaluation"))

from metrics import dice, iou, score_case, volume_ml  # noqa: E402

IDENTITY = np.eye(4)


def box(shape=(8, 8, 8), extent=4) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    mask[:extent, :extent, :extent] = 1
    return mask


def test_a_perfect_prediction_scores_one():
    mask = box()
    assert dice(mask, mask) == 1.0
    assert iou(mask, mask) == 1.0


def test_a_prediction_that_misses_entirely_scores_zero():
    truth = np.zeros((8, 8, 8), dtype=np.uint8)
    truth[:4, :4, :4] = 1
    prediction = np.zeros((8, 8, 8), dtype=np.uint8)
    prediction[4:, 4:, 4:] = 1

    assert dice(prediction, truth) == 0.0
    assert iou(prediction, truth) == 0.0


def test_finding_nothing_when_there_is_nothing_is_a_right_answer():
    """The whole-body model gets asked for organs a scan does not contain.
    Predicting none of an absent organ is correct, not a zero."""
    empty = np.zeros((4, 4, 4), dtype=np.uint8)
    assert dice(empty, empty) == 1.0
    assert iou(empty, empty) == 1.0


def test_finding_nothing_when_there_is_something_scores_zero():
    assert dice(np.zeros((4, 4, 4)), box((4, 4, 4), 2)) == 0.0


def test_half_an_overlap():
    truth = np.zeros(10, dtype=np.uint8)
    truth[:6] = 1
    prediction = np.zeros(10, dtype=np.uint8)
    prediction[3:9] = 1

    # 3 shared voxels, 6 in each mask: 2*3 / 12.
    assert dice(prediction, truth) == pytest.approx(0.5)
    # 3 shared, 9 in the union.
    assert iou(prediction, truth) == pytest.approx(1 / 3)


def test_volume_uses_the_voxel_size_from_the_affine():
    mask = np.zeros((10, 10, 10), dtype=np.uint8)
    mask[:5, :5, :5] = 1  # 125 voxels

    # 2mm x 2mm x 2mm = 8 mm3 a voxel, so 1000 mm3, which is 1 mL.
    assert volume_ml(mask, np.diag([2.0, 2.0, 2.0, 1.0])) == pytest.approx(1.0)
    assert volume_ml(mask, IDENTITY) == pytest.approx(0.125)


def test_volume_error_is_signed():
    prediction = box(extent=5)
    truth = box(extent=4)
    scores = score_case(prediction, truth, IDENTITY)

    assert scores.predicted_ml > scores.truth_ml
    assert scores.volume_error_ml > 0
    assert scores.volume_error_pct == pytest.approx(
        100 * (125 - 64) / 64
    )


def test_volume_error_percentage_is_undefined_without_a_true_volume():
    scores = score_case(box(extent=2), np.zeros((8, 8, 8)), IDENTITY)
    assert scores.truth_ml == 0
    assert math.isnan(scores.volume_error_pct)
