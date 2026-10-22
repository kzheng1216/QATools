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

echo "[startup] Starting Vite dev server on http://localhost:9898"
echo "[startup] Make sure the backend is running: cd ../backend && ./startup.sh (127.0.0.1:9888)"
echo "[startup] Logging to $LOG_FILE"
nohup npm run dev >> "$LOG_FILE" 2>&1 &
