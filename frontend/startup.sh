#!/usr/bin/env bash
# Startup script for the QATools frontend (Vite + React + antd).
# Installs dependencies on first run, then starts the dev server.
set -e

cd "$(dirname "$0")"

if [ ! -d node_modules ]; then
  echo "[startup] node_modules not found, installing dependencies..."
  npm install
fi

LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/frontend.$(date +%F).log"

# Log retention: keep only the most recent 7 daily log files (same policy as the
# backend logger, which retains 7 rotated files).
LOG_RETENTION_DAYS=7
ls -1t "$LOG_DIR"/frontend.*.log 2>/dev/null \
  | tail -n +$((LOG_RETENTION_DAYS + 1)) \
  | while IFS= read -r old_log; do
      echo "[startup] removing old log: $old_log"
      rm -f "$old_log" 2>/dev/null || true
    done
# Also drop anything older than 7 days, even if fewer files exist.
find "$LOG_DIR" -maxdepth 1 -type f -name 'frontend.*.log' -mtime +6 \
  -exec rm -f {} \; 2>/dev/null || true

echo "[startup] Starting Vite dev server on http://localhost:9898"
echo "[startup] Make sure the backend is running: cd ../backend && ./startup.sh (127.0.0.1:9888)"
echo "[startup] Logging to $LOG_FILE"
nohup npm run dev >> "$LOG_FILE" 2>&1 &
