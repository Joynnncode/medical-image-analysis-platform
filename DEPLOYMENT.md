# Deploying for free — one account (Render)

This deploys the whole platform live on the internet at **$0/month**, all
under a **single Render account** — no juggling multiple sign-ups.

Render hosts all five pieces:
- **Static Site** — the React frontend (free forever, no expiry)
- **Web Service** — the .NET API (free forever, sleeps after ~15 min idle)
- **Web Service** — the Python AI service (free forever, same sleep behavior).
  This one container runs both the job API *and* a queue worker — see the
  note in step 3.
- **Key Value** — free Redis-compatible instance, used as the segmentation
  job queue
- **PostgreSQL** — free database (expires after 90 days — see the note at
  the bottom for how to renew it in ~2 minutes when that happens)

**The tradeoffs, plainly:**
- Free web services sleep after ~15 minutes of no traffic. The first
  request after that takes 30s-2min to wake up (the AI service is slower,
  since it has to reload the PyTorch model into memory). After that, it's
  fast until it goes idle again.
- No persistent disk on Render's free plan — uploaded scans/masks live on
  the container's disk and are **lost on restart or redeploy**. Fine for a
  personal/demo project; upgrade that one service to a paid plan with a
  persistent disk if you need scans to survive restarts.
- The free Postgres database **expires after 90 days** and needs to be
  recreated (not upgraded automatically). See the last section for the
  2-minute fix when that happens.
