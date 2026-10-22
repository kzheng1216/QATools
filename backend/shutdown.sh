#!/usr/bin/env bash
# Shutdown script for the QATools backend.
# Shuts down the backend server.

cd "$(dirname "$0")"
echo "Shutting down QATools backend..."

find_pids() {
    ps aux | grep '[u]vicorn app:app' | awk '{print $2}'
}

max_attempts=3 # 1 initial + 2 retries
attempt=1

while [ "$attempt" -le "$max_attempts" ]; do
    pids=$(find_pids)
    if [ -z "$pids" ]; then
        echo "QATools backend shut down successfully"
        exit 0
    fi
    echo "Attempt ${attempt}/${max_attempts}: killing PIDs: ${pids}"
    for pid in $pids; do
        kill -9 "$pid" 2>/dev/null || true
    done
    sleep 0.5
    echo "Processes still running: ${pids}"
    attempt=$((attempt + 1))
done

echo "Failed to shut down QATools backend after ${max_attempts} attempts" >&2
exit 1
