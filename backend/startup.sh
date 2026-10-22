#!/usr/bin/env bash
# Start the QATools backend. Logging to file is owned by the Python logger
# (config/log.py TimedRotatingFileHandler -> logs/backend.log, rolled daily to
# backend.log.<date>, 7 days retained). uvicorn's own stdout/stderr is dropped
# to avoid a second, duplicate log file.
cd "$(dirname "$0")"

LOG_DIR="logs"
mkdir -p "$LOG_DIR"

# Resolve a Python that has uvicorn. Non-login shells (e.g. devcontainer
# postStartCommand) do NOT have the venv's bin on PATH, so a bare `uvicorn`
# fails with "No such file or directory". Find the venv python explicitly.
PY=""
for c in \
    /root/.virtualenvs/docker-ra/bin/python \
    /home/qauser/bot_env/bin/python \
    "$(command -v python3 2>/dev/null)" \
    "$(command -v python 2>/dev/null)"; do
    if [ -n "$c" ] && "$c" -c "import uvicorn" >/dev/null 2>&1; then
        PY="$c"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "ERROR: no Python with uvicorn found; cannot start backend" >&2
    exit 1
fi

nohup "$PY" -m uvicorn app:app --host 0.0.0.0 --port 9888 > /dev/null 2>&1 &
echo "Backend started with $PY, logging to $LOG_DIR/backend.log"
