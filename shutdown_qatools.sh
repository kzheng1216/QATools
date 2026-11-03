#!/usr/bin/env bash
# Shutdown script for the QATools backend and frontend.
# Shuts down the backend and frontend servers.
set -e

cd "$(dirname "$0")"
echo "Shutting down QATools backend..."
./backend/shutdown.sh
echo "Shutting down QATools frontend..."
./frontend/shutdown.sh
echo "QATools shut down successfully"
