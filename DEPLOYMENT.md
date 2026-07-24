# Deploying for free — one account (Render)

This deploys the whole platform live on the internet at **$0/month**, all
under a **single Render account** — no juggling multiple sign-ups.

Render hosts all four pieces:
- **Static Site** — the React frontend (free forever, no expiry)
- **Web Service** — the .NET API (free forever, sleeps after ~15 min idle)
- **Web Service** — the Python AI service (free forever, same sleep behavior)
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

## 2. AI service

- New + → Web Service → select your repo
- Root Directory: `ai-service`
- Runtime: Docker, Instance Type: **Free**
- Name: `medimg-ai-service` (or anything)
- Create Web Service, wait for the build, then copy its public URL
  (e.g. `https://medimg-ai-service.onrender.com`)

## 3. API

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
  | `AiService__BaseUrl` | the AI service URL from step 2 |
  | `Storage__Root` | `/app/storage` |
  | `Cors__AllowedOrigins__0` | `http://localhost:5173` (placeholder — updated in step 5) |

- Create Web Service, wait for the build, then copy its public URL
  (e.g. `https://medimg-api.onrender.com`)

## 4. Frontend

- New + → Static Site → same repo
- Root Directory: `frontend`
- Build Command: `npm install && npm run build`
- Publish Directory: `dist`
- Environment variable:

  | Key | Value |
  |---|---|
  | `VITE_API_BASE_URL` | `<your API URL from step 3>/api`, e.g. `https://medimg-api.onrender.com/api` |

- Under **Redirects/Rewrites**, add one rule so React Router works on refresh:
  - Source: `/*`  →  Destination: `/index.html`  →  Action: **Rewrite**
- Create Static Site, wait for the build, then copy its URL
  (e.g. `https://medimg-frontend.onrender.com`)

## 5. Close the loop: fix CORS

Go back to the `medimg-api` service → Environment → edit
`Cors__AllowedOrigins__0` to your real frontend URL from step 4 (no trailing
slash). Saving triggers a redeploy.

## 6. Try it

Visit your frontend URL, register an account, upload a `.nii.gz` scan, and
run segmentation. The first request to a sleeping service will be slow —
that's expected, not broken.

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
