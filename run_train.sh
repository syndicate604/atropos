#!/usr/bin/env bash
set -euo pipefail

# One-button training script: starts API, serve, and GRPO training
# Usage: ./run_train.sh [max_token_length] [total_steps]

MAX_TOKEN_LENGTH="${1:-512}"
TOTAL_STEPS="${2:-1000}"

echo "========================================"
echo "GRPO Training Pipeline"
echo "========================================"
echo "Configuration:"
echo "  max_token_length: ${MAX_TOKEN_LENGTH}"
echo "  total_steps: ${TOTAL_STEPS}"
echo "========================================"
echo ""

# Step 1: Ensure API is running
echo "[1/3] Starting Atropos API..."
/root/hydra/run_api.sh 0.0.0.0 8000 /tmp/atropos_api.log
echo ""

# Step 2: Start serve with appropriate settings
echo "[2/3] Starting secure_code_review serve..."
/root/hydra/run_serve.sh "${MAX_TOKEN_LENGTH}" "${TOTAL_STEPS}"
echo ""

# Step 3: Start GRPO training
echo "[3/3] Starting GRPO training..."

# Kill any existing GRPO process
pkill -f "example_trainer/grpo.py" >/dev/null 2>&1 || true
sleep 2

# Set memory optimization
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# Create timestamp for log
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
GRPO_LOG="/tmp/grpo_${TIMESTAMP}.log"

cd /root/hydra

nohup python3 -u /root/hydra/example_trainer/grpo.py > "${GRPO_LOG}" 2>&1 &

GRPO_PID=$!

echo ""
echo "Started GRPO training with PID: ${GRPO_PID}"
echo ""
echo "Waiting for training to start..."
sleep 10

# Check if still running
if ps -p ${GRPO_PID} > /dev/null; then
    echo "✓ GRPO training is running"
    echo ""
    echo "Monitor progress:"
    echo "  tail -f ${GRPO_LOG}"
    echo ""
    echo "Check GPU usage:"
    echo "  watch -n 2 nvidia-smi"
    echo ""
    echo "Stop training:"
    echo "  pkill -f 'example_trainer/grpo.py'"
    echo ""
    echo "Latest log output:"
    tail -20 "${GRPO_LOG}"
else
    echo "✗ GRPO training failed to start"
    echo ""
    echo "Check logs: tail -100 ${GRPO_LOG}"
    exit 1
fi
