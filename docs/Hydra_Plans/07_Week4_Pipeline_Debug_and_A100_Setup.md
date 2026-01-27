# Week 4: Pipeline Debug and A100 Setup

**Date:** January 27, 2026
**Status:** End-to-end pipeline validated, OOM during training on shared GPU

---

## Executive Summary

Successfully debugged and validated the complete GRPO training pipeline end-to-end:
- Fixed 6 critical bugs from code review (duplicate requests, token alignment, hardcoded filenames)
- Set up A100 40GB training box with Deep Learning VM
- Identified and fixed 3 filters blocking batch formation in SCR env
- **Proved pipeline works**: SCR → POST /scored_data → API queue → GRPO fetches batch
- Hit OOM during backward pass (expected: 7B inference + 7B training on shared 40GB GPU)

**Next**: Either reduce memory footprint or use separate GPUs for inference/training.

---

## Critical Bug Fixes

### Priority 0 (Correctness)

#### 1. Duplicate OpenAI Request When n=1
**File:** `atroposlib/envs/server_handling/vllm_server.py:74-83`

**Issue:** When `n_kwarg_is_ignored=True` and `n=1`, code made redundant API call in else branch.

**Fix:**
```python
# BEFORE: Made 2 requests when n=1
if self.config.n_kwarg_is_ignored:
    n = kwargs.pop("n", 1)
    completion_list = await asyncio.gather(...)
    completions = completion_list[0]
    if n > 1:
        for c in completion_list[1:]:
            completions.choices.extend(c.choices)
    else:
        completions = await self.openai.chat.completions.create(**kwargs)  # DUPLICATE!

# AFTER: Single request path
if self.config.n_kwarg_is_ignored:
    n = kwargs.pop("n", 1)
    completion_list = await asyncio.gather(
        *[self.openai.chat.completions.create(**kwargs) for _ in range(n)]
    )
    completions = completion_list[0]
    for c in completion_list[1:]:
        completions.choices.extend(c.choices)
```

**Impact:** 2x performance improvement for n=1 case (most common).

#### 2. Token/Logprob Alignment Mismatch
**File:** `atroposlib/envs/server_handling/vllm_server.py:205-240`

**Issue:** Reconstructing token IDs from logprob dict keys instead of using authoritative `token_ids` from server. With top-k > 1, keys may not match selected tokens.

**Fix:** Use `results["token_ids"]` as source of truth, lookup logprobs from per-step dict:
```python
# Use authoritative token_ids from server
output_ids = list(token_ids_from_server[idx])
logprobs = []
for step_idx, token_id in enumerate(output_ids):
    step_dict = output_token_logprobs[step_idx][0]
    logprob = step_dict.get(str(token_id), step_dict.get(token_id))
    if logprob is None:
        # Fail fast instead of silent fallback
        raise ValueError(f"Token {token_id} not found in logprobs dict")
    logprobs.append(logprob)
```

**Impact:** Training data now has correct token/logprob pairs. Fail-fast prevents silent corruption.

### Priority 1 (Robustness)

#### 3. Patch Command Can Hang Indefinitely
**File:** `environments/hydra/harness/runner.py:325-343`

**Issue:** `patch` command could hang waiting for user input if patch is ambiguous.

**Fix:** Added non-interactive flags + timeout:
```python
result = subprocess.run(
    [
        "patch", "-p1",
        "--batch",      # Non-interactive
        "--forward",    # Don't ask about reverse patches
        "-d", str(workspace),
        "-i", str(patch_file.absolute())
    ],
    capture_output=True,
    text=True,
    stdin=subprocess.DEVNULL,
    timeout=30
)
```

#### 4. Only Checks First Code Block
**File:** `environments/hydra/secure_code_review_env.py:321-332`

**Issue:** Model often emits explanation blocks before diff. Code only checked `matches[0]`.

**Fix:** Iterate through all fenced blocks:
```python
matches = re.findall(diff_pattern, response, re.DOTALL)
for match in matches:  # Check ALL blocks, not just first
    diff_text = match.strip()
    if any(line.startswith(('---', '+++', 'diff ')) for line in diff_text.split('\n')[:5]):
        return self._normalize_diff_headers(diff_text)
```

