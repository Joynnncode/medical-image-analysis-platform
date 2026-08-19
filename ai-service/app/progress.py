"""Progress reporting for segmentation jobs.

A CPU inference run is minutes long, so "it's still working" is not a good
enough answer for a UI. The job publishes a coarse stage name plus a
percentage into its RQ metadata, which the API surfaces on
`GET /jobs/{id}` and the poller mirrors down to the browser.

The inference stage is the slow one, and MONAI's sliding window walks a
known number of patches over the volume, so we can count them and turn
that into a genuine percentage rather than a fake spinner.
"""

import math
import time
from typing import Any, Callable, Sequence

# Percentage each stage *starts* at. Inference is deliberately given the
# widest band because it dominates the wall clock.
STAGE_PERCENTS: dict[str, int] = {
    "queued": 0,
    "starting": 3,
    "loading_model": 6,
    "downloading_weights": 8,
    "preprocessing": 18,
    "inference": 25,
    "postprocessing": 88,
    "writing_mask": 95,
    "done": 100,
}

INFERENCE_START = STAGE_PERCENTS["inference"]
INFERENCE_END = STAGE_PERCENTS["postprocessing"] - 3

STAGE_LABELS: dict[str, str] = {
    "queued": "Waiting for a worker",
    "starting": "Starting",
    "loading_model": "Loading model",
    "downloading_weights": "Downloading model weights",
    "preprocessing": "Preparing volume",
    "inference": "Running inference",
    "postprocessing": "Post-processing mask",
    "writing_mask": "Writing mask",
    "done": "Done",
    "failed": "Failed",
}


def stage_label(stage: str) -> str:
    return STAGE_LABELS.get(stage, stage.replace("_", " ").capitalize())


def estimate_window_count(
    image_size: Sequence[int], roi_size: Sequence[int], overlap: float
) -> int:
    """How many patches MONAI's sliding window will visit.

    Uses MONAI's own patch enumeration so the count matches what actually
    runs; falls back to the closed-form approximation if MONAI's internals
    move, since being slightly wrong about a progress bar must never break
    an inference run.
    """
    padded = [max(int(dim), int(roi)) for dim, roi in zip(image_size, roi_size)]
    intervals = [
        int(roi) if int(roi) == dim else max(int(int(roi) * (1 - overlap)), 1)
        for dim, roi in zip(padded, roi_size)
    ]

    try:
        from monai.data.utils import dense_patch_slices

        return max(len(dense_patch_slices(padded, list(roi_size), intervals)), 1)
    except Exception:
        total = 1
        for dim, roi, interval in zip(padded, roi_size, intervals):
            total *= max(int(math.ceil((dim - int(roi)) / interval)) + 1, 1)
        return max(total, 1)


class Progress:
    """No-op reporter. Inference code depends on this, not on RQ."""

    def stage(self, name: str, percent: float | None = None) -> None:
        return None

    def wrap_predictor(
        self,
        predictor: Callable,
        image_size: Sequence[int],
        roi_size: Sequence[int],
        overlap: float,
    ) -> Callable:
        return predictor


NULL_PROGRESS = Progress()


class JobProgress(Progress):
    """Writes progress into an RQ job's metadata.

    Updates are throttled: a large volume can be thousands of patches and
    a Redis round trip per patch would be pure overhead. Stage changes and
    the final update always flush.
    """

    def __init__(self, job: Any, min_interval: float = 0.75, extra: dict[str, Any] | None = None):
        self._job = job
        self._min_interval = min_interval
        self._last_write = 0.0
        self._stage = "starting"
        self._percent = float(STAGE_PERCENTS["starting"])
        if extra:
            self._job.meta.update(extra)

    def stage(self, name: str, percent: float | None = None) -> None:
        self._stage = name
        if percent is None:
            percent = STAGE_PERCENTS.get(name, self._percent)
        # Never let the bar go backwards, whatever the caller asks for.
        self._percent = max(self._percent, float(percent))
        self._flush(force=True)

    def wrap_predictor(
        self,
        predictor: Callable,
        image_size: Sequence[int],
        roi_size: Sequence[int],
        overlap: float,
    ) -> Callable:
        total = estimate_window_count(image_size, roi_size, overlap)
        done = 0
        span = INFERENCE_END - INFERENCE_START

        def tracked(*args, **kwargs):
            nonlocal done
            result = predictor(*args, **kwargs)
            done += 1
            fraction = min(done / total, 1.0)
            self._percent = max(self._percent, INFERENCE_START + span * fraction)
            self._job.meta["windows_done"] = done
            self._job.meta["windows_total"] = total
            self._flush()
            return result

        self._job.meta["windows_total"] = total
        return tracked

    def _flush(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_write < self._min_interval:
            return
        self._last_write = now
        self._job.meta["stage"] = self._stage
        self._job.meta["stage_label"] = stage_label(self._stage)
        self._job.meta["progress"] = int(round(self._percent))
        self._job.meta["updated_at"] = now
        try:
            self._job.save_meta()
        except Exception:
            # Progress is best-effort: a Redis blip must not kill the job.
            pass
