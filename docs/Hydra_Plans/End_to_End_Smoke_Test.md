# End-to-End Smoke Test Guide

**Purpose:** Validate the complete training and evaluation pipeline after script hardening.

**Duration:** ~1-2 hours (100 training steps + 2 evaluations)

---

## Prerequisites

### 1. Verify All Scripts are Deployed

**Training Server (35.202.149.44):**
```bash
ssh -i ~/.ssh/gcp/ngcp_root_key root@35.202.149.44
ls -lh /root/hydra/{run_*.sh,monitor_*.sh}

# Expected:
# -rwxr-xr-x run_api.sh
# -rwxr-xr-x run_serve.sh
# -rwxr-xr-x run_train.sh
# -rwxr-xr-x run_evals.sh
# -rwxr-xr-x monitor_train.sh
# -rwxr-xr-x monitor_train_tmux.sh
```

**vLLM Server (34.45.239.100):**
```bash
ssh -i ~/.ssh/gcp/ngcp_root_key root@34.45.239.100
ls -lh /root/hydra/run_vllm.sh

# Expected:
# -rwxr-xr-x run_vllm.sh
```

### 2. Check Available Disk Space

```bash
# Training server (needs space for checkpoints)
ssh -i ~/.ssh/gcp/ngcp_root_key root@35.202.149.44 "df -h /root"

# vLLM server (needs space for models)
ssh -i ~/.ssh/gcp/ngcp_root_key root@34.45.239.100 "df -h /root"
```

### 3. Verify Models Exist

**vLLM Server:**
```bash
ssh -i ~/.ssh/gcp/ngcp_root_key root@34.45.239.100 "
ls -lh /root/models/Qwen2.5-7B-Instruct/
ls -lh /root/models/trained_model/
"
```

---

## Step 1: Start vLLM with Base Model (5 minutes)

### On vLLM Server:
```bash
ssh -i ~/.ssh/gcp/ngcp_root_key root@34.45.239.100
cd /root/hydra

# Start base model
./run_vllm.sh base

# Expected output:
# ========================================
# Starting vLLM Server
# ========================================
# Model: /root/models/Qwen2.5-7B-Instruct
# Port:  9004
# Log:   /tmp/vllm_base.log
# ========================================
#
# Started vLLM with PID: XXXXX
#
# Waiting for vLLM to initialize...
#   Still waiting... (5s elapsed)
#   Still waiting... (10s elapsed)
#   ...
# ✓ vLLM is fully responding on port 9004 (after 35s)
```

### Verify vLLM is Serving:
```bash
# Check basic health (on vLLM server)
curl -s http://127.0.0.1:9004/health
# Returns: {"status":"ok"}

# Check health with generation (confirms model loaded)
curl -s http://127.0.0.1:9004/health_generate
# Returns: {"status":"ok","model_loaded":true}

# Check what model is loaded
curl -s http://127.0.0.1:9004/v1/models | jq

# Expected:
# {
#   "object": "list",
#   "data": [
#     {
#       "id": "/root/models/Qwen2.5-7B-Instruct",
#       "object": "model",
#       "created": 0,
#       "owned_by": "vllm"
#     }
#   ]
# }
```

### Check GPU Usage:
```bash
nvidia-smi

# Expected: ~14GB used (model loaded)
```

---

## Step 2: Run 100-Step Training (30-50 minutes)

### On Training Server:
```bash
ssh -i ~/.ssh/gcp/ngcp_root_key root@35.202.149.44
cd /root/hydra

# One-button training (starts API + serve + GRPO)
./run_train.sh 512 100

# Expected output:
# ========================================
# GRPO Training Pipeline
# ========================================
# Configuration:
#   max_token_length: 512
#   total_steps: 100
# ========================================
#
# [1/3] Starting Atropos API...
# ✓ API is responding on port 8000 (after 3s)
#
# [2/3] Starting secure_code_review serve...
# ✓ API is already running
# ✓ Serve process is running
# ✓ Server is responding on port 8000
#
# [3/3] Starting GRPO training...
# Started GRPO training with PID: XXXXX
```

