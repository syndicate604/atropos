#!/bin/bash
# Script to start secure_code_review_env.py serve with proper configuration
# Usage: ./run_serve.sh [max_token_length] [total_steps]
# Example: ./run_serve.sh 512 1000

# Default values
MAX_TOKEN_LENGTH=${1:-512}
TOTAL_STEPS=${2:-1000}

# Validate inputs
if ! [[ "$MAX_TOKEN_LENGTH" =~ ^[0-9]+$ ]]; then
    echo "Error: max_token_length must be a number"
    echo "Usage: ./run_serve.sh [max_token_length] [total_steps]"
    exit 1
fi

if ! [[ "$TOTAL_STEPS" =~ ^[0-9]+$ ]]; then
    echo "Error: total_steps must be a number"
    echo "Usage: ./run_serve.sh [max_token_length] [total_steps]"
    exit 1
fi

# Check if API is running, start if needed
echo "Checking Atropos API status..."
if ! curl -s http://127.0.0.1:8000/status >/dev/null 2>&1; then
    echo "⚠ API not responding; starting it..."
    /root/hydra/run_api.sh 0.0.0.0 8000 /tmp/atropos_api.log
    sleep 2
else
    echo "✓ API is already running"
fi

# Kill any existing serve process
echo "Checking for existing serve processes..."
pkill -f "secure_code_review_env.py serve" && echo "Killed existing serve process" || echo "No existing serve process found"
sleep 2

# Set memory optimization
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# Create timestamp for log file
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOGFILE="/tmp/scr_serve_${TIMESTAMP}.log"

echo "========================================"
echo "Starting secure_code_review_env serve"
echo "========================================"
echo "Configuration:"
echo "  max_token_length: $MAX_TOKEN_LENGTH"
echo "  total_steps: $TOTAL_STEPS"
echo "  Log file: $LOGFILE"
echo "========================================"

cd /root/hydra

# Start serve in background
nohup python3 -u /root/hydra/environments/hydra/secure_code_review_env.py serve \
  --slurm false \
  --openai.base_url http://10.128.0.78:9004/v1 \
  --openai.model_name Qwen/Qwen2.5-7B-Instruct \
  --openai.server_type vllm \
  --env.rollout_server_url http://127.0.0.1:8000 \
  --env.tokenizer_name Qwen/Qwen2.5-7B-Instruct \
  --env.max_token_length $MAX_TOKEN_LENGTH \
  --env.total_steps $TOTAL_STEPS \
  --env.steps_per_eval 0 \
  --env.eval_handling NONE \
  --env.max_num_workers 16 \
  --env.max_batches_offpolicy 20 \
  --env.ensure_scores_are_not_same false \
  --env.use_wandb false \
  > "$LOGFILE" 2>&1 &

SERVE_PID=$!

echo ""
echo "Started serve process with PID: $SERVE_PID"
echo ""
echo "Waiting for server to start..."
sleep 10

# Check if process is still running
if ps -p $SERVE_PID > /dev/null; then
    echo "✓ Serve process is running"

    # Check if server is responding
    if curl -s http://localhost:8000/status > /dev/null 2>&1; then
        echo "✓ Server is responding on port 8000"
    else
        echo "⚠ Server not responding yet on port 8000 (may need more time)"
    fi

    echo ""
    echo "Monitor with: tail -f $LOGFILE"
    echo "Stop with: pkill -f 'secure_code_review_env.py serve'"
else
    echo "✗ Serve process failed to start"
    echo "Check logs: tail -50 $LOGFILE"
    exit 1
fi

echo ""
echo "Latest log output:"
tail -20 "$LOGFILE"
