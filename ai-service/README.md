# AI Service (Python / FastAPI / MONAI)

Runs CT organ segmentation using two pretrained MONAI Model Zoo bundles:

- **`spleen_ct_segmentation`** - a dedicated 3D UNet trained on the Medical
  Segmentation Decathlon Task09_Spleen dataset. Used for the "spleen" option
  - the most accurate choice for that one organ.
- **`wholeBody_ct_segmentation`** - a SegResNet trained to segment 104
  structures in one pass (TotalSegmentator-style). Used for every other organ
  in the picker (liver, kidneys, gallbladder, stomach, pancreas, bladder) by
  running the full model once and keeping only the requested label. Runs at
  its "low-res" (3mm) checkpoint by default for CPU-friendly speed.

See `app/organs.py` for the full list of organ keys and which engine backs
each one.

> Educational / demo project. Not a medical device. Not for clinical use.
> Segmentation quality varies by organ - liver/kidney/spleen tend to be
> reliable, pancreas is a known hard case for this class of model (small,
> irregular shape, low contrast) and may under-segment.

## How a segmentation runs

Segmentation is a **job**, not an HTTP request. `POST /jobs` writes the
uploaded volume to a shared directory, puts a job id on a Redis-backed
[RQ](https://python-rq.org/) queue and returns `202` immediately; a worker
picks it up, reports progress as it goes, and writes the mask back.

```
POST /jobs ──▶ Redis queue ──▶ worker (app/worker.py)
                                 │  fork per job
                                 └─▶ app/tasks.py ─▶ MONAI inference
                                        │
     GET /jobs/{id}  ◀── progress ──────┘
     GET /jobs/{id}/mask ◀── finished mask
```

Why: inference takes minutes on CPU. Running it inside the request meant one
HTTP connection was held open the whole time, a client that went away took
the work with it, and nothing capped how many could run at once. As a queue,
the work outlives the connection, retries on failure, reports progress, and
is bounded by `MAX_QUEUE_DEPTH`.

**Progress** is published to the job's RQ metadata as a stage plus a
percentage. The percentage during inference is real, not a guess: MONAI's
sliding window visits a known number of patches, and the worker counts them.

**Failures** are retried `JOB_MAX_ATTEMPTS` times with a backoff. A job that
fails them all is written to a **dead letter queue** in Redis with its organ,
filename, attempt count and traceback, and its input volume is kept on disk
so it can be replayed. Errors that a retry cannot fix (unknown organ, missing
payload) skip the remaining attempts and go straight there.

## Endpoints

**Jobs**

- `POST /jobs` - multipart upload of a `.nii` / `.nii.gz` CT volume plus an
  `organ` form field (defaults to `spleen`). Returns `202` with a job id.
  Returns `503` with `Retry-After` when the queue is at `MAX_QUEUE_DEPTH`.
- `GET /jobs/{id}` - status (`queued` / `retrying` / `running` / `completed` /
  `failed` / `canceled`), progress percentage, stage, attempt count, error,
  and the result stats once finished.
- `GET /jobs/{id}/mask` - the finished mask as `.nii.gz` (same shape/affine
  as the input).
- `DELETE /jobs/{id}` - drop the job and its stored payload. Callers do this
  once they have collected the mask.
- `POST /jobs/{id}/cancel` - cancel a queued or running job.

**Dead letter queue** (operator-facing; not exposed through the public API)

- `GET /dlq` - the failed jobs, newest first, with the error and whether the
  input is still on disk to replay.
- `POST /dlq/{id}/replay` - re-queue it. The job keeps its id, so anything
  already tracking it (the .NET API's poller) picks the replay up.
- `DELETE /dlq/{id}` - discard it and its payload.

**Other**

- `GET /health` - Redis connectivity plus queue depth, worker count and DLQ
  size. Returns `503` if Redis is unreachable.
- `GET /organs` - available organ keys + display names.

## Configuration

| Variable | Default | What it does |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Queue and job state |
| `JOB_DIR` | `/app/jobs` | Shared payload store; API and workers both mount it |
| `MODEL_DIR` | `/app/models` | Where downloaded bundle weights are cached |
| `MAX_QUEUE_DEPTH` | `50` | Backlog ceiling; new jobs get `503` past it |
| `JOB_MAX_ATTEMPTS` | `3` | Attempts per job, including the first |
| `JOB_RETRY_INTERVALS` | `10,30` | Backoff in seconds before each retry. A floor, not an exact delay: a delayed retry is picked up by the worker's scheduler on its next tick, so short backoffs round up to roughly that interval |
| `JOB_TIMEOUT_SECONDS` | `1800` | A job running longer than this is killed |
| `JOB_RETENTION_SECONDS` | `86400` | Age at which the janitor reclaims job directories |
| `MAINTENANCE_INTERVAL_SECONDS` | `60` | How often a worker re-checks that the retry scheduler is alive - the ceiling on how long a delayed retry can stall after a worker restart |

Each job runs in a forked work horse and loads its model there, from the
cache under `MODEL_DIR`. That costs a model load per job, and it is
deliberate: the worker process must not import torch itself, because
libgomp (torch's OpenMP runtime on Linux) is not fork-safe - a parent that
has already started OpenMP threads leaves the child deadlocked at 0% CPU
the first time it hits a parallel region. Isolation per job is worth more
here than the second it saves.

Pretrained weights are downloaded automatically on first use per model and
cached under `MODEL_DIR` - the first `spleen` job and the first job for any
*other* organ (which triggers the larger `wholeBody_ct_segmentation`
download) will each be slower than subsequent ones.

## Local development (without Docker)

You need a Redis instance for the queue; the quickest is
`docker run -p 6379:6379 redis:7-alpine`.

```bash
cd ai-service
python3.11 -m venv .venv
source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

export REDIS_URL=redis://localhost:6379/0
export JOB_DIR=$(pwd)/.jobs
export MODEL_DIR=$(pwd)/models

# terminal 1 - HTTP API (never loads a model)
uvicorn app.main:app --reload --port 8001

# terminal 2 - one worker (this is what runs inference)
python -m app.worker
```

Both processes need the same `REDIS_URL` and `JOB_DIR`. Start more workers to
run more jobs at once - each one takes a single job at a time.