### Monitor Training Progress:

**Option 1 - Consolidated Dashboard (Recommended):**
```bash
# Simple single-terminal dashboard (3s refresh)
./monitor_train.sh

# Or tmux 4-pane dashboard (interactive)
./monitor_train_tmux.sh
```

Both show: GPU status, process status, GRPO progress, serve queue, API activity

**Option 2 - Manual Monitoring (Fallback):**
```bash
# Terminal 1 - GRPO logs
tail -f /tmp/grpo_*.log

# Terminal 2 - GPU usage
watch -n 2 nvidia-smi

# Terminal 3 - Serve logs (optional)
tail -f /tmp/scr_serve_*.log
```

**What to watch for:**
- Step progress: Step 1/100 (1.0%) → 100/100 (100.0%)
- Loss values decreasing over time
- Checkpoints saved every 3 steps (plus final at step 100)
- Memory staying < 40GB
- No OOM errors
- GPU utilization 80-100%

**Example GRPO log output:**
```
================================================================================
Step 1/100 (1.0%)
Time: 2026-01-29 14:23:15
================================================================================

📊 Step Summary:
  Loss: 0.5234 (over 8 microbatches, 3072 tokens)
  Learning Rate: 1.00e-06
  Gradient Norm: 0.1234
  Advantages: mean=0.0012, std=0.0234, n=3072
  Pos LogP: -1.2345 | Neg LogP: -1.5678

⏱️  Timing:
  Step Time: 45.2s
  Avg Step Time (last 10): 45.2s
  ETA: 1h 14m (99 steps remaining)

💾 Memory:
  GPU: 28.5 GB / 40.0 GB (71.3%)
  Batches in Queue: 4

✅ Checkpoint saved (15.2GB in 8.3s)
```

### Expected Timeline:
- **Step 1-10:** ~5-10 minutes (initial generation slower)
- **Step 10-50:** ~15-20 minutes
- **Step 50-100:** ~15-20 minutes
- **Total:** ~35-50 minutes

The monitor scripts show live ETA estimates based on average step time.

### Success Criteria:
- ✅ Reaches step 100/100
- ✅ No OOM errors in logs
- ✅ Final checkpoint saved at `/root/hydra/trained_model_checkpoints/final_model/`
- ✅ GPU memory stayed under 40GB throughout

### If OOM Occurs:
```bash
# Check logs for memory errors
tail -100 /tmp/grpo_*.log | grep -i "oom\|memory\|cuda"

# Check what step it failed at
grep "Step.*/" /tmp/grpo_*.log | tail -5

# Check memory usage before crash (enhanced logging shows this)
grep "💾 Memory:" /tmp/grpo_*.log | tail -10
```

**Note:** The seq_len=512 + hard truncation in grpo.py should prevent OOM. If it still occurs:
- Verify grpo.py line 720: `training_steps=100`
- Verify grpo.py line 721: `seq_len=512`
- Check if truncation is working: `grep "Hard cap" /tmp/grpo_*.log`
- Report exact error and last memory reading

---

## Step 3: Copy Trained Model to vLLM Server (5 minutes)

### From Training Server:
```bash
ssh -i ~/.ssh/gcp/ngcp_root_key root@35.202.149.44

# Set up SSH key for rsync
scp -i ~/.ssh/gcp/ngcp_root_key ~/.ssh/gcp/ngcp_root_key /root/.ssh/id_rsa
chmod 600 /root/.ssh/id_rsa

# Copy trained model to vLLM server
rsync -avz --progress \
  -e 'ssh -i /root/.ssh/id_rsa -o StrictHostKeyChecking=no' \
  /root/hydra/trained_model_checkpoints/final_model/ \
  root@10.128.0.78:/root/models/trained_model/

# Expected: ~15GB transferred in 2-5 minutes (internal network is fast)
```

