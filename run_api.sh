#!/usr/bin/env bash
set -euo pipefail

HOST="${1:-0.0.0.0}"
PORT="${2:-8000}"
LOGFILE="${3:-/tmp/atropos_api.log}"

echo "========================================"
echo "Starting Atropos API"
echo "========================================"
echo "Host: ${HOST}"
echo "Port: ${PORT}"
echo "Log:  ${LOGFILE}"
echo "========================================"

# Kill only the API process for this specific port (matches what we actually start)
pkill -f "atroposlib.cli.run_api.*--port ${PORT}" >/dev/null 2>&1 || true
sleep 1

cd /root/hydra

nohup python3 -u -m atroposlib.cli.run_api --host "${HOST}" --port "${PORT}" > "${LOGFILE}" 2>&1 &

API_PID=$!
echo "Started API with PID: ${API_PID}"
echo ""

# Retry health check (up to 20 seconds)
echo "Waiting for API to respond..."
MAX_RETRIES=20
RETRY_COUNT=0
API_UP=false

while [[ ${RETRY_COUNT} -lt ${MAX_RETRIES} ]]; do
    if curl -s "http://127.0.0.1:${PORT}/status" >/dev/null 2>&1; then
        API_UP=true
        break
    fi
    sleep 1
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [[ "${API_UP}" == "true" ]]; then
    echo "✓ API is responding on port ${PORT} (after ${RETRY_COUNT}s)"
    echo ""
    echo "Monitor with: tail -f ${LOGFILE}"
    echo "Stop with: pkill -f 'atroposlib.cli.run_api.*--port ${PORT}'"
else
    echo "✗ API not responding after ${MAX_RETRIES} seconds on port ${PORT}"
    echo ""
    echo "Last 50 lines of log:"
    tail -50 "${LOGFILE}" || true
    exit 1
fi
