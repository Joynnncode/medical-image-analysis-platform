# Medical Image Analysis Platform

A full-stack demo platform for uploading CT scans (NIfTI format), running an
AI segmentation model on them, and viewing the results in the browser.

> **Educational / portfolio project. Not a medical device.** The included
> model is a research-grade demo (trained on a public academic dataset) and
> is not validated for clinical use. Do not upload real patient data.

![Dashboard](docs/screenshots/dashboard.png)
![Scan detail with segmentation overlay](docs/screenshots/scan-detail.png)

## Architecture

```
React (Vite)  --->  ASP.NET Core API  --->  Python FastAPI AI service
   :5173             :5283 / :8080              :8001
                          |
                     PostgreSQL
```

- **Frontend** (`frontend/`): React + TypeScript + Vite. Handles auth,
  scan upload, and volume visualization via [Niivue](https://niivue.github.io/niivue/).
- **Backend** (`backend/MedicalImageAnalysis.Api/`): ASP.NET Core Web API.
  Owns users, JWT auth, scan/file storage, and orchestrates calls to the AI
  service. Persists metadata in PostgreSQL via EF Core.
- **AI service** (`ai-service/`): Python + FastAPI. Runs a pretrained
  [MONAI](https://monai.io/) 3D UNet (`spleen_ct_segmentation` from the
  MONAI Model Zoo, trained on the Medical Segmentation Decathlon Task09_Spleen
  dataset) to segment the spleen in a CT volume.

## Features

- Register / log in (JWT-based auth)
- Upload a CT scan in NIfTI format (`.nii` / `.nii.gz`)
- Run spleen segmentation on a scan
- View the scan and segmentation overlay in an interactive 3D viewer
- See segmentation stats (voxel count, estimated volume in mL, inference time)

## Deploying it live (free)

Want a real public URL instead of running it locally? See
[DEPLOYMENT.md](DEPLOYMENT.md) for a $0/month setup — everything hosted
under a single Render account.

## Running it

### Option A: Docker Compose (recommended)

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/) to
be installed and running.

```bash
cp .env.example .env
# edit .env if you want to change the generated dev secrets

docker compose up --build
```

Then open:
- Frontend: http://localhost:5173
- API (Swagger): http://localhost:5283/swagger
- AI service (docs): http://localhost:8001/docs

The AI service downloads its pretrained weights (~tens of MB) automatically
on the first segmentation request, so the first run of `/segment` will be
slower than subsequent ones.

### Option B: Run everything locally without Docker

Useful if Docker isn't set up yet, or for active development.

**Prerequisites:** Node 20+, .NET 10 SDK, Python 3.11, PostgreSQL.

1. **Database**

   ```bash
   # e.g. via Homebrew on macOS
   brew install postgresql@16
   brew services start postgresql@16
   psql -d postgres -c "CREATE USER medimg WITH PASSWORD 'medimg_dev_password';"
   psql -d postgres -c "CREATE DATABASE medimg OWNER medimg;"
   ```

2. **AI service**

   ```bash
   cd ai-service
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8001
   ```

3. **Backend API**

   ```bash
   cd backend/MedicalImageAnalysis.Api
   dotnet run --launch-profile http
   ```

   This applies EF Core migrations automatically on startup and listens on
   `http://localhost:5283`.

4. **Frontend**

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

   Open http://localhost:5173.

## Project layout

```
frontend/               React + Vite + TypeScript SPA
backend/
  MedicalImageAnalysis.Api/   ASP.NET Core Web API (auth, scans, storage)
ai-service/             FastAPI + MONAI segmentation service
docker-compose.yml      Wires all services + Postgres together
```

## Configuration

Backend settings (`backend/MedicalImageAnalysis.Api/appsettings.json`) and
Docker Compose (`.env`, copy from `.env.example`) both expose:

| Setting | Purpose |
|---|---|
| `ConnectionStrings:Default` | PostgreSQL connection string |
| `Jwt:Key` | Secret used to sign JWTs — **change this** for anything beyond local testing |
| `AiService:BaseUrl` | Where the API reaches the AI service |
| `Storage:Root` | Where uploaded scans / masks are stored on disk |

## Security / scope notes

- This is a demo project: JWT secrets and DB passwords ship with insecure
  defaults meant for local use only. Rotate them (`openssl rand -base64 32`)
  before exposing this anywhere beyond your own machine.
- File storage is local disk, not encrypted at rest.
- No rate limiting, audit logging, or HIPAA/PHI safeguards are implemented —
  this is not suitable for real patient data.

## License

MIT