### Verify Copy:
```bash
ssh -i ~/.ssh/gcp/ngcp_root_key root@34.45.239.100 "
ls -lh /root/models/trained_model/ | head -15
"

# Should see:
# - model-00001-of-00004.safetensors (~5GB)
# - model-00002-of-00004.safetensors (~5GB)
# - model-00003-of-00004.safetensors (~4GB)
# - model-00004-of-00004.safetensors (~1GB)
# - config.json
# - tokenizer files
```

---

## Step 4: Run Base Model Evaluation (10-15 minutes)

### On Training Server:
```bash
ssh -i ~/.ssh/gcp/ngcp_root_key root@35.202.149.44
cd /root/hydra

# Run base eval (auto-switches vLLM to base model)
./run_evals.sh base 4096

# Expected output:
# ========================================
# Running Evaluation: base
# ========================================
# Configuration:
#   MODE: base
#   max_token_length: 4096
#   vLLM Host: 34.45.239.100
#   vLLM URL: http://10.128.0.78:9004/v1
#   SSH Key: /root/.ssh/gcp/ngcp_root_key
#   Output dir: evals/base_20260128_HHMMSS
# ========================================
#
# ⚠ Ensure BASE_URL points to the same vLLM server!
#
# [1/3] Switching vLLM to base model on 34.45.239.100...
# ✓ vLLM is fully responding on port 9004 (after 35s)
# ✓ vLLM switched to base model
#
# [2/3] Waiting for vLLM to stabilize...
# Capturing vLLM model info...
# vLLM is now serving:
#   /root/models/Qwen2.5-7B-Instruct
# ✓ Model matches expected mode
#
# Using tokenizer: Qwen/Qwen2.5-7B-Instruct
#
# [3/3] Starting evaluation...
# Started eval with PID: XXXXX
```

### Monitor Evaluation:
```bash
tail -f /tmp/eval_base_*.log

# Watch for:
# - Loaded 11 tasks
# - Each task running through 5 steps
# - Final metrics reported
```

### Check Results:
```bash
# Wait for completion (~10-15 minutes)
# Check if eval finished
ps aux | grep "secure_code_review_env.py evaluate" | grep -v grep

# View results
cat evals/base_*/metrics.json | jq

# View samples
cat evals/base_*/samples.jsonl | jq -r '.failure_reason' | sort | uniq -c

# Expected (from earlier baseline):
#       5 patch_apply_hunk_failed
#       4 patch_ineffective
#       1 regression_test_failure
#       1 patch_apply_malformed
```

---

## Step 5: Run Trained Model Evaluation (10-15 minutes)

### On Training Server:
```bash
cd /root/hydra

# Run trained eval (auto-switches vLLM to trained model)
./run_evals.sh trained 4096

# Expected output:
# [1/3] Switching vLLM to trained model on 34.45.239.100...
# ✓ vLLM is fully responding on port 9004 (after 40s)
# ✓ vLLM switched to trained model
#
# vLLM is now serving:
#   /root/models/trained_model
# ✓ Model matches expected mode
#
# Using tokenizer: /root/hydra/trained_model_checkpoints/final_model
```

### Monitor and Check Results:
```bash
tail -f /tmp/eval_trained_*.log

# After completion:
cat evals/trained_*/metrics.json | jq
cat evals/trained_*/samples.jsonl | jq -r '.failure_reason' | sort | uniq -c
```

---

## Step 6: Compare Base vs Trained Results

### Quick Comparison:
```bash
echo "=== BASE MODEL ==="
cat evals/base_*/metrics.json | jq '.results.all'
cat evals/base_*/samples.jsonl | jq -r '.failure_reason' | sort | uniq -c

echo ""
echo "=== TRAINED MODEL ==="
cat evals/trained_*/metrics.json | jq '.results.all'
cat evals/trained_*/samples.jsonl | jq -r '.failure_reason' | sort | uniq -c
```