- Render's free plan has no **Background Worker** service type, so the AI
  service container runs one queue worker alongside its HTTP API (the
  image's default `start-all.sh` does exactly this). Segmentation still
  runs as a proper background job with progress and retries — there is just
  one worker, and it shares the instance's memory with the API. Anywhere
  with a worker service type (or Docker Compose locally), run the workers
  as their own service and scale them independently.
- The free Key Value instance has no persistence and a small memory cap. If
  it evicts a job, the API notices the job has vanished and marks that scan
  as failed rather than waiting forever — re-run the segmentation.
- The AI service now loads one of two models depending on which organ you
  pick: a small dedicated model for spleen, or a larger multi-organ model
  for everything else (liver, kidneys, gallbladder, stomach, pancreas,
  bladder). Whichever ones get used stay cached in memory, so if you try
  several different organs in one session, memory use adds up. Render's
  free instance (512MB RAM) may not be enough for the multi-organ model -
  if segmentation requests for non-spleen organs fail or the service
  crashes, that's why; upgrade just that one service to a paid instance
  with more RAM.

You'll need to create one free account at [render.com](https://render.com)
yourself (GitHub login works, no card required) and authorize it to access
the `medical-image-analysis-platform` repo — that one step can't be done on
your behalf. Everything else below is copy/paste once you're signed in.

---

## 1. Database

- New + → PostgreSQL
- Name: anything (e.g. `medimg-db`), Plan: **Free**
- Create Database, wait for it to spin up
- Copy the **Internal Database URL** (starts with `postgres://...`) — using
  the internal one (not external) is faster since the API lives on Render too
- Convert it to .NET/Npgsql format. Given:
  ```
  postgres://<user>:<password>@<host>/<dbname>
  ```
  write it as:
  ```
  Host=<host>;Port=5432;Database=<dbname>;Username=<user>;Password=<password>;SSL Mode=Require;Trust Server Certificate=true
  ```
  Save this for step 3.

## 2. Job queue (Key Value)

Note "Key Value", not "Project" — a Project is just a folder for grouping
services. New instances run Valkey (a Redis fork), which the AI service's
Redis client and RQ treat as a drop-in replacement.

- New + → Key Value (direct link: `dashboard.render.com/new/redis`)
- Name: anything (e.g. `medimg-queue`)
- **Region: the same one you pick for the AI service in step 3.** The free
  internal connection only works between services in the same region.
- Maxmemory Policy: **`noeviction`**. The default LRU policies are meant for
  caches and will happily evict jobs that are still waiting to run.
- Instance Type: **Free**
- Create Key Value, then open it and use **Connect** (top right) to copy the
  **Internal Key Value URL** (starts with `redis://...`). Save it for step 3.

Free tier caveats, none of them blocking for a demo:

- One free Key Value instance per workspace.
- No persistence, and Render may restart the instance at any time — queued
  and in-flight jobs are lost when that happens. The API notices the job has
  vanished and marks that scan as failed rather than waiting forever, so
  re-running the segmentation is all that's needed.
- Unlike the free Postgres database, it does not expire.

## 3. AI service

- New + → Web Service → select your repo
- Root Directory: `ai-service`
- Runtime: Docker, Instance Type: **Free**
- Name: `medimg-ai-service` (or anything)
- Environment variables:

  | Key | Value |
  |---|---|
  | `REDIS_URL` | the internal Key Value URL from step 2 |
  | `JOB_DIR` | `/app/jobs` |
  | `MAX_QUEUE_DEPTH` | `10` (free instance — keep the backlog small) |

- Leave the start command alone. The image's default runs the HTTP API and
  one queue worker in the same container, which is what you want here:
  Render's free plan has no separate worker service type.
- Create Web Service, wait for the build, then copy its public URL
  (e.g. `https://medimg-ai-service.onrender.com`)

## 4. API

- New + → Web Service → same repo
- Root Directory: `backend/MedicalImageAnalysis.Api`
- Runtime: Docker, Instance Type: **Free**
- Name: `medimg-api`
- Environment variables:

  | Key | Value |
  |---|---|
  | `ASPNETCORE_ENVIRONMENT` | `Production` |
  | `ConnectionStrings__Default` | the connection string from step 1 |
  | `Jwt__Key` | `8eINJCtMTculuv18zSkXyKI3HkhfjC3sD0IOBIJXuds=` (a random secret generated for this project — safe to use, don't reuse it elsewhere) |
  | `Jwt__Issuer` | `MedicalImageAnalysis` |
  | `AiService__BaseUrl` | the AI service URL from step 3 |
  | `Storage__Root` | `/app/storage` |
  | `Cors__AllowedOrigins__0` | `http://localhost:5173` (placeholder — updated in step 6) |

- Create Web Service, wait for the build, then copy its public URL
  (e.g. `https://medimg-api.onrender.com`)

## 5. Frontend

- New + → Static Site → same repo
- Root Directory: `frontend`
- Build Command: `npm install && npm run build`
- Publish Directory: `dist`
- Environment variable:

  | Key | Value |
  |---|---|
  | `VITE_API_BASE_URL` | `<your API URL from step 4>/api`, e.g. `https://medimg-api.onrender.com/api` |

- Under **Redirects/Rewrites**, add one rule so React Router works on refresh:
  - Source: `/*`  →  Destination: `/index.html`  →  Action: **Rewrite**
- Create Static Site, wait for the build, then copy its URL
  (e.g. `https://medimg-frontend.onrender.com`)

## 6. Close the loop: fix CORS

Go back to the `medimg-api` service → Environment → edit
`Cors__AllowedOrigins__0` to your real frontend URL from step 5 (no trailing
slash). Saving triggers a redeploy.

## 7. Try it

Visit your frontend URL, register an account, upload a `.nii.gz` scan, and
run segmentation. The scan goes to `Queued`, then shows live progress while
the worker runs — you can close the tab and come back to a finished result.
The first request to a sleeping service will be slow — that's expected, not
broken.

---

## When the free database expires (~every 90 days)

Render's free Postgres is deleted after 90 days rather than auto-renewed.
When that happens:

1. New + → PostgreSQL → Free (same as step 1) — create a fresh one.
2. Copy its new Internal Database URL, convert it the same way as step 1.
3. Go to `medimg-api` → Environment → update `ConnectionStrings__Default`
   with the new value → saves and redeploys.

Your old scans/uploads in the previous database won't carry over (this is a
demo project's storage, not a backup system) — this just gets the app
running again in about 2 minutes.

## Local development is unaffected

Everything above is for the live deployment. `docker compose up` and the
manual local setup in the main [README](README.md) still work exactly as
before — Render's `PORT` env var only takes effect when it's actually set,
which local Docker Compose doesn't do.
