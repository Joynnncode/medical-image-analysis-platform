#!/bin/bash
# Runs the HTTP API and one queue worker in a single container.
#
# Docker Compose runs them as separate services (which is what you want -
# workers scale independently). This script is for hosts that only give you
# one process/container per service, such as Render's free tier, where a
# dedicated background worker isn't available.
set -euo pipefail

python -m app.worker &
worker_pid=$!

uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8001}" &
api_pid=$!

shutdown() {
    kill "$worker_pid" "$api_pid" 2>/dev/null || true
    wait
}
trap shutdown TERM INT

# If either half dies, take the container down so the platform restarts it -
# an API with no worker behind it would just queue work nobody runs.
wait -n
shutdown
exit 1
