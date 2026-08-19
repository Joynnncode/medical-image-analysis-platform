"""On-disk payload store shared between the API process and the workers.

A job's input volume can be a couple of hundred MB, which has no business
sitting in Redis. Redis holds the job's *state*; the bytes live in a
directory keyed by job id on a volume both containers mount:

    JOB_DIR/<job_id>/input.nii.gz   uploaded scan
    JOB_DIR/<job_id>/mask.nii.gz    segmentation output
    JOB_DIR/<job_id>/meta.json      original filename, organ, timestamps

The directory outlives the job on purpose: a dead lettered job keeps its
input so an operator can replay it. `prune(...)` is what eventually
reclaims the space.
"""

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

JOB_DIR = Path(os.environ.get("JOB_DIR", "/app/jobs"))
# Age after which a job directory is reclaimed, whether or not anyone
# collected the mask.
JOB_RETENTION_SECONDS = int(os.environ.get("JOB_RETENTION_SECONDS", str(24 * 3600)))

INPUT_NAME = "input.nii.gz"
MASK_NAME = "mask.nii.gz"
META_NAME = "meta.json"


def job_dir(job_id: str) -> Path:
    # job ids are server-generated uuid4s; refuse anything that could climb
    # out of JOB_DIR if that ever stops being true.
    if not job_id or "/" in job_id or "\\" in job_id or job_id.startswith("."):
        raise ValueError(f"Invalid job id: {job_id!r}")
    return JOB_DIR / job_id


def input_path(job_id: str) -> Path:
    return job_dir(job_id) / INPUT_NAME


def mask_path(job_id: str) -> Path:
    return job_dir(job_id) / MASK_NAME


def meta_path(job_id: str) -> Path:
    return job_dir(job_id) / META_NAME


def create(job_id: str, content: bytes, meta: dict[str, Any]) -> Path:
    directory = job_dir(job_id)
    directory.mkdir(parents=True, exist_ok=True)
    input_path(job_id).write_bytes(content)
    write_meta(job_id, {**meta, "created_at": time.time(), "size_bytes": len(content)})
    return directory


def write_meta(job_id: str, meta: dict[str, Any]) -> None:
    meta_path(job_id).write_text(json.dumps(meta))


def read_meta(job_id: str) -> dict[str, Any]:
    path = meta_path(job_id)
    if not path.exists():
        raise FileNotFoundError(f"No payload stored for job {job_id}")
    return json.loads(path.read_text())


def has_input(job_id: str) -> bool:
    try:
        return input_path(job_id).exists()
    except ValueError:
        return False


def has_mask(job_id: str) -> bool:
    try:
        return mask_path(job_id).exists()
    except ValueError:
        return False


def delete(job_id: str) -> bool:
    directory = job_dir(job_id)
    if not directory.exists():
        return False
    shutil.rmtree(directory, ignore_errors=True)
    return True


def prune(max_age_seconds: int = JOB_RETENTION_SECONDS, keep: set[str] | None = None) -> int:
    """Delete job directories older than `max_age_seconds`.

    `keep` lets the caller protect jobs it still cares about (dead lettered
    ones awaiting replay).
    """
    if not JOB_DIR.exists():
        return 0

    keep = keep or set()
    cutoff = time.time() - max_age_seconds
    removed = 0
    for directory in JOB_DIR.iterdir():
        if not directory.is_dir() or directory.name in keep:
            continue
        try:
            if directory.stat().st_mtime < cutoff:
                shutil.rmtree(directory, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed
