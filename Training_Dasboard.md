# Evaluation Automation & Results Tracking System

## Overview

Build a local control plane on `/home/bron/projects/atropos` that orchestrates GRPO evaluations via SSH, automatically ingests results into SQLite, and provides a Flask UI for comparison and analysis.

**Key Requirements:**
- Run everything from LOCAL machine (not training server)
- SSH to training server (35.202.149.44) and vLLM server (34.45.239.100)
- Automated results ingestion into local SQLite database
- Flask UI for viewing/comparing runs
- No manual intervention after initial setup

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  LOCAL MACHINE (/home/bron/projects/atropos)                │
│                                                              │
│  ┌──────────────────┐      ┌──────────────────┐            │
│  │  local_eval.py   │──────│  db_manager.py   │            │
│  │  (Orchestrator)  │      │  (SQLite CRUD)   │            │
│  └────────┬─────────┘      └────────┬─────────┘            │
│           │                         │                       │
│           │ SSH/SCP                 │ INSERT                │
│           │                         ▼                       │
│           │                  ┌──────────────┐               │
│           │                  │hydra_evals.db│               │
│           │                  └──────┬───────┘               │
│           │                         │ SELECT                │
│           │                         │                       │
│           │                  ┌──────▼────────┐              │
│           │                  │  eval_ui.py   │              │
│           │                  │  (Flask App)  │              │
│           │                  └───────────────┘              │
│           │                   http://localhost:5000         │
└───────────┼──────────────────────────────────────────────────┘
            │
            │ SSH: ./run_vllm.sh {base|trained}
            ▼
┌────────────────────────────┐
│  VLLM Server               │
│  34.45.239.100             │
│  Serves model on port 9004 │
└────────────────────────────┘
            │
            │ HTTP inference requests
            ▼
┌─────────────────────────────────────────────────────────────┐
│  TRAINING Server (35.202.149.44)                            │
│                                                              │
│  local_eval.py SSHs here and runs:                          │
│  cd /root/hydra && ./run_evals.sh {base|trained} 4096       │
│                                                              │
│  Results generated at:                                      │
│  /root/hydra/evals/{mode}_{timestamp}/                      │
│  ├── metrics.json                                           │
│  ├── samples.jsonl                                          │
│  └── vllm_models.json                                       │
│                                                              │
│  local_eval.py polls for completion then pulls via SCP      │
└─────────────────────────────────────────────────────────────┘
```

## Model Management Strategy

### Current State (Problems)

**vLLM Server (`/root/models/`):**
```
/root/models/
├── Qwen2.5-7B-Instruct/          # Base model
├── Qwen2.5-7B-Instruct_hf/       # Duplicate (can delete)
└── trained_model/                # Generic name - can only store ONE trained model
```

**Training Server (`/root/hydra/trained_model_checkpoints/`):**
```
/root/hydra/trained_model_checkpoints/
├── step_100_20260129_143022/     # Timestamped checkpoint
├── step_100_20260128_120000/     # Previous training
└── final_model/                  # Symlink to latest
```

**Issue:** Trained models on training server have timestamps, but copied to vLLM as generic `trained_model` → can't track multiple versions or compare different training runs.

### Improved Model Naming Convention

**vLLM Server (`/root/models/`):**
```
/root/models/
├── Qwen2.5-7B-Instruct/                    # Base model (permanent)
├── trained_20260129_143022/                # Trained model from Jan 29 run
├── trained_20260128_120000/                # Previous trained model
└── trained_latest -> trained_20260129_143022  # Symlink to latest (optional)
```

**Benefits:**
- Can store multiple trained models
- Easy to identify which training run produced each model
- Can evaluate different training checkpoints
- Clear provenance in evaluation results

### Model Copy Workflow

**After training completes:**
```bash
# 1. Training server has checkpoint at:
/root/hydra/trained_model_checkpoints/step_100_20260129_143022/

# 2. Copy to vLLM server with matching timestamp:
rsync -avz --progress \
  -e 'ssh -i ~/.ssh/gcp/ngcp_root_key -o StrictHostKeyChecking=no' \
  /root/hydra/trained_model_checkpoints/step_100_20260129_143022/ \
  root@10.128.0.78:/root/models/trained_20260129_143022/

# 3. Optionally update symlink:
ssh root@34.45.239.100 \
  "cd /root/models && ln -sfn trained_20260129_143022 trained_latest"
```

### Modified run_vllm.sh

**Current:** `./run_vllm.sh {base|trained}`

**Enhanced:** `./run_vllm.sh {base|trained_TIMESTAMP|trained_latest}`

Examples:
```bash
./run_vllm.sh base                          # Serve base model
./run_vllm.sh trained_20260129_143022       # Serve specific trained model
./run_vllm.sh trained_latest                # Serve latest trained model (follows symlink)
```

**Implementation:**
```bash
MODE="$1"
if [[ "$MODE" == "base" ]]; then
    MODEL_PATH="/root/models/Qwen2.5-7B-Instruct"
elif [[ "$MODE" == trained_* ]]; then
    MODEL_PATH="/root/models/$MODE"  # e.g., /root/models/trained_20260129_143022
    # Verify model exists
    if [[ ! -d "$MODEL_PATH" ]]; then
        echo "Error: Model not found at $MODEL_PATH"
        exit 1
    fi
else
    echo "Usage: $0 {base|trained_TIMESTAMP}"
    exit 1
fi
```

### Database Schema Updates

Add to `eval_runs` table:
```sql
trained_model_timestamp TEXT,              -- e.g., "20260129_143022" (NULL for base)
training_checkpoint_path TEXT,             -- e.g., "/root/hydra/trained_model_checkpoints/step_100_20260129_143022"
vllm_model_path TEXT,                      -- e.g., "/root/models/trained_20260129_143022"
```

This allows queries like:
- "Show all evals for training run 20260129_143022"
- "Compare base vs all trained models"
- "Show improvement over time across training runs"

### Integration with local_eval.py

**Enhanced arguments:**
```bash
# Evaluate base model
python local_eval.py --mode base

# Evaluate specific trained model
python local_eval.py --mode trained --model-timestamp 20260129_143022

# Evaluate latest trained model
python local_eval.py --mode trained --model-timestamp latest

# Auto-detect: if training just completed, use that timestamp
python local_eval.py --mode trained --auto-detect
```

**Workflow with auto-detect:**
1. Check training server for latest checkpoint
2. Copy to vLLM server with timestamp
3. Run eval with that specific model
4. Database records exact model version used

### Model Cleanup Policy

**Keep on vLLM server:**
- Base model (permanent)
- Latest 3 trained models
- Any trained model with "good" eval results (pass_rate > 70%)

**Cleanup script (optional future enhancement):**
```bash
# Keep only models referenced in database or newer than 30 days
python eval_tracking/cleanup_models.py --keep-recent 3 --keep-days 30
```

## Database Schema

### Table: `eval_runs`
Primary table tracking each evaluation run.

```sql
CREATE TABLE eval_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT UNIQUE NOT NULL,           -- e.g., "base_20260129_143022" or "trained_20260129_143022"
    mode TEXT NOT NULL,                    -- "base" or "trained"
    model_name TEXT,                       -- e.g., "/root/models/Qwen2.5-7B-Instruct"
    trained_model_timestamp TEXT,          -- e.g., "20260129_143022" (NULL for base)
    training_checkpoint_path TEXT,         -- e.g., "/root/hydra/trained_model_checkpoints/step_100_20260129_143022"
    vllm_model_path TEXT,                  -- e.g., "/root/models/trained_20260129_143022"
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    total_time_seconds REAL,
    pass_rate REAL,                        -- 0.0 to 1.0
    pass_count INTEGER,
    total_tasks INTEGER,
    temperature REAL,
    max_tokens INTEGER,
    max_token_length INTEGER,              -- Config value
    vllm_model_served TEXT,                -- From vllm_models.json (for verification)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Table: `eval_samples`
Per-task results for each run.

```sql
CREATE TABLE eval_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_run_id INTEGER NOT NULL,
    task_id TEXT NOT NULL,                 -- e.g., "sqli-001"
    passed BOOLEAN NOT NULL,
    failure_reason TEXT,                   -- Empty string if passed
    response_snippet TEXT,                 -- First 500 chars of model response
    FOREIGN KEY (eval_run_id) REFERENCES eval_runs(id) ON DELETE CASCADE
);
CREATE INDEX idx_samples_run ON eval_samples(eval_run_id);
CREATE INDEX idx_samples_task ON eval_samples(task_id);
```

### Table: `task_metadata` (Optional, for enrichment)
Static metadata about each task.

```sql
CREATE TABLE task_metadata (
    task_id TEXT PRIMARY KEY,
    category TEXT,                         -- "sql_injection", "xss", etc.
    cwe TEXT,                              -- "CWE-89", etc.
    language TEXT,
    framework TEXT,
    difficulty TEXT,
    description TEXT
);
```

### Table: `eval_config` (Optional, for extensibility)
Additional config key-value pairs per run.

```sql
CREATE TABLE eval_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_run_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    FOREIGN KEY (eval_run_id) REFERENCES eval_runs(id) ON DELETE CASCADE
);
CREATE INDEX idx_config_run ON eval_config(eval_run_id);
```

## File Structure

```
/home/bron/projects/atropos/
├── eval_tracking/                    # NEW directory
│   ├── __init__.py
│   ├── config.py                     # Configuration (servers, SSH keys, paths)
│   ├── db_manager.py                 # Database schema and CRUD operations
│   ├── utils.py                      # SSH/SCP helper functions
│   ├── local_eval.py                 # Main orchestrator script
│   ├── ingest_results.py             # Standalone ingestion for manual runs
│   ├── eval_ui.py                    # Flask application
│   ├── requirements.txt              # Python dependencies
│   ├── hydra_evals.db                # SQLite database (gitignored)
│   ├── templates/                    # Flask HTML templates
│   │   ├── base.html                 # Base layout
│   │   ├── index.html                # Dashboard
│   │   ├── runs.html                 # Run history table
│   │   ├── run_detail.html           # Single run details
│   │   ├── compare.html              # Side-by-side comparison
│   │   └── task_detail.html          # Task performance history
│   └── static/                       # CSS/JS assets
│       ├── css/
│       │   └── style.css
│       └── js/
│           └── app.js
├── run_local_eval.sh                 # Optional: Convenience wrapper
└── .gitignore                        # Add eval_tracking/*.db
```

## Component Details

### 1. `config.py` - Configuration Constants

```python
# Server configuration
TRAINING_SERVER = "35.202.149.44"
VLLM_SERVER = "34.45.239.100"
SSH_KEY = "~/.ssh/gcp/ngcp_root_key"
SSH_USER = "root"

# Paths
TRAINING_HYDRA_DIR = "/root/hydra"
TRAINING_EVALS_DIR = "/root/hydra/evals"
LOCAL_RESULTS_DIR = "/home/bron/projects/atropos/eval_tracking/results"
DB_PATH = "/home/bron/projects/atropos/eval_tracking/hydra_evals.db"

# Polling configuration
POLL_INTERVAL = 10  # seconds
MAX_WAIT_TIME = 3600  # 1 hour timeout
```

### 2. `db_manager.py` - Database Operations

**Key Functions:**
- `init_db()` - Create schema
- `insert_run(run_data)` - Insert evaluation run
- `insert_samples(run_id, samples)` - Insert per-task results
- `get_all_runs()` - List all runs
- `get_run_by_id(run_id)` - Get single run details
- `get_samples_by_run(run_id)` - Get task results for run
- `compare_runs(run_id_1, run_id_2)` - Side-by-side comparison
- `get_task_history(task_id)` - Historical performance of one task

### 3. `utils.py` - SSH/SCP Utilities

**Key Functions:**
- `ssh_exec(host, command)` - Execute remote command, return stdout
- `scp_pull(host, remote_path, local_path)` - Copy files from remote
- `wait_for_file(host, filepath, timeout)` - Poll until file exists
- `get_eval_status(host, log_file)` - Check if eval completed

