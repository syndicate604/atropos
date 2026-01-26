# Week 1-2 Implementation Notes

**Date:** January 2026
**Status:** Core pipeline validated, ready for model scaling

---

## What Was Built

### Week 1: Verification Harness

Location: `environments/hydra/`

```
environments/hydra/
├── check_prereqs.sh          # Verify docker, python3, patch
├── run_primary.sh            # CLI entry point for harness
├── harness/
│   ├── Dockerfile            # Hardened container (semgrep, pytest)
│   ├── requirements.txt      # Container dependencies
│   ├── runner.py             # Core harness logic
│   └── semgrep-rules/
│       └── security.yaml     # SQL injection detection rules
├── tasks/
│   └── sqli-001/             # First benchmark task
│       ├── task.json
│       ├── workspace/app.py  # Vulnerable Flask app
│       ├── workspace/tests/  # Regression tests
│       ├── exploit/          # SQL injection exploit
│       └── patches/          # known-good, known-bad, breaks-tests
├── secure_code_review_env.py # Atropos environment
└── results/                  # Output JSON files
```

### Week 2: Atropos Integration

- `SecureCodeReviewEnv` extends `BaseEnv`
- Generates patch candidates via model inference
- Scores patches using Docker harness
- Returns `ScoredDataGroup` for GRPO training

---

## How to Use

### 1. Test Harness Locally (No Model)

```bash
cd environments/hydra

# Check prerequisites
./check_prereqs.sh

# Build Docker image (first time only)
docker build -t hydra-harness:latest harness/

# Run Win A/B/C validation
./run_primary.sh sqli-001 known-good      # Should PASS
./run_primary.sh sqli-001 known-bad       # Should FAIL (patch_ineffective)
./run_primary.sh sqli-001 breaks-tests    # Should FAIL (regression_test_failure)

# Test with external patch file (for model-generated patches)
python3 harness/runner.py sqli-001 --patch-file /path/to/model.diff --tasks-dir tasks
```

### 2. Run SecureCodeReviewEnv (Process Mode)

```bash
# From repo root, with vLLM running on :9004
python3 environments/hydra/secure_code_review_env.py process \
  --openai.base_url http://localhost:9004/v1 \
  --openai.model_name Qwen/Qwen2.5-1.5B-Instruct \
  --openai.server_type vllm \
  --env.tokenizer_name Qwen/Qwen2.5-1.5B-Instruct \
  --env.group_size 4 \
  --env.total_steps 10 \
  --env.max_token_length 1024 \
  --env.use_wandb false \
  --env.data_path_to_save_groups /tmp/scr_rollouts.jsonl
```

### 3. Run Online Training (Serve Mode)

```bash
# Terminal 1: Atropos API
uvicorn atroposlib.api.server:app --host 0.0.0.0 --port 8000

# Terminal 2: SecureCodeReviewEnv
python3 environments/hydra/secure_code_review_env.py serve \
  --slurm false \
  --openai.base_url http://localhost:9004/v1 \
  --openai.model_name Qwen/Qwen2.5-1.5B-Instruct \
  --openai.server_type vllm \
  --env.tokenizer_name Qwen/Qwen2.5-1.5B-Instruct \
  --env.group_size 4 \
  --env.use_wandb false

# Terminal 3: GRPO Trainer
python3 example_trainer/grpo.py
```

---

## VM Setup (GCP)

### Instance Details
- **Name:** training-controller-1 (hydra-controller)
- **IP:** 35.222.9.121
- **GPU:** NVIDIA L4 (24GB VRAM)
- **Image:** Deep Learning VM (pytorch-2-7-cu128-ubuntu-2204)
- **SSH:** `ssh hydra-controller` (configured in ~/.ssh/config)

### vLLM Server Command
```bash
cd ~/hydra && python3 example_trainer/vllm_api_server.py \
  --model Qwen/Qwen2.5-1.5B-Instruct \
  --port 9004 \
  --gpu-memory-utilization 0.25
```

Memory settings:
- `0.25` (6GB) - leaves room for training
- `0.4` (9GB) - inference only
- `0.8` (18GB) - maximum inference performance

### Key Fixes Applied

| Issue | Fix |
|-------|-----|
| Server type defaulting to OpenAI | Always pass `--openai.server_type vllm` |
| Base URL missing `/v1` | Must be `http://localhost:9004/v1` |
| Tokenizer mismatch | `--env.tokenizer_name` must match model |
| Adam OOM on L4 | Use SGD or reduce vLLM memory |
| wandb None fields | Fixed to use string "none" instead |