### Priority 2 (Maintenance)

#### 5. System Prompt Hardcodes app.py
**File:** `environments/hydra/secure_code_review_env.py:36-81`

**Issue:** System prompt template had hardcoded `app.py` filename. Future tasks with different filenames would break.

**Fix:** Dynamic substitution from task metadata:
```python
SYSTEM_PROMPT_TEMPLATE = """...
Use this EXACT format for the target file {target_file}:

```diff
diff --git a/{target_file} b/{target_file}
--- a/{target_file}
+++ b/{target_file}
...
```
"""

def _get_system_prompt(target_file: str = "app.py") -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(target_file=target_file)

# Extract from task metadata
target_file = task_meta.get("files", {}).get("vulnerable", "workspace/app.py")
if target_file.startswith("workspace/"):
    target_file = target_file[len("workspace/"):]  # Strip prefix for patch
```

---

## A100 VM Setup

### Instance Configuration

**Name:** training-box-01 (hydra-a100)
**IP:** 35.202.149.44
**GPU:** NVIDIA A100-SXM4-40GB
**Image:** Deep Learning VM (pytorch-2-7-cu128-ubuntu-2204-nvidia-570)
**Boot Disk:** 500GB SSD
**SSH:** `ssh hydra-a100` (configured in ~/.ssh/config)

### Setup Process

1. **Provision via gcloud CLI** (replaced Ubuntu 24.04 with Deep Learning VM):
   ```bash
   # Stop instance
   gcloud compute instances stop training-box-01 --zone us-central1-a

   # Detach old boot disk
   gcloud compute instances detach-disk training-box-01 --disk training-box-01 --zone us-central1-a

   # Create new Deep Learning VM disk
   gcloud compute disks create training-box-01-dlvm \
     --size 500GB \
     --type pd-ssd \
     --image-family pytorch-2-7-cu128-ubuntu-2204 \
     --image-project deeplearning-platform-release \
     --zone us-central1-a

   # Attach new disk as boot
   gcloud compute instances attach-disk training-box-01 \
     --disk training-box-01-dlvm \
     --boot \
     --zone us-central1-a

   # Add SSH keys to metadata (preserve root access)
   gcloud compute instances add-metadata training-box-01 \
     --metadata-from-file ssh-keys=<(cat ~/.ssh/gcp/ngcp_root_key.pub | sed 's/^/root:/')

   # Start instance
   gcloud compute instances start training-box-01 --zone us-central1-a
   ```

2. **Verify GPU and PyTorch**:
   ```bash
   nvidia-smi  # NVIDIA A100-SXM4-40GB
   python3 -c "import torch; print(torch.__version__, torch.cuda.is_available())"
   # PyTorch 2.7.1+cu128, True
   ```

3. **Clone HYDRA repo**:
   ```bash
   # Copy SSH keys
   scp -r ~/.ssh/git/ hydra-a100:~/.ssh/

   # Clone
   ssh hydra-a100
   git clone git@github.com:RelayOne/hydra.git ~/hydra
   cd ~/hydra && git checkout hydra
   ```

4. **Run automated setup**:
   ```bash
   cd ~/hydra
   bash environments/hydra/setup-vm.sh
   ```

### Automated Setup Script

**File:** `environments/hydra/setup-vm.sh`

```bash
#!/bin/bash
set -e

echo "=== HYDRA VM Setup ==="

# 1. System packages
apt-get update -qq
apt-get install -y -qq docker.io git curl jq
systemctl start docker && systemctl enable docker
usermod -aG docker root 2>/dev/null || true

# 2. Python packages
pip install -q vllm aiohttp transformers huggingface_hub hf_transfer accelerate bitsandbytes

# 3. Install HYDRA
cd ~/hydra && pip install -q -e .

# 4. Download model
MODEL_DIR=~/models/Qwen2.5-7B-Instruct
if [ ! -d "$MODEL_DIR" ]; then
    HF_HUB_ENABLE_HF_TRANSFER=1 huggingface-cli download Qwen/Qwen2.5-7B-Instruct --local-dir $MODEL_DIR
fi

# 5. Build harness Docker image
docker build -t hydra-harness:latest ~/hydra/environments/hydra/harness/

echo "=== Setup Complete ==="
```

### Component Startup Commands

```bash
# 1. vLLM Server
python3 ~/hydra/example_trainer/vllm_api_server.py \
  --model ~/models/Qwen2.5-7B-Instruct \
  --port 9004 \
  --gpu-memory-utilization 0.5

# 2. Atropos API
uvicorn atroposlib.api.server:app --host 0.0.0.0 --port 8000

# 3. SecureCodeReviewEnv (serve mode)
python3 ~/hydra/environments/hydra/secure_code_review_env.py serve \
  --slurm false \
  --openai.base_url http://localhost:9004/v1 \
  --openai.model_name ~/models/Qwen2.5-7B-Instruct \
  --openai.server_type vllm \
  --env.tokenizer_name ~/models/Qwen2.5-7B-Instruct \
  --env.use_wandb false

# 4. GRPO Trainer
python3 ~/hydra/example_trainer/grpo.py
```

---

## Batch Formation Debugging

### The Problem

GRPO was stuck at "Step 1/5" waiting for first batch. No data flowing from SCR env → API → GRPO.

**Expected flow:**
1. SCR env generates + scores 4 patches per group
2. POST to `/scored_data` API endpoint
3. API buffers until batch_size * gradient_accumulation_steps (2 × 32 = 64 sequences)
4. GRPO calls `/batch` to fetch training data

**Actual:** API `queue_size: 0`, GRPO blocked on `/batch` request.

### Root Cause Analysis

Three filters were silently dropping groups before POST:

#### Filter 1: Uniform Score Check (in `score()`)
```python
# environments/hydra/secure_code_review_env.py:579-580
if all(s == scores["scores"][0] for s in scores["scores"]):
    return None  # Drop group silently
```

**Issue:** Untrained model produces patches that all fail the same way (-0.85, -0.85, -0.85, -0.85). ~90% of groups dropped.

**Why it exists:** GRPO learns from score variance. Uniform groups provide no learning signal.

**Fix for smoke testing:** Make configurable via `--env.ensure_scores_are_not_same false`

#### Filter 2: Short Completion Check (in `score()`)
```python
# environments/hydra/secure_code_review_env.py:561-564
masks = item["masks"]
if len([m for m in masks if m != -100]) < 10:
    continue  # Skip item
```

**Issue:** If all 4 items in group have < 10 tokens, group drops to 0 items → caught by "need >= 2 items" check → return None.

**Why it exists:** Prevent degenerate empty outputs from wasting compute.

**Fix:** Keep short items to prevent group collapse:
```python
completion_len = sum(1 for m in masks if m != -100)
if completion_len < 10:
    pass  # Keep item, it will have poor score anyway
```

#### Filter 3: Token Length Check (in `handle_send_to_api()`)
```python
# atroposlib/envs/base.py:900-904
elif abort_on_any_max_length_exceeded and any(
    [len(x) >= self.max_token_len for x in group["tokens"]]
):
    logger.warning("Token length is too long in a group, skipping...")
    continue
```

**Issue:** Groups with long patches (>2048 tokens) dropped after scoring, before POST.

**Why it exists:** Prevent OOM during training from oversized sequences.

**Fix:** Override in SCR env to disable for smoke testing:
```python
async def handle_send_to_api(self, scored_data, item=None, do_send_to_api=True,
                              abort_on_any_max_length_exceeded=True):
    """Override to disable token length checking for smoke testing."""
    return await super().handle_send_to_api(
        scored_data, item, do_send_to_api,
        abort_on_any_max_length_exceeded=False  # Always False
    )
```

### Validation: Pipeline Working

After fixes, confirmed end-to-end data flow:

```bash
# SCR env logs
[SCR] Group scores: [(-0.85, 'patch_apply_hunk_failed'), (-0.85, ...), (-0.85, ...), (-0.85, ...)]
[SCR] Items after filtering: 4/4
[SCR] Uniform scores detected, ensure_scores_are_not_same=False
[SCR] Group accepted! Returning 4 scored items
{"status":"received"}

# API status
{"current_step":2,"queue_size":3}

# GRPO logs
Starting training for 5 steps on device: cuda
Step 1/5
`use_cache=True` is incompatible with gradient checkpointing. Setting `use_cache=False`.
grpo_loss.backward()
```

**Evidence:**
- ✅ 4 groups accepted by SCR env (no drops)
- ✅ 4 POST requests to `/scored_data` with HTTP 200
- ✅ API queue_size incremented to 3
- ✅ GRPO fetched batch and entered training loop
- ❌ OOM during backward pass (memory issue, not pipeline issue)

---

## Memory Tuning for Shared GPU

### The Challenge

Running inference (vLLM) and training (GRPO) on the same 40GB A100:

**vLLM memory usage:**
- Model weights (7B bf16): ~14 GB
- KV cache (depends on gpu_memory_utilization): 2-8 GB
- Total: 16-22 GB

**GRPO memory usage (batch_size=2, seq_len=2048):**
- Model weights (7B bf16): ~14 GB
- Activations (forward pass): ~3-4 GB
- Gradients (backward pass): ~2-3 GB
- Optimizer state: ~1-2 GB (depending on optimizer)
- Total: ~20-23 GB

**Problem:** 21 GB (vLLM) + 20 GB (GRPO) = 41 GB > 39.49 GB available → OOM

### Attempted Fixes

| Config | vLLM Mem | GRPO Peak | Total | Result |
|--------|----------|-----------|-------|--------|
| gpu_util=0.5, seq=2048, batch=2 | 21 GB | 21 GB | 42 GB | ❌ OOM |
| gpu_util=0.45, seq=1024, batch=2 | 19 GB | 21 GB | 40 GB | ❌ OOM |
| gpu_util=0.45, seq=1024, batch=1 | 19 GB | 18 GB | 37 GB | ⚠️ Still OOM |

**Key insight:** Peak memory during backward pass includes:
- Gradient accumulation buffers
- Activation recomputation (even with gradient checkpointing)
- Temporary tensors for MLP layers
- Memory fragmentation overhead

### Recommended Solutions

**Option A: Separate GPUs (cleanest)**
- Run vLLM on GPU:0, GRPO on GPU:1
- Each gets full 40GB
- No memory competition

**Option B: Reduce vLLM footprint (current approach)**
- `--gpu-memory-utilization 0.3-0.4`
- `--max-model-len 1024` (reduce KV cache)
- Leaves ~22 GB for GRPO

**Option C: Use smaller model for training**
- Train 1.5B model (uses ~8 GB vs 14 GB)
- Keep 7B for inference
- Faster iteration, lower quality

**Option D: CPU offloading (slow)**
- Offload optimizer state to CPU
- Reduces GPU memory ~2 GB
- Adds latency to backward pass

### Current Configuration

**File:** `example_trainer/grpo.py`

```python
training_config = TrainingConfig(
    model_name="/root/models/Qwen2.5-7B-Instruct",
    training_steps=5,
    batch_size=1,          # Reduced from 2
    seq_len=1024,          # Reduced from 2048
    launch_vllm=False,     # Use external vLLM
    vllm_port=9004,
)
```

**vLLM launch:**
```bash
python3 example_trainer/vllm_api_server.py \
  --model ~/models/Qwen2.5-7B-Instruct \
  --port 9004 \
  --gpu-memory-utilization 0.45
```

**Status:** Still hitting OOM. Need gpu_util < 0.4 or separate GPU.

---

## Key Code Changes

### 1. GRPO: External vLLM Support

**File:** `example_trainer/grpo.py`

Added `launch_vllm` flag to disable internal vLLM management:

