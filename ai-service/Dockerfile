FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY start-all.sh ./start-all.sh
RUN chmod +x ./start-all.sh

ENV MODEL_DIR=/app/models \
    JOB_DIR=/app/jobs
EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -f http://localhost:${PORT:-8001}/health || exit 1

# One image, three ways to run it:
#   default          API + one worker in the same container (single-container hosts)
#   uvicorn ...      API only          (docker-compose "ai-service")
#   python -m app.worker   worker only (docker-compose "ai-worker")
CMD ["./start-all.sh"]
