#!/bin/bash
# Runs the HTTP API and one queue worker in a single container.
#
# Docker Compose runs them as separate services (which is what you want -
# workers scale independently). This script is for hosts that only give you
# one process/container per service, such as Render's free tier, where a
# dedicated background worker isn't available.
set -uo pipefail

# Keep the worker running without letting it decide the container's fate. If
# it exits - a bug, an OOM kill, a broker that went away for good - restart
# it, but leave the API up: the API serves /health, which is where you find
# out that the queue is in trouble. A container that dies instead just fails
# its deploy and tells you nothing.
supervise_worker() {
    while true; do
        python -m app.worker
        echo "start-all: worker exited with status $?; restarting in 5s" >&2
        sleep 5
    done
}

supervise_worker &
worker_pid=$!

uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8001}" &
api_pid=$!

shutdown() {
    # The container runtime reaps anything still standing after this.
    kill "$worker_pid" "$api_pid" 2>/dev/null || true
    kill $(jobs -p) 2>/dev/null || true
}
trap shutdown TERM INT

# The API defines the container: if it stops, the container should stop too.
wait "$api_pid"
status=$?
shutdown
exit "$status"
