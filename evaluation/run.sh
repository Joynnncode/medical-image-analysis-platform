#!/usr/bin/env bash
# Score the model against labelled scans. Arguments go straight to evaluate.py:
#
#   ./evaluation/run.sh --dataset evaluation/data/Task09_Spleen --organ spleen \
#       --label-value 1 --json evaluation/runs/spleen-$(date +%F).json
#
# Needs the real AI service running (see evaluation/README.md). The stub in
# tests/ is no use here: the point is the model.
set -euo pipefail

EVAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$EVAL_DIR/.venv"
PYTHON="${MEDIMG_TEST_PYTHON:-/opt/homebrew/bin/python3.11}"

if [ ! -x "$PYTHON" ]; then
  PYTHON="$(command -v python3.11 || command -v python3)"
fi

if [ ! -d "$VENV" ]; then
  echo "Creating $VENV with $PYTHON"
  "$PYTHON" -m venv "$VENV"
fi

STAMP="$VENV/.requirements-stamp"
if [ ! -f "$STAMP" ] || [ "$EVAL_DIR/requirements.txt" -nt "$STAMP" ]; then
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$EVAL_DIR/requirements.txt"
  touch "$STAMP"
fi

exec "$VENV/bin/python" "$EVAL_DIR/evaluate.py" "$@"