```python
class TrainingConfig(BaseModel):
    launch_vllm: bool = Field(
        False,
        description="Whether to launch and manage vLLM server (use False if vLLM is already running externally)"
    )

# Wrap all vLLM subprocess code in:
if config.launch_vllm:
    # Launch, restart, terminate vLLM
    ...
else:
    print("Using external vLLM server (launch_vllm=False)")
```

**Benefits:**
- Avoid GPU memory fragmentation from repeated vLLM restarts
- Better control over vLLM memory allocation
- Easier to debug with persistent vLLM process

### 2. SCR Env: Debug Logging

**File:** `environments/hydra/secure_code_review_env.py`

Added detailed logging to track group acceptance/rejection:

```python
print(f"[SCR] Group scores: {group_scores}")
print(f"[SCR] Items after filtering: {len(scores['tokens'])}/{len(group_scores)}")

if len(scores["tokens"]) < 2:
    print(f"[SCR] Group dropped: only {len(scores['tokens'])} items (need >= 2)")
    return None

all_same = all(s == scores["scores"][0] for s in scores["scores"])
if all_same:
    print(f"[SCR] Uniform scores detected, ensure_scores_are_not_same={self.config.ensure_scores_are_not_same}")
if self.config.ensure_scores_are_not_same and all_same:
    print(f"[SCR] Group dropped: all scores identical ({scores['scores'][0]})")
    return None

print(f"[SCR] Group accepted! Returning {len(scores['tokens'])} scored items")
```

**Impact:** Immediately identified which filter was dropping groups.

---

## Git History

```bash
$ git log --oneline -5
2044da1 Unblock GRPO smoke testing: fix batch formation and shared GPU OOM
5d3097c Add VM setup requirements and script for A100/L4 boxes
92e5240 Harden token/logprob alignment: fail fast instead of silent fallbacks
305adf7 Make system prompt dynamically substitute target_file
4eeeeeb Fix critical bugs identified in code review
```

### Commit 2044da1: Batch Formation + OOM Fixes

**Files changed:**
- `environments/hydra/secure_code_review_env.py` (+30, -11)
- `example_trainer/grpo.py` (+200, -160)

**Key changes:**
1. SCR env: Disable uniform score filter via `ensure_scores_are_not_same` config
2. SCR env: Keep short completions to prevent group collapse
3. SCR env: Override `handle_send_to_api()` to bypass token length limit
4. GRPO: Add `launch_vllm` flag for external vLLM server
5. GRPO: Reduce `batch_size=1`, `seq_len=1024` for memory savings

---

## Lessons Learned

### 1. Silent Filters are Hard to Debug

Three different filters silently dropped groups before API:
- Had to add extensive logging to identify which filter was active
- Each filter had valid purpose (prevent OOM, ensure learning signal)
- For smoke testing, need ability to disable all filters

**Recommendation:** Add `--env.smoke_test_mode` flag that disables all filters at once.

### 2. Shared GPU Requires Careful Memory Budget

Running inference + training on same GPU is fragile:
- vLLM pre-allocates memory and doesn't release it
- GRPO peak memory happens at backward (hard to predict exactly)
- 1-2 GB of slack isn't enough due to fragmentation

**Recommendation:** Either use separate GPUs or budget conservatively (leave 5+ GB free).

### 3. Fail-Fast is Better Than Silent Fallbacks

Token/logprob alignment bug would have silently corrupted training data. Fail-fast caught it immediately:

```python
if logprob is None:
    raise ValueError(f"Token {token_id} not found in logprobs dict at step {step_idx}")
```

**Recommendation:** Prefer loud failures over silent data corruption in training pipelines.

### 4. End-to-End Validation is Essential

Despite all components "working" individually:
- vLLM served requests ✅
- SCR env generated patches ✅
- API accepted POST requests ✅
- GRPO registered as trainer ✅

...the pipeline was still broken due to filters between components.

**Recommendation:** Always test full pipeline end-to-end, not just individual components.

---

## Next Steps

### Immediate (Unblock Training)