### 4. `local_eval.py` - Main Orchestrator

**Workflow:**
1. Parse arguments (mode, max_token_length)
2. SSH to vLLM server → `./run_vllm.sh {mode}`
3. Wait for vLLM to be ready
4. SSH to training server → `./run_evals.sh {mode} {max_token_length}`
5. Capture RUN_ID from output
6. Poll for completion (check for metrics.json)
7. SCP pull results directory to local
8. Parse JSON files
9. Insert into database
10. Print summary

**Command Line:**
```bash
python eval_tracking/local_eval.py --mode base --max-token-length 4096
python eval_tracking/local_eval.py --mode trained --max-token-length 4096
```

**Output:**
```
[1/5] Switching vLLM to base model on 34.45.239.100...
✓ vLLM ready on port 9004

[2/5] Starting evaluation on training server...
✓ Eval started with run_id: base_20260129_143022

[3/5] Waiting for completion...
  Polling... 60s elapsed
  Polling... 120s elapsed
  ...
✓ Evaluation completed (total time: 847s)

[4/5] Pulling results from training server...
✓ Downloaded metrics.json, samples.jsonl (34KB)

[5/5] Ingesting into database...
✓ Inserted run: base_20260129_143022
✓ Inserted 11 task samples

═══════════════════════════════════════════════════
Summary: base_20260129_143022
Pass Rate: 7/11 (63.6%)
Total Time: 14m 7s
View details: http://localhost:5000/run/base_20260129_143022
═══════════════════════════════════════════════════
```

### 5. `ingest_results.py` - Standalone Ingestion

For manually run evals, pull and ingest after the fact:

```bash
# Pull results from training server and ingest
python eval_tracking/ingest_results.py --remote-dir evals/base_20260128_120000

# Or ingest from already-pulled local directory
python eval_tracking/ingest_results.py --local-dir eval_tracking/results/base_20260128_120000
```

### 6. `eval_ui.py` - Flask Application

**Routes:**

- `GET /` - Dashboard (recent runs, aggregate stats)
- `GET /runs` - Run history table (sortable, filterable)
- `GET /run/<run_id>` - Single run details (pass/fail breakdown)
- `GET /compare?run1=X&run2=Y` - Side-by-side comparison
- `GET /task/<task_id>` - Historical performance of one task
- `GET /api/runs` - JSON list of all runs
- `GET /api/run/<run_id>` - JSON details of one run

**Templates:**

**`base.html`** - Bootstrap layout with nav
**`index.html`** - Cards showing:
  - Total runs
  - Latest run stats
  - Average pass rate trend (Chart.js)
  - Recent runs table (last 10)

**`runs.html`** - Sortable table:
  - Run ID | Mode | Pass Rate | Total Time | Timestamp | Actions

**`run_detail.html`** - Single run view:
  - Metadata table
  - Task results table (task_id, passed, failure_reason)
  - Pass/fail pie chart

**`compare.html`** - Two-column layout:
  - Left: Run 1 metrics and task results
  - Right: Run 2 metrics and task results
  - Highlight differences (tasks that changed from fail→pass or pass→fail)

**`task_detail.html`** - Historical view:
  - Line chart of task pass rate over time
  - Table of all runs for this task

**Styling:**
- Bootstrap 5 for responsive layout
- Chart.js for visualizations
- Custom CSS for pass/fail badges

## Implementation Steps

### Phase 1: Database & Ingestion (Day 1)

1. Create `eval_tracking/` directory structure
2. Implement `config.py` with all constants
3. Implement `db_manager.py`:
   - Schema creation
   - CRUD functions
   - Test with dummy data
4. Implement `ingest_results.py`:
   - JSON parsing
   - Validation
   - Database insertion
5. Test ingestion with existing results from training server

**Verification:**
```bash
python eval_tracking/db_manager.py --init
python eval_tracking/ingest_results.py --remote-dir evals/trained_v2
sqlite3 eval_tracking/hydra_evals.db "SELECT * FROM eval_runs;"
```

