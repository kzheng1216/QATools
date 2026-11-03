#!/usr/bin/env bash
# Shutdown script for the QATools frontend.
# Shuts down the frontend server.

cd "$(dirname "$0")"
echo "Shutting down QATools frontend..."

find_pids() {
    ps aux | grep '[n]pm run dev' | awk '{print $2}' | sort -u
    # Vite is started by npm run dev; kill it too so the port is freed.
    ps aux | grep '[v]ite' | grep -E '9898|QATools/frontend' | awk '{print $2}' | sort -u
}

max_attempts=3 # 1 initial + 2 retries
attempt=1

while [ "$attempt" -le "$max_attempts" ]; do
    pids=$(find_pids)
    if [ -z "$pids" ]; then
        echo "QATools frontend shut down successfully"
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

echo "Failed to shut down QATools frontend after ${max_attempts} attempts" >&2
exit 1
