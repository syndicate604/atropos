#!/bin/bash
# HYDRA VM Setup Script
# Run on a fresh Deep Learning VM (A100/L4)

set -e

echo "=== HYDRA VM Setup ==="

# 1. System packages
echo "[1/5] Installing system packages..."
apt-get update -qq
apt-get install -y -qq docker.io git curl jq
systemctl start docker
systemctl enable docker
usermod -aG docker root 2>/dev/null || true

# 2. Python packages
echo "[2/5] Installing Python packages..."
pip install -q vllm aiohttp transformers huggingface_hub hf_transfer accelerate bitsandbytes

# 3. Install HYDRA
echo "[3/5] Installing HYDRA..."
cd ~/hydra 2>/dev/null || { echo "ERROR: Clone hydra repo to ~/hydra first"; exit 1; }
pip install -q -e .

# 4. Download model (7B by default)
MODEL_DIR=~/models/Qwen2.5-7B-Instruct
if [ ! -d "$MODEL_DIR" ]; then
    echo "[4/5] Downloading Qwen2.5-7B-Instruct..."
    HF_HUB_ENABLE_HF_TRANSFER=1 huggingface-cli download Qwen/Qwen2.5-7B-Instruct --local-dir $MODEL_DIR
else
    echo "[4/5] Model already exists at $MODEL_DIR"
fi

# 5. Build harness Docker image
echo "[5/5] Building harness Docker image..."
docker build -t hydra-harness:latest ~/hydra/environments/hydra/harness/

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Start vLLM:    python3 ~/hydra/example_trainer/vllm_api_server.py --model ~/models/Qwen2.5-7B-Instruct --port 9004 --gpu-memory-utilization 0.5"
echo "  2. Start API:     uvicorn atroposlib.api.server:app --host 0.0.0.0 --port 8000"
echo "  3. Start SCR:     python3 ~/hydra/environments/hydra/secure_code_review_env.py serve --slurm false --openai.base_url http://localhost:9004/v1 --openai.model_name ~/models/Qwen2.5-7B-Instruct --openai.server_type vllm --env.tokenizer_name ~/models/Qwen2.5-7B-Instruct --env.use_wandb false"
echo "  4. Run GRPO:      python3 ~/hydra/example_trainer/grpo.py"
