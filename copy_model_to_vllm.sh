#!/bin/bash
# Script to rename final_model with timestamp and copy to vLLM server
# Usage: ./copy_model_to_vllm.sh
# Run this AFTER training completes

set -e  # Exit on error

TRAINING_SERVER="35.202.149.44"
VLLM_SERVER="10.128.0.78"  # Internal IP
SSH_KEY="/root/.ssh/id_rsa"
CHECKPOINT_DIR="/root/hydra/trained_model_checkpoints"
FINAL_MODEL="$CHECKPOINT_DIR/final_model"

echo "========================================"
echo "Copy Trained Model to vLLM Server"
echo "========================================"

# Check if final_model exists
if [ ! -d "$FINAL_MODEL" ]; then
    echo "Error: $FINAL_MODEL not found"
    echo "Make sure training has completed successfully"
    exit 1
fi

# Generate timestamp from model's modification time (when it was saved)
TIMESTAMP=$(date -r "$FINAL_MODEL" +%Y%m%d_%H%M%S)
TIMESTAMPED_MODEL="$CHECKPOINT_DIR/final_model_$TIMESTAMP"

echo "Source model: $FINAL_MODEL"
echo "Timestamp: $TIMESTAMP"
echo "Timestamped model: $TIMESTAMPED_MODEL"
echo ""

# Rename final_model to timestamped name
echo "[1/3] Renaming final_model to final_model_$TIMESTAMP..."
if [ -d "$TIMESTAMPED_MODEL" ]; then
    echo "Warning: $TIMESTAMPED_MODEL already exists, skipping rename"
else
    mv "$FINAL_MODEL" "$TIMESTAMPED_MODEL"
    echo "✓ Renamed to final_model_$TIMESTAMP"
fi

# Verify model files exist
echo ""
echo "[2/3] Verifying model files..."
if [ ! -f "$TIMESTAMPED_MODEL/config.json" ]; then
    echo "Error: config.json not found in $TIMESTAMPED_MODEL"
    exit 1
fi
MODEL_SIZE=$(du -sh "$TIMESTAMPED_MODEL" | cut -f1)
echo "✓ Model verified ($MODEL_SIZE)"

# Copy to vLLM server
VLLM_MODEL_PATH="/root/models/trained_$TIMESTAMP"
echo ""
echo "[3/3] Copying to vLLM server..."
echo "Destination: $VLLM_SERVER:$VLLM_MODEL_PATH"
echo ""

rsync -avz --progress \
  -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
  "$TIMESTAMPED_MODEL/" \
  "root@$VLLM_SERVER:$VLLM_MODEL_PATH/"

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ Model copied successfully"
    echo ""
    echo "========================================"
    echo "Model deployed:"
    echo "  Training server: $TIMESTAMPED_MODEL"
    echo "  vLLM server: $VLLM_MODEL_PATH"
    echo "========================================"
    echo ""
    echo "To use this model for evaluation:"
    echo "  ./run_evals.sh trained_$TIMESTAMP 4096"
    echo ""
    echo "Or update run_vllm.sh to support:"
    echo "  ./run_vllm.sh trained_$TIMESTAMP"
else
    echo "Error: Failed to copy model to vLLM server"
    exit 1
fi
