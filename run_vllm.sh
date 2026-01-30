#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-base}"   # base|trained|/abs/path/to/model
PORT="${2:-9004}"

# Determine model path and log file based on target
if [[ "${TARGET}" == "base" ]]; then
    MODEL="/root/models/Qwen2.5-7B-Instruct"
    LOG="/tmp/vllm_base.log"
elif [[ "${TARGET}" == "trained" ]]; then
    MODEL="/root/models/trained_model"
    LOG="/tmp/vllm_trained.log"
else
    MODEL="${TARGET}"
    LOG="/tmp/vllm_custom.log"
fi

echo "========================================"
echo "Starting vLLM Server"
echo "========================================"
echo "Model: ${MODEL}"
echo "Port:  ${PORT}"
echo "Log:   ${LOG}"
echo "========================================"

# Kill only vLLM process on this specific port (not all python processes!)
pkill -f "example_trainer/vllm_api_server.py.*--port ${PORT}" >/dev/null 2>&1 || true
sleep 2

cd /root/hydra

nohup python3 -u example_trainer/vllm_api_server.py \
  --model "${MODEL}" \
  --port "${PORT}" \
  --host 0.0.0.0 \
  --dtype bfloat16 \
  --gpu-memory-utilization 0.88 \
  --max-model-len 8192 \
  --max-num-seqs 16 \
  --max-num-batched-tokens 16384 \
  --enable-prefix-caching \
  --trust-remote-code \
  > "${LOG}" 2>&1 &

VLLM_PID=$!
echo ""
echo "Started vLLM with PID: ${VLLM_PID}"
echo ""
echo "Waiting for vLLM to initialize..."

# Retry health check (model loading can take 30-60 seconds)
MAX_RETRIES=60
RETRY_COUNT=0
VLLM_UP=false

while [[ ${RETRY_COUNT} -lt ${MAX_RETRIES} ]]; do
    if curl -s "http://127.0.0.1:${PORT}/health_generate" >/dev/null 2>&1; then
        VLLM_UP=true
        break
    fi

    # Show progress every 5 seconds
    if [[ $((RETRY_COUNT % 5)) -eq 0 ]]; then
        echo "  Still waiting... (${RETRY_COUNT}s elapsed)"
    fi

    sleep 1
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [[ "${VLLM_UP}" == "true" ]]; then
    echo "✓ vLLM is fully responding on port ${PORT} (after ${RETRY_COUNT}s)"
    echo ""
    echo "KV cache info:"
    tail -20 "${LOG}" | grep -E "(Uvicorn|KV cache)" || tail -20 "${LOG}"
    echo ""
    echo "Monitor with: tail -f ${LOG}"
    echo "Stop with: pkill -f 'example_trainer/vllm_api_server.py.*--port ${PORT}'"
else
    # Check if at least /health is responding
    if curl -s "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
        echo "⚠ vLLM /health responding but /health_generate timed out after ${MAX_RETRIES}s"
        echo "Model may still be loading - check logs"
    else
        echo "✗ vLLM not responding after ${MAX_RETRIES} seconds on port ${PORT}"
    fi
    echo ""
    echo "Last 50 lines of log:"
    tail -50 "${LOG}" || true
    exit 1
fi