### Detailed Task-by-Task Comparison:
```bash
# Create comparison table
echo "Task,Base_Reason,Trained_Reason" > /tmp/comparison.csv

for task in cmd-001 idor-001 path-001 sqli-{001..006} xss-001 xss-002; do
    base_reason=$(cat evals/base_*/samples.jsonl | jq -r "select(.task_id==\"$task\") | .failure_reason")
    trained_reason=$(cat evals/trained_*/samples.jsonl | jq -r "select(.task_id==\"$task\") | .failure_reason")
    echo "$task,$base_reason,$trained_reason" >> /tmp/comparison.csv
done

cat /tmp/comparison.csv | column -t -s,
```

### Key Metrics to Check:

**Pass Rate:**
```bash
# Base
cat evals/base_*/metrics.json | jq '.results.all."eval/pass_rate"'

# Trained
cat evals/trained_*/metrics.json | jq '.results.all."eval/pass_rate"'

# Expected: Trained >= Base (improvement or at least no regression)
```

**Failure Reason Distribution:**
- Compare counts of each failure type
- Check if trained model has:
  - Fewer `patch_ineffective` (good - better at fixing vulns)
  - Fewer `patch_apply_*` errors (good - better patch formatting)
  - More tasks reaching `regression_test_failure` (good - fixing vulns but maybe breaking tests)

---

## Success Criteria

### ✅ Training Phase:
- [ ] vLLM base model started successfully
- [ ] GRPO completed 100 steps without OOM
- [ ] Final checkpoint saved
- [ ] Model copied to vLLM server

### ✅ Evaluation Phase:
- [ ] Base eval completed on all 11 tasks
- [ ] Trained eval completed on all 11 tasks
- [ ] Both evals auto-switched vLLM models correctly
- [ ] vLLM model provenance captured in metrics

### ✅ Results:
- [ ] Trained model pass rate >= base model pass rate
- [ ] Failure reason distribution documented
- [ ] No unexpected errors or crashes

---

## Troubleshooting

### Issue: OOM During Training
**Symptom:** GRPO crashes before step 100
**Check:**
```bash
grep -i "oom\|memory" /tmp/grpo_*.log
```
**Solution:** Verify seq_len=512 in grpo.py and truncation is in place

### Issue: vLLM Model Switch Failed
**Symptom:** run_evals.sh can't switch vLLM
**Check:**
```bash
# Verify SSH works
ssh -i ~/.ssh/gcp/ngcp_root_key root@34.45.239.100 "echo test"

# Check if run_vllm.sh exists
ssh -i ~/.ssh/gcp/ngcp_root_key root@34.45.239.100 "ls -lh /root/hydra/run_vllm.sh"
```

### Issue: Eval Shows Wrong Model
**Symptom:** "Expected base but vLLM is serving trained_model"
**Check:**
```bash
curl -s http://10.128.0.78:9004/v1/models | jq -r '.data[0].id'
```
**Solution:** Manually switch:
```bash
ssh -i ~/.ssh/gcp/ngcp_root_key root@34.45.239.100
cd /root/hydra
./run_vllm.sh base  # or trained
```

### Issue: Trained Tokenizer Not Found
**Symptom:** "Trained model tokenizer not found"
**Check:**
```bash
ls -lh /root/hydra/trained_model_checkpoints/final_model/
```
**Solution:** Verify training completed and saved checkpoint

---

## Clean Up After Test

```bash
# Optional: Remove old logs to free space
ssh -i ~/.ssh/gcp/ngcp_root_key root@35.202.149.44 "
find /tmp -name 'grpo_*.log' -mtime +7 -delete
find /tmp -name 'eval_*.log' -mtime +7 -delete
find /tmp -name 'scr_serve_*.log' -mtime +7 -delete
"

# Keep evaluation results (they're small)
# Keep trained model checkpoints
```

---

**Last Updated:** 2026-01-29 (Updated with enhanced monitoring and logging)
**Status:** Ready for smoke test

**Changes from previous version:**
- Fixed training command: 1000 → 100 steps
- Added monitor_train.sh and monitor_train_tmux.sh as primary monitoring method
- Updated checkpoint interval: every 3 steps (not 25/50/75/100)
- Added example of enhanced GRPO logging output
- Improved OOM troubleshooting with memory tracking references