---

## Harness API

### CLI Options

```bash
python3 harness/runner.py <task_id> [patch_name] [--patch-file PATH] [--tasks-dir DIR] [--output FILE]
```

- `patch_name`: Named patch from `tasks/<id>/patches/*.diff`
- `--patch-file`: External diff file (for model outputs)
- Cannot provide both `patch_name` and `--patch-file`

### Failure Reasons

| Reason | Meaning |
|--------|---------|
| `patch_apply_failure` | Diff couldn't be applied (wrong paths, syntax) |
| `invalid_patch_format` | Not a valid unified diff (missing headers) |
| `patch_ineffective` | Exploit still works after patch |
| `regression_test_failure` | Patch breaks existing functionality |
| `scanner_findings` | Semgrep still detects vulnerability |
| `original_not_vulnerable` | Exploit doesn't work on original (bad task) |

### TaskResult JSON Schema

```json
{
  "task_id": "sqli-001",
  "patch_name": "known-good",
  "passed": true,
  "exploit_original_succeeded": true,
  "exploit_patched_succeeded": false,
  "tests_passed": true,
  "scanner_clean": true,
  "failure_reason": null,
  "patch_error": ""
}
```

---

## Known Issues & Workarounds

### 1. Small Models Struggle with Diff Format

**Symptom:** All patches fail with `patch_apply_failure`

**Cause:** 1.5B models output:
- `--- workspace/app.py` instead of `--- a/workspace/app.py`
- Malformed hunks
- Missing context lines

**Workarounds:**
- Use 7B+ model
- Add few-shot example in system prompt
- Post-process diffs to fix paths

### 2. All-Same Scores Skip Groups

**Symptom:** JSONL file empty or very few entries

**Cause:** When all patches in a group fail identically, GRPO can't learn (no contrast)

**Expected:** Early training will have many skipped groups. As model improves, more variance appears.

### 3. Docker Permission Denied

**Symptom:** `patch_apply_failure` with permission errors

**Fix:** Ensure user is in docker group: `usermod -aG docker $USER`

### 4. vLLM "Hangs" on Wrong Server Type

**Symptom:** Process hangs waiting for response

**Cause:** Using OpenAI client against vLLM `/generate` endpoint

**Fix:** Always pass `--openai.server_type vllm`

---

## Metrics to Track

### Training Metrics (wandb)
- `train/pass_rate` - Fraction of patches that fully pass
- `train/failure_patch_apply_failure` - Format errors
- `train/failure_patch_ineffective` - Security failures
- `train/failure_regression_test_failure` - Breaking changes

### Evaluation Metrics
- `eval/pass_rate` - Deterministic eval on all tasks
- `eval/pass_count` - Number of tasks solved

### Success Criteria (Investor Demo)
- Baseline pass rate (untrained model)
- Trained pass rate (after N steps)
- 2-3 case studies with evidence bundles

---

## Next Steps

### Immediate (Week 3)
1. **Try 7B model** for better diff generation
2. **Add few-shot examples** to system prompt
3. **Expand to 10 tasks** (different vuln categories)

### Near-term (Week 4-5)
1. **Train with LoRA** on 7B model
2. **Build evaluation dashboard**
3. **Generate baseline numbers**

### Milestone Targets
- [ ] 10-task benchmark suite (SecureCodeReview-10)
- [ ] Baseline pass rate measured
- [ ] Trained model shows improvement
- [ ] Evidence bundle for 3 case studies

---

## Git Workflow

```bash
# Local development
git checkout hydra
# ... make changes ...
git add environments/hydra/
git commit -m "Description"
git push relayone hydra

# VM sync
ssh hydra-controller "cd ~/hydra && git pull origin hydra"
```

**Remotes:**
- `origin` → syndicate604/atropos (personal fork)
- `upstream` → NousResearch/atropos (upstream)
- `relayone` → RelayOne/hydra (team repo)

---

## Files Reference

| File | Purpose |
|------|---------|
| `harness/runner.py` | Core verification logic |
| `harness/Dockerfile` | Hardened sandbox container |
| `secure_code_review_env.py` | Atropos BaseEnv wrapper |
| `tasks/sqli-001/` | First benchmark task |
| `run_primary.sh` | CLI entry point |

---

*Last updated: January 2026*