### Phase 2: SSH Orchestration (Day 2)

1. Implement `utils.py`:
   - SSH execution wrapper
   - SCP pull wrapper
   - Polling functions
2. Implement `local_eval.py`:
   - Argument parsing
   - vLLM switching via SSH
   - Eval execution via SSH
   - Polling for completion
   - Results pulling
   - Database ingestion
3. Test end-to-end flow

**Verification:**
```bash
python eval_tracking/local_eval.py --mode base --max-token-length 3072
# Wait for completion, verify database updated
```

### Phase 3: Flask UI (Day 3)

1. Implement `eval_ui.py`:
   - Flask app setup
   - All routes
   - JSON API endpoints
2. Create templates:
   - `base.html` with Bootstrap
   - `index.html` dashboard
   - `runs.html` table
   - `run_detail.html`
   - `compare.html`
   - `task_detail.html`
3. Add CSS styling and Chart.js

**Verification:**
```bash
python eval_tracking/eval_ui.py
# Open http://localhost:5000, test all pages
```

### Phase 4: Polish & Documentation (Day 4)

1. Error handling (SSH failures, timeouts, missing files)
2. Logging (use Python logging module)
3. Create `requirements.txt`
4. Create `run_local_eval.sh` wrapper script
5. Update `.gitignore`
6. Documentation in README

**Verification:**
- Test timeout scenarios
- Test SSH failure
- Test missing files
- Run full eval cycle
- Test all UI features

## Critical Files to Modify/Create

### New Files (Priority Order)

1. **`eval_tracking/db_manager.py`** - Core database operations
2. **`eval_tracking/local_eval.py`** - Main orchestrator
3. **`eval_tracking/utils.py`** - SSH/SCP utilities
4. **`eval_tracking/eval_ui.py`** - Flask app
5. **`eval_tracking/config.py`** - Configuration
6. **`eval_tracking/templates/base.html`** - Base template
7. **`eval_tracking/requirements.txt`** - Dependencies

### Existing Files to Update

1. **`.gitignore`** - Add `eval_tracking/*.db` and `eval_tracking/results/`

## Dependencies (requirements.txt)

```
flask==3.0.0
paramiko==3.4.0
```

## Verification Steps

### 1. Database Test
```bash
python eval_tracking/db_manager.py --init
python eval_tracking/ingest_results.py --remote-dir evals/trained_v2
sqlite3 eval_tracking/hydra_evals.db "SELECT COUNT(*) FROM eval_runs;"
```

### 2. SSH Connection Test
```bash
python -c "from eval_tracking.utils import ssh_exec; print(ssh_exec('35.202.149.44', 'ls /root/hydra/evals'))"
```

### 3. Full Orchestration Test
```bash
python eval_tracking/local_eval.py --mode base --max-token-length 3072
# Should complete in ~15-20 minutes and auto-ingest
```

### 4. UI Test
```bash
python eval_tracking/eval_ui.py
# Visit http://localhost:5000 and test all pages
```

### 5. Comparison Test
```bash
# Run two evals
python eval_tracking/local_eval.py --mode base --max-token-length 4096
python eval_tracking/local_eval.py --mode trained --max-token-length 4096
# Compare in UI: http://localhost:5000/compare?run1=base_XXX&run2=trained_XXX
```

## Integration with Existing Workflow

**No changes to remote servers:**
- `run_evals.sh` stays exactly as-is
- `run_vllm.sh` stays exactly as-is
- All orchestration happens from local machine

**Backward compatibility:**
- Can still SSH manually and run evals
- Manual runs can be ingested later with `ingest_results.py`
- Database is purely additive (doesn't affect existing workflow)

**Convenience wrapper:**
```bash
#!/usr/bin/env bash
# run_local_eval.sh
python eval_tracking/local_eval.py "$@"
```

## Future Enhancements (Out of Scope)

- Email notifications on completion
- Slack integration for results
- Automatic baseline comparisons (alert if pass rate drops)
- Export to CSV/PDF
- Multi-user authentication
- Real-time log streaming in UI
- Task metadata auto-extraction from task.json files
