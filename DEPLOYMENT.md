# Deploying for free (Vercel + Render + Neon)

This deploys the whole platform live on the internet at **$0/month**, using:

- **[Neon](https://neon.tech)** — free Postgres (serverless, auto-sleeps, never expires)
- **[Render](https://render.com)** — free web services for the .NET API and the Python AI service
- **[Vercel](https://vercel.com)** — free static hosting for the React frontend

**The tradeoff:** free Render services sleep after ~15 minutes of no traffic.
The first request after that takes 30s-2min to wake up (the AI service is
slower, since it has to reload the PyTorch model into memory). After that,
it's fast until it goes idle again. There's also no persistent disk on
Render's free plan — uploaded scans/masks live on the container's disk and
are **lost on restart or redeploy**. Fine for a personal/demo project; if you
need scans to survive restarts, upgrade that one Render service to a paid
plan with a persistent disk later.

You'll need to create free accounts on all three sites yourself (no card
required for any of them) — sign-ups and OAuth/GitHub-linking steps can't be
done on your behalf. Everything below is copy/paste once you're signed in.

---

## 1. Database — Neon

1. Sign up at [neon.tech](https://neon.tech) (GitHub login works).
2. Create a new project (any name/region).
3. On the project dashboard, copy the **connection string**. It looks like:
   ```
   postgresql://<user>:<password>@<host>.neon.tech/<dbname>?sslmode=require
   ```
4. Convert it to .NET/Npgsql format (same values, different syntax):
   ```
   Host=<host>.neon.tech;Port=5432;Database=<dbname>;Username=<user>;Password=<password>;SSL Mode=Require;Trust Server Certificate=true
   ```
   Save this — you'll paste it into Render in step 2.

## 2. API + AI service — Render

1. Sign up at [render.com](https://render.com) (GitHub login works) and
   authorize Render to access the `medical-image-analysis-platform` repo.

2. **Deploy the AI service first:**
   - New + → Web Service → select your repo
   - Root Directory: `ai-service`
   - Runtime: Docker
   - Instance Type: Free
   - Name: `medimg-ai-service` (or anything — just note the URL it gives you)
   - Create Web Service, wait for the build, then copy its public URL
     (e.g. `https://medimg-ai-service.onrender.com`)

3. **Deploy the API:**
   - New + → Web Service → same repo
   - Root Directory: `backend/MedicalImageAnalysis.Api`
   - Runtime: Docker
   - Instance Type: Free
   - Name: `medimg-api`
   - Environment variables:

     | Key | Value |
     |---|---|
     | `ASPNETCORE_ENVIRONMENT` | `Production` |
     | `ConnectionStrings__Default` | the Neon connection string from step 1 |
     | `Jwt__Key` | a long random secret — see below |
     | `Jwt__Issuer` | `MedicalImageAnalysis` |
     | `AiService__BaseUrl` | the AI service URL from step 2 |
     | `Storage__Root` | `/app/storage` |
     | `Cors__AllowedOrigins__0` | `http://localhost:5173` (placeholder — you'll update this in step 4) |

     A ready-to-use random `Jwt__Key` (generated for this project, safe to
     use, don't reuse it elsewhere): `8eINJCtMTculuv18zSkXyKI3HkhfjC3sD0IOBIJXuds=`

   - Create Web Service, wait for the build, then copy its public URL
     (e.g. `https://medimg-api.onrender.com`)

## 3. Frontend — Vercel

1. Sign up at [vercel.com](https://vercel.com) (GitHub login works).
2. Add New → Project → import the `medical-image-analysis-platform` repo.
3. Root Directory: `frontend` (Vercel should auto-detect the Vite preset).
4. Environment variable:

   | Key | Value |
   |---|---|
   | `VITE_API_BASE_URL` | `<your Render API URL>/api`, e.g. `https://medimg-api.onrender.com/api` |

5. Deploy. Copy the resulting URL (e.g. `https://medical-image-analysis-platform.vercel.app`).

## 4. Close the loop: fix CORS

Go back to the `medimg-api` service in Render → Environment → edit
`Cors__AllowedOrigins__0` to your real Vercel URL from step 3 (no trailing
slash). Saving triggers a redeploy.

## 5. Try it

Visit your Vercel URL, register an account, upload a `.nii.gz` scan, and run
segmentation. Remember: the very first request to a sleeping service will be
slow — that's expected, not broken.

## Local development is unaffected

Everything above is for the live deployment. `docker compose up` and the
manual local setup in the main [README](README.md) still work exactly as
before — Render's `PORT` env var only takes effect when it's actually set,
which local Docker Compose doesn't do.
