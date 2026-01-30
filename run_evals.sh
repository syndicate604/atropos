#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-}"
if [[ "$MODE" != "base" && "$MODE" != "trained" && ! "$MODE" =~ ^trained_[0-9]{8}_[0-9]{6}$ ]]; then
  echo "Usage: $0 {base|trained|trained_YYYYMMDD_HHMMSS} [max_token_length]"
  echo "Examples:"
  echo "  $0 base 4096"
  echo "  $0 trained 4096"
  echo "  $0 trained_20260130_044500 4096"
  exit 1
fi

MAX_TOKEN_LENGTH="${2:-4096}"
BASE_URL="${OPENAI_BASE_URL:-http://10.128.0.78:9004/v1}"
VLLM_HOST="${VLLM_HOST:-34.45.239.100}"
SSH_KEY="${SSH_KEY:-~/.ssh/gcp/ngcp_root_key}"
# Expand ~ in SSH key path
SSH_KEY="${SSH_KEY/#\~/$HOME}"

RUN_TS="$(date -u +%Y%m%d_%H%M%S)"
RUN_ID="${MODE}_${RUN_TS}"
OUT_DIR="evals/${RUN_ID}"
LOG_FILE="/tmp/eval_${RUN_ID}.log"
MODELS_FILE="${OUT_DIR}/vllm_models.json"

echo "========================================"
echo "Running Evaluation: ${MODE}"
echo "========================================"
echo "Configuration:"
echo "  MODE: ${MODE}"
echo "  max_token_length: ${MAX_TOKEN_LENGTH}"
echo "  vLLM Host: ${VLLM_HOST}"
echo "  vLLM URL: ${BASE_URL}"
echo "  SSH Key: ${SSH_KEY}"
echo "  Output dir: ${OUT_DIR}"
echo "========================================"
echo ""
echo "⚠ Ensure BASE_URL points to the same vLLM server!"
echo ""

# Step 1: Switch vLLM to correct model
echo "[1/3] Switching vLLM to ${MODE} model on ${VLLM_HOST}..."
ssh -i "${SSH_KEY}" "root@${VLLM_HOST}" "cd /root/hydra && ./run_vllm.sh ${MODE}"

if [[ $? -ne 0 ]]; then
    echo "✗ Failed to start vLLM with ${MODE} model"
    exit 1
fi

echo "✓ vLLM switched to ${MODE} model"
echo ""

# Wait for vLLM to be fully ready
echo "[2/3] Waiting for vLLM to stabilize..."
sleep 5

# Step 2: Prepare output directory
cd /root/hydra
mkdir -p "$OUT_DIR"

# Record what vLLM says it is serving (for provenance)
echo "Capturing vLLM model info..."
curl -s "${BASE_URL%/v1}/v1/models" > "$MODELS_FILE" 2>&1 || echo "{\"error\": \"Could not fetch model info\"}" > "$MODELS_FILE"

# Display what model is actually being served
echo "vLLM is now serving:"
SERVED_MODEL=$(cat "$MODELS_FILE" | jq -r '.data[0].id // "unknown"' 2>/dev/null || echo "unknown")
echo "  ${SERVED_MODEL}"

# Verify it matches expected mode
if [[ "${MODE}" == "base" ]]; then
    if [[ "${SERVED_MODEL}" == *"Qwen2.5"* ]]; then
        echo "✓ Model matches expected mode (base)"
    else
        echo "⚠ WARNING: Expected base model (Qwen2.5) but vLLM is serving: ${SERVED_MODEL}"
    fi
elif [[ "${MODE}" =~ ^trained ]]; then
    if [[ "${SERVED_MODEL}" == *"trained"* ]]; then
        echo "✓ Model matches expected mode (trained)"
        # For timestamped models, show which specific version
        if [[ "${MODE}" =~ ^trained_([0-9]{8}_[0-9]{6})$ ]]; then
            EXPECTED_TS="${BASH_REMATCH[1]}"
            if [[ "${SERVED_MODEL}" == *"${EXPECTED_TS}"* ]]; then
                echo "✓ Exact timestamp match: ${EXPECTED_TS}"
            else
                echo "⚠ WARNING: Expected ${MODE} but vLLM is serving: ${SERVED_MODEL}"
            fi
        fi
    else
        echo "⚠ WARNING: Expected trained model but vLLM is serving: ${SERVED_MODEL}"
    fi
fi
echo ""

# Set tokenizer - always use the base HuggingFace tokenizer
# The trained model is a fine-tune and uses the same tokenizer
TOKENIZER_NAME="Qwen/Qwen2.5-7B-Instruct"

echo "Using tokenizer: ${TOKENIZER_NAME}"
echo ""

# Step 3: Run evaluation
echo "[3/3] Starting evaluation..."
nohup python3 environments/hydra/secure_code_review_env.py evaluate \
  --openai.base_url "$BASE_URL" \
  --openai.model_name Qwen/Qwen2.5-7B-Instruct \
  --openai.server_type vllm \
  --env.tokenizer_name "$TOKENIZER_NAME" \
  --env.max_token_length "$MAX_TOKEN_LENGTH" \
  --env.data_dir_to_save_evals "$OUT_DIR" \
  --env.use_wandb false \
  > "$LOG_FILE" 2>&1 &

EVAL_PID=$!

echo ""
echo "Started eval with PID: ${EVAL_PID}"
echo ""
echo "Details:"
echo "  MODE: ${MODE}"
echo "  TOKENIZER: ${TOKENIZER_NAME}"
echo "  OUT_DIR: ${OUT_DIR}"
echo "  LOG_FILE: ${LOG_FILE}"
echo "  VLLM_MODELS_SNAPSHOT: ${MODELS_FILE}"
echo ""
echo "Monitor with: tail -f ${LOG_FILE}"
echo "Check results: cat ${OUT_DIR}/metrics.json"
