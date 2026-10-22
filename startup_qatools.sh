#!/usr/bin/env bash
# Startup script for the QATools backend and frontend.
# Starts the backend and frontend servers.
set -e

cd "$(dirname "$0")"
echo "Starting QATools backend..."
./backend/startup.sh
echo "Starting QATools frontend..."
./frontend/startup.sh
echo "QATools started successfully"