#!/usr/bin/env bash
# Run the end-to-end suite against a local stack.
#
#   ./tests/run.sh                       everything
#   ./tests/run.sh test_click_path.py    just the happy path
#   ./tests/run.sh -k busy --keep-logs   one behaviour, keeping the logs
#
# Needs a Postgres server (`brew services start postgresql@16`) and the .NET
# SDK. Creates its own throwaway database and never touches the dev one.
set -euo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$TESTS_DIR/.venv"
PYTHON="${MEDIMG_TEST_PYTHON:-/opt/homebrew/bin/python3.11}"

if [ ! -x "$PYTHON" ]; then
  PYTHON="$(command -v python3.11 || command -v python3)"
fi

if [ ! -d "$VENV" ]; then
  echo "Creating $VENV with $PYTHON"
  "$PYTHON" -m venv "$VENV"
fi

# Cheap check: reinstall only when the requirements file is newer than the
# marker the last install left behind.
STAMP="$VENV/.requirements-stamp"
if [ ! -f "$STAMP" ] || [ "$TESTS_DIR/requirements.txt" -nt "$STAMP" ]; then
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$TESTS_DIR/requirements.txt"
  touch "$STAMP"
fi

cd "$TESTS_DIR"
exec "$VENV/bin/pytest" "$@"