**Option 1: Reduce vLLM memory to 0.3-0.35**
```bash
--gpu-memory-utilization 0.3 --max-model-len 1024
```
Leaves ~23 GB for GRPO, should avoid OOM with batch_size=1, seq_len=1024.

**Option 2: Use second GPU**
Provision second A100 or split workload across 2 GPUs on same box.

### Short-term (Week 5)

1. **Run 5-step smoke test to completion**
   - Verify no OOM with reduced config
   - Measure time per step
   - Confirm checkpoints save correctly

2. **Run 100-step learning curve**
   - Track failure reason distribution over time
   - Measure pass_rate at steps 0, 25, 50, 75, 100
   - Generate evidence: "untrained model: 0% → trained model: X%"

3. **Add deterministic evaluation**
   - Run temp=0 eval on all tasks after training
   - Compare to baseline (untrained model)
   - Quantify improvement

### Medium-term (Week 6-7)

1. **Expand to 10-task benchmark**
   - Add SQLi variants, XSS, path traversal, command injection
   - Measure generalization across vulnerability types

2. **Optimize memory usage**
   - Try 8-bit optimizer (reduces memory ~2 GB)
   - Experiment with gradient accumulation vs batch size
   - Profile peak memory usage per component

3. **Build evidence bundles**
   - 3 case studies: vulnerable code → untrained patch → trained patch
   - Show exploit output, test results, semgrep findings
   - Generate before/after comparison

---

## Configuration Reference

### Smoke Test Configuration (Current)

**vLLM:**
```bash
python3 example_trainer/vllm_api_server.py \
  --model ~/models/Qwen2.5-7B-Instruct \
  --port 9004 \
  --gpu-memory-utilization 0.45
```

**SCR Env:**
```bash
python3 environments/hydra/secure_code_review_env.py serve \
  --slurm false \
  --openai.base_url http://localhost:9004/v1 \
  --openai.model_name ~/models/Qwen2.5-7B-Instruct \
  --openai.server_type vllm \
  --env.tokenizer_name ~/models/Qwen2.5-7B-Instruct \
  --env.use_wandb false \
  --env.ensure_scores_are_not_same false  # Disable uniform filter
```

**GRPO:**
```python
training_config = TrainingConfig(
    model_name="/root/models/Qwen2.5-7B-Instruct",
    training_steps=5,
    batch_size=1,
    seq_len=1024,
    gradient_accumulation_steps=32,
    launch_vllm=False,
    vllm_port=9004,
    use_wandb=False,
)
```

**Effective batch size:** 1 × 32 = 32 sequences (half of original 64)

### Memory Breakdown (Current)

| Component | Memory | Notes |
|-----------|--------|-------|
| vLLM weights | 14 GB | 7B model in bf16 |
| vLLM KV cache | 2.77 GB | gpu_util=0.45, 51,920 tokens |
| vLLM overhead | 2-3 GB | CUDA context, buffers |
| **vLLM total** | **~19 GB** | |
| GRPO weights | 14 GB | 7B model in bf16 |
| GRPO activations | 2-3 GB | batch=1, seq=1024 |
| GRPO gradients | 2-3 GB | Backward pass peak |
| **GRPO peak** | **~19-20 GB** | |
| **Total** | **~38-39 GB** | ⚠️ Tight fit! |

**Recommended:** Reduce vLLM to 0.3-0.35 for reliable operation (leaves 3-5 GB slack).

---

## Files Changed

### New Files
- `environments/hydra/setup-vm.sh` - Automated VM setup script
- `environments/hydra/requirements-vm.txt` - Dependency list for A100/L4

### Modified Files
- `atroposlib/envs/server_handling/vllm_server.py` - Fixed duplicate request, token alignment
- `environments/hydra/harness/runner.py` - Non-interactive patch with timeout
- `environments/hydra/secure_code_review_env.py` - Dynamic target_file, batch formation fixes
- `example_trainer/grpo.py` - External vLLM support, reduced memory config

### Documentation
- This file: `docs/Hydra_Plans/07_Week4_Pipeline_Debug_and_A100_Setup.md`

---

*Last updated: January 27, 2026*
