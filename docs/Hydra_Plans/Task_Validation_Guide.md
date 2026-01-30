# Task Validation & Test Infrastructure Guide

**Purpose:** How to create, validate, and fix security benchmark tasks for the Hydra training pipeline.

**Status:** 4 of 12 tasks validated as of 2026-01-30

---

## Task Acceptance Checklist (Quick Reference)

Before adding a task to the training set, run:

```bash
# SOURCE OF TRUTH: Full harness validation
cd /root/hydra && ./test_single_task.sh <task-id>
# Expected: ✅ PASSED
```

**That's it.** The harness runs exploit in a containerized environment that matches training/eval.

**Optional debug-only checks** (can disagree with harness):
```bash
# 1. Patch applies cleanly
cd workspace && patch --dry-run -p1 < ../patches/known-good.diff

# 2. Exploit on vulnerable (exit 0) - LOCAL ONLY, may differ from harness
python3 exploit/exploit.py

# 3. Exploit on patched (exit 1) - LOCAL ONLY, may differ from harness
cd workspace && patch -p1 < ../patches/known-good.diff
cd .. && python3 exploit/exploit.py

# 4. Tests pass - LOCAL ONLY, may differ from harness
cd workspace && pytest tests/
```

**Copy/Paste Drift Prevention:**
- Exploit only polls endpoints that exist in `workspace/app.py`
- Tests only call endpoints that exist in `workspace/app.py`
- Patch only targets functions that exist in `workspace/app.py`
- Run: `grep "@app.route" workspace/app.py` and verify all components match

**Known-Good Hygiene:**
- ≤5 lines changed (ideally 1-3)
- No `# FIXED:` comments
- No API contract changes

---

## Table of Contents
1. [Current Status](#current-status)
2. [What Makes a Good Task](#what-makes-a-good-task)
   - Task Structure
   - Task Metadata Schema (task.json)
   - Critical Requirements
   - Endpoint Polling Rule
   - Known-Good Patch Hygiene
   - Negative Controls
   - Difficulty Guidelines
3. [How to Validate a Task](#how-to-validate-a-task)
   - Harness Canary vs Task Validity
4. [Task Acceptance Criteria (CI-Style)](#task-acceptance-criteria-ci-style)
5. [Copy/Paste Drift Checklist](#copypaste-drift-checklist)
6. [Common Task Issues](#common-task-issues)
7. [How to Fix Broken Tasks](#how-to-fix-broken-tasks)
8. [Task-by-Task Status](#task-by-task-status)

---

## Current Status

### ✅ Validated Tasks (4/12)

| Task ID | Vulnerability | Status | Notes |
|---------|--------------|--------|-------|
| sqli-001 | SQL Injection (LIKE) | ✅ PASSED | Clean task, good reference |
| sqli-002 | SQL Injection (WHERE id) | ✅ PASSED | Fixed: exploit, tests, patch all aligned |
| xss-001 | Reflected XSS | ✅ PASSED | Fixed: added tests, corrected imports |
| trivial-001 | Hardcoded password | ✅ PASSED | Canary task for smoke testing |

### ❌ Broken Tasks (8/12)

| Task ID | Issue | Priority |
|---------|-------|----------|
| sqli-005 | No tests, exploit doesn't work | Medium |
| cmd-001 | No known-good patch | High |
| idor-001 | No known-good patch | High |
| path-001 | No known-good patch | High |
| sqli-003 | No known-good patch | Medium |
| sqli-004 | No known-good patch | Medium |
| sqli-006 | No known-good patch | Medium |
| xss-002 | No known-good patch | High |

---

## What Makes a Good Task

### 1. Complete Task Structure

```
tasks/<task-id>/
├── workspace/              # Vulnerable code
│   ├── app.py             # Main application file
│   └── tests/             # Regression tests (REQUIRED)
│       └── test_app.py    # Test file
├── exploit/               # Exploit to verify vulnerability
│   └── exploit.py         # Must succeed on vulnerable, fail on fixed
├── patches/               # Reference patches
│   └── known-good.diff    # Correct fix (REQUIRED for validation)
│   └── known-bad.diff     # (Optional) Patch that doesn't fix vulnerability
│   └── breaks-tests.diff  # (Optional) Fix that breaks regression tests
└── task.json             # Task metadata (see schema below)
```

### 1.1. Task Metadata Schema (task.json)

**Actual schema used in tasks (e.g., sqli-001/task.json):**

```json
{
  "id": "sqli-001",
  "version": 1,
  "category": "sql_injection",
  "cwe": "CWE-89",
  "metadata": {
    "language": "python",
    "framework": "flask",
    "difficulty": "easy",
    "description": "String concatenation in SQL query"
  },
  "files": {
    "vulnerable": "workspace/app.py",
    "exploit": "exploit/exploit.py",
    "tests": "workspace/tests/"
  },
  "patches": {
    "known-good": "Correct parameterized query fix",
    "known-bad": "Strip/length limit but still vulnerable to injection",
    "breaks-tests": "Uses parameterized query but changes return format"
  }
}
```

**Field explanations:**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `id` | string | ✅ | Unique task identifier (e.g., "sqli-001") |
| `version` | integer | ✅ | Schema version (currently 1) |
| `category` | string | ✅ | Vulnerability type: "sql_injection", "xss", "command_injection", etc. |
| `cwe` | string | ✅ | CWE identifier (e.g., "CWE-89") |
| `metadata.language` | string | ✅ | Programming language (e.g., "python") |
| `metadata.framework` | string | ✅ | Framework (e.g., "flask", "django") |
| `metadata.difficulty` | string | ✅ | "easy", "medium", or "hard" |
| `metadata.description` | string | ✅ | Brief description of vulnerability |
| `files.vulnerable` | string | ✅ | Path to main vulnerable file (e.g., "workspace/app.py") |
| `files.exploit` | string | ✅ | Path to exploit script (e.g., "exploit/exploit.py") |
| `files.tests` | string | ✅ | Path to test **directory** (e.g., "workspace/tests/") |
| `patches.known-good` | string | Optional | **Description** of correct fix (not file path) |
| `patches.known-bad` | string | Optional | **Description** of ineffective patch |
| `patches.breaks-tests` | string | Optional | **Description** of fix that breaks tests |

**Important notes:**
- `files.tests` points to a **directory** (`workspace/tests/`), not a single file
- `patches.*` fields contain **descriptions** of patches, not file paths
  - Actual patch files are at `patches/known-good.diff`, etc.
  - The task.json descriptions help humans understand what each patch does
- `metadata.language` and `metadata.framework` are nested under `metadata` object (not top-level)

**Why this matters:**
- Prevents incomplete tasks from being added
- Makes it easy to filter tasks by category, difficulty, CWE
- Enables automated validation of task structure
- Ensures tasks load correctly in the harness

### 2. Critical Requirements

**A task is ONLY valid if:**

✅ **Known-good patch exists** - Reference solution that proves task is solvable
✅ **Exploit works correctly:**
  - Exit 0 (success) on vulnerable code
  - Exit 1 (failure) on patched code
  - Polls an endpoint that **actually exists** in workspace (see Endpoint Polling Rule below)
✅ **Tests exist and pass:**
  - Located in `workspace/tests/`
  - Test normal functionality (not the vulnerability)
  - Pass after applying known-good patch
✅ **Components are aligned:**
  - Exploit tests the actual vulnerability in workspace
  - Tests match the actual endpoints/functions in workspace
  - Patch fixes what the exploit tests

### 2.1. Endpoint Polling Rule (Prevents Drift) ⚠️ CRITICAL

**Problem:** sqli-002 and other tasks had exploits that polled `/health`, but workspaces didn't implement it → exploit failed even though vulnerability existed.

**EXPLICIT RULE:**
> **Exploits must ONLY poll endpoints that exist in `workspace/app.py`.**
>
> Before using an endpoint in exploit, run:
> ```bash
> grep "@app.route" workspace/app.py
> ```
> If the endpoint doesn't appear, **don't use it in exploit.**

**Two approved approaches:**

**Option A (recommended):** Poll the vulnerable endpoint itself
```python
# If task tests /user?id=, poll that same endpoint
def wait_for_server():
    try:
        requests.get("http://127.0.0.1:5000/user?id=1", timeout=1)
        return True
    except:
        return False
```

**Option B (standardize):** Require ALL workspaces to implement `/health`
```python
# Add to every workspace/app.py:
@app.route('/health')
def health():
    return {"status": "ok"}
```

**Enforcement:**
- Run Copy/Paste Drift Checklist (Section below) before validation
- If exploit uses an endpoint, it must exist in `workspace/app.py`
- No exceptions

**Why this matters:** Prevents false negatives where exploit fails to connect, not because vulnerability doesn't exist, but because health check endpoint is missing.

**Example (good):**
```python
# Poll the actual vulnerable endpoint
def wait_for_server():
    try:
        requests.get("http://127.0.0.1:5000/user?id=1", timeout=1)
        return True
    except:
        return False
```

**Example (bad):**
```python
# Poll /health that may not exist
def wait_for_server():
    try:
        requests.get("http://127.0.0.1:5000/health", timeout=1)
        return True
    except:
        return False
```

### 2.2. Known-Good Patch Hygiene

**A known-good patch must meet these standards:**

✅ **Applies cleanly:**
```bash
cd workspace && patch --dry-run -p1 < ../patches/known-good.diff
# Must exit 0 with no errors
```

✅ **Minimal diff:** Change 1-5 lines ideally, maximum 10 lines
  - Only the security fix
  - No refactoring
  - No formatting changes
  - No new dependencies unless required for fix

✅ **No extra files:** Should only modify existing workspace files

✅ **No API contract changes:** Unless task explicitly tests API versioning
  - Don't add new endpoints
  - Don't change request/response formats
  - Don't rename functions

✅ **No training signal leaks:** ⚠️ CRITICAL - Don't include comments like "# FIXED:"

**BAD (leaks training signal):**
```python
-    sql = f"SELECT * FROM users WHERE id = {user_id}"
+    sql = "SELECT * FROM users WHERE id = ?"  # FIXED: Use parameterized queries
+    cursor = conn.execute(sql, (user_id,))
```

**GOOD (minimal, no hints):**
```python
-    sql = f"SELECT * FROM users WHERE id = {user_id}"
-    cursor = conn.execute(sql)
+    sql = "SELECT * FROM users WHERE id = ?"
+    cursor = conn.execute(sql, (user_id,))
```

**Why NO "# FIXED:" comments:**
- Model learns to add comments, not understand the fix
- Teaches surface patterns, not security concepts
- Makes evaluation meaningless (model just adds "# FIXED:" to pass)
- Real security fixes don't include self-congratulatory comments

**Rule:** If your patch includes the word "FIXED" or "TODO" or "VULNERABLE", remove it.

**Why this matters:**
- Keeps task focused on security fix, not code style
- Prevents model from learning "just add # FIXED comments"
- Makes the fix learnable (clear cause-and-effect)

### 2.3. Negative Controls (Optional but Valuable)

**Purpose:** Validate that harness can distinguish failure modes.

**For each task, optionally create:**

**`patches/known-bad.diff`** - A patch that applies but doesn't fix the vulnerability
```diff
# Example: Input validation but still concatenates
-    sql = f"SELECT * FROM users WHERE id = {user_id}"
+    if user_id.isdigit():
+        sql = f"SELECT * FROM users WHERE id = {user_id}"
```
**Expected:** `patch_ineffective` (exploit still succeeds)

**`patches/breaks-tests.diff`** - A fix that works but breaks functionality
```diff
# Example: Prevents injection but changes API contract
-    @app.route('/user')
-    def get_user():
-        user_id = request.args.get('id')
+    @app.route('/user/<int:user_id>')
+    def get_user(user_id):
```
**Expected:** `regression_test_failure` (tests fail due to API change)

**Benefits:**
- Proves harness correctly detects different failure types
- Provides training reward variance (not just 0/1)
- Helps debug harness issues vs task issues

**Not required for initial validation, but useful for robustness.**

### 3. Task Difficulty Guidelines

**For a 7B model to learn these tasks, use mechanical criteria:**

✅ **Human-solvable in <5 minutes:**
  - A security engineer should understand the vulnerability immediately
  - The fix should be obvious once the vulnerability is identified

✅ **Single-file fix:**
  - Change ≤5 lines in a single file
  - No multi-file refactors
  - No architectural changes

✅ **Obvious vulnerability:**
  - Well-commented in code (e.g., "# VULNERABLE: string concatenation")
  - Common patterns (SQL injection, XSS, hardcoded secrets)
  - No edge cases or trick questions

✅ **Minimal, focused fix:**
  - One security concept per task (parameterized queries OR input validation, not both)
  - No incidental complexity
  - No framework-specific edge cases

**Rule of thumb:** If Claude Sonnet 4.5 can't fix it in one shot, it's too hard for a 7B model to learn.

**Examples:**
- ✅ **Good:** Hardcoded password → use environment variable (trivial-001)
- ✅ **Good:** String concatenation in SQL → parameterized query (sqli-001)
- ❌ **Too hard:** SQL injection + missing auth + timing attack (multiple concepts)
- ❌ **Too hard:** Requires understanding ORM internals or framework magic

---

## How to Validate a Task

### Step 1: Test with Known-Good Patch

Run the validation script:

```bash
cd /root/hydra
./test_single_task.sh <task-id>
```

**Expected output for valid task:**
```
✅ PASSED
Exploit Original: True   (vulnerability is exploitable)
Exploit Patched: False   (fix stops the exploit)
Tests Passed: True       (no regressions)
Scanner Clean: True      (no remaining issues)
```

### Step 2: Full Validation Suite

Test all tasks with known-good patches:

```bash
cd /root/hydra
./test_all_known_good.sh
```

**Success criteria:** All tasks with known-good patches pass.

### Step 3: Distinguish Harness Canary vs Task Validity

**Two types of validation:**

**Harness Canary (Infrastructure Test):**
- **Purpose:** Proves the test harness itself works
- **Script:** `./test_harness_canary.py`
- **What it does:** Runs sqli-001's known-good patch (a task known to be correct)
- **If this fails:** The **harness is broken**, not the tasks
- **Run when:** After harness code changes, before blaming tasks

**Task Validity (Per-Task Test):**
- **Purpose:** Proves each individual task is correctly configured
- **Script:** `./test_single_task.sh <task-id>`
- **What it does:** Runs the task's own known-good patch
- **If this fails:** The **task is broken** (misaligned components, wrong patch, etc.)
- **Run when:** After creating/fixing a task, before adding to training set

**Why distinguish these?**
- "2 passed / 1 failed / 9 no patch" ≠ "infra broken"
- It means: 2 tasks are valid, 1 task is broken, 9 tasks are incomplete
- Only if harness canary fails is the infrastructure itself broken

---

## Task Acceptance Criteria (CI-Style)

Use this command sequence to validate a task is ready for training:

### 1. Check Structure
```bash
TASK_ID="sqli-001"
[ -d "environments/hydra/tasks/$TASK_ID/workspace/tests" ] || echo "❌ Missing tests/"
[ -f "environments/hydra/tasks/$TASK_ID/exploit/exploit.py" ] || echo "❌ Missing exploit"
[ -f "environments/hydra/tasks/$TASK_ID/patches/known-good.diff" ] || echo "❌ Missing known-good patch"
```

### 2. Verify Patch Applies Cleanly
```bash
cd environments/hydra/tasks/$TASK_ID/workspace
patch --dry-run -p1 < ../patches/known-good.diff
# Expected: exit 0, no "FAILED" messages
cd -
```

### 3. Run Exploit on Vulnerable Code (Optional - for debugging)
```bash
cd environments/hydra/tasks/$TASK_ID
python3 exploit/exploit.py
# Expected: exit 0 (vulnerability is exploitable)
cd -
```

**⚠️ Note:** Direct exploit runs are for debugging only. The harness runs exploit in a controlled containerized environment with `/workspace` mounts. Local runs can give false confidence if your environment differs from the harness.

### 4. Apply Patch (Optional - for debugging)
```bash
cd environments/hydra/tasks/$TASK_ID/workspace
patch -p1 < ../patches/known-good.diff
```

### 5. Run Exploit on Patched Code (Optional - for debugging)
```bash
cd environments/hydra/tasks/$TASK_ID
python3 exploit/exploit.py
# Expected: exit 1 (fix prevents exploitation)
cd -
```

### 6. Run Regression Tests (Optional - for debugging)
```bash
cd environments/hydra/tasks/$TASK_ID/workspace
pytest tests/ -v
# Expected: all tests pass
cd -
```

### 7. Full Harness Test ⚠️ SOURCE OF TRUTH
```bash
cd /root/hydra
./test_single_task.sh $TASK_ID
# Expected: ✅ PASSED
```

**This is the authoritative validation.** Steps 3-6 are useful for debugging, but only Step 7 (full harness) matches the actual training/eval environment.

**Exit codes:**
- All commands succeed → Task is valid
- Any command fails → Task is not ready

**Automate this:**
```bash
# Future: Add to CI/CD
./validate_task.sh <task-id>
# Runs all 7 steps, exits 0 if all pass, 1 if any fail
```

---

## Copy/Paste Drift Checklist

**Problem:** Tasks are often created by copying an existing task, which causes components to reference endpoints/functions that don't exist in the new workspace.

**Example:** sqli-002 was copy-pasted from sqli-001, so exploit attacked `/search` and tests tested `search_users()`, but workspace had `/user` and `get_user()`.

**Use this checklist BEFORE validating any task:**

### 1. Verify Endpoints Match
```bash
# List all endpoints in workspace
grep -n "@app.route" environments/hydra/tasks/TASK/workspace/app.py

# Check exploit uses only those endpoints
grep "requests\.(get|post)" environments/hydra/tasks/TASK/exploit/exploit.py

# ✅ All exploit URLs must match workspace routes
# ❌ If exploit attacks /search but workspace has /user → drift detected
```

### 2. Verify Functions Match
```bash
# List all function definitions in workspace
grep -n "^def " environments/hydra/tasks/TASK/workspace/app.py

# Check patch targets only those functions
grep "^@@.*def " environments/hydra/tasks/TASK/patches/known-good.diff

# ✅ All patch hunks must target actual functions
# ❌ If patch modifies search_users() but workspace has get_user() → drift detected
```

### 3. Verify Tests Match
```bash
# Check what endpoints tests call
grep "client\.(get|post)" environments/hydra/tasks/TASK/workspace/tests/test_app.py

# ✅ All test URLs must match workspace routes
# ❌ If tests call /search but workspace has /user → drift detected
```

### 4. Verify Database Schema Match (SQL tasks)
```bash
# Check what tables exist in init_db()
grep "CREATE TABLE" environments/hydra/tasks/TASK/workspace/app.py

# Check what tables exploit/tests/patch reference
grep -i "FROM \|INTO \|UPDATE " environments/hydra/tasks/TASK/exploit/exploit.py
grep -i "FROM \|INTO \|UPDATE " environments/hydra/tasks/TASK/workspace/tests/test_app.py

# ✅ All table references must match actual schema
# ❌ If code uses 'users' but exploit queries 'accounts' → drift detected
```

### 5. Verify Patch Context Matches
```bash
# Test that patch applies cleanly (context lines must match)
cd environments/hydra/tasks/TASK/workspace
patch --dry-run -p1 < ../patches/known-good.diff

# ✅ Patch hunk context must match workspace; line numbers can drift but hunks must apply cleanly
# ❌ If patch fails with "Hunk #1 FAILED" → context mismatch (copy-pasted from wrong task)
```

**Why context, not line numbers:**
- Patches work by matching surrounding context lines, not exact line numbers
- If code structure matches, patches apply even if line numbers differ
- "Hunk FAILED" means context doesn't match → copied from different workspace

**Common drift patterns:**

| Component | Looks For | Must Match |
|-----------|-----------|------------|
| exploit/exploit.py | `requests.get("http://.../<ENDPOINT>")` | `@app.route('/<ENDPOINT>')` in workspace/app.py |
| workspace/tests/test_app.py | `client.get('/<ENDPOINT>')` | `@app.route('/<ENDPOINT>')` in workspace/app.py |
| patches/known-good.diff | `@@ ... @@ def <FUNCTION>` | Context lines must match workspace (line numbers can drift) |

**Prevention:**
1. Never copy-paste entire task directories
2. Always read workspace/app.py FIRST before writing exploit/tests/patch
3. Use grep to verify alignment before running harness
4. Run the drift checklist above before calling a task "ready"

---

## Common Task Issues

### Issue 1: "original_not_vulnerable"

**Symptom:** Exploit fails on both vulnerable AND patched code

**Root cause:** Exploit doesn't actually test the vulnerability

**Example:** sqli-005 exploit checked for 500 errors, but the vulnerable code returns 200

**Fix:**
1. Read the vulnerable code in `workspace/app.py`
2. Understand what the vulnerability actually does
3. Rewrite exploit to detect that specific behavior
4. Test on vulnerable code first (should exit 0)

### Issue 2: "patch_ineffective"

**Symptom:** Exploit succeeds after applying known-good patch

**Root causes:**
- Patch has wrong line numbers
- Patch doesn't actually fix the vulnerability
- Exploit tests something different than what patch fixes

**Fix:**
1. Verify patch applies cleanly: `cd workspace && patch -p1 < ../patches/known-good.diff`
2. Check patched code actually has the fix
3. Run exploit manually on patched code
4. Adjust patch or exploit to align

### Issue 3: "regression_test_failure"

**Symptom:** Tests fail after applying patch

**Root causes:**
- Tests don't exist (`workspace/tests/` missing)
- Tests expect vulnerable behavior
- Tests import wrong modules
- Tests target wrong endpoints

**Fix:**
1. Check if `workspace/tests/` exists
2. If missing, create it with basic tests
3. Tests should verify **functionality**, not vulnerability
4. Run tests manually: `cd workspace && pytest tests/`

### Issue 4: "patch_apply_hunk_failed"

**Symptom:** Patch doesn't apply to workspace code

**Root cause:** Patch was copy-pasted from another task or line numbers wrong

**Example:** sqli-002's original patch targeted `search_users()` but workspace had `get_user()`

**Fix:**
1. Read actual workspace code: `cat workspace/app.py`
2. Identify the vulnerable lines
3. Rewrite patch with correct line numbers and context
4. Test patch applies: `cd workspace && patch --dry-run -p1 < ../patches/known-good.diff`

### Issue 5: No known-good patch

**Symptom:** Task has no reference solution

**Fix:** Create one from scratch or base model near-misses (see below)

---

## How to Fix Broken Tasks

### Workflow: Fix from Base Model Near-Misses

**Best candidates:** Tasks with `regression_test_failure` (closest to passing)

**Steps:**

1. **Extract base model attempt:**
```bash
cat /root/hydra/evals/base_TIMESTAMP/samples.jsonl | \
  jq 'select(.task_id == "TARGET_TASK")' | \
  jq -r '.diff_text'
```

2. **Identify what's wrong:**
- Is the fix conceptually correct?
- Did it make unnecessary changes?
- Are the line numbers right?

3. **Create minimal fix:**
- Keep ONLY the security fix
- Remove cosmetic changes
- Verify line numbers match workspace

4. **Save as known-good:**
```bash
# Save the corrected patch
cat > environments/hydra/tasks/TARGET_TASK/patches/known-good.diff << 'EOF'
[your corrected patch]
EOF
```

5. **Validate:**
```bash
./test_single_task.sh TARGET_TASK
```

### Workflow: Fix Exploit/Tests Alignment

**When exploit and tests don't match workspace:**

1. **Check what endpoints exist:**
```bash
grep -n "@app.route" environments/hydra/tasks/TASK/workspace/app.py
```

2. **Update exploit to match:**
- Change endpoint URLs
- Change expected response format
- Update success/failure detection logic

3. **Update tests to match:**
- Test the actual endpoints that exist
- Check for actual response structure
- Don't test for vulnerability, test for functionality

4. **Example fix:** See sqli-002 in git history
   - Changed exploit from `/search` to `/user`
   - Changed tests from `search_users()` to `get_user()`
   - Updated known-good patch to match actual code

### Workflow: Create Tests from Scratch

**For tasks with no tests:**

1. **Create tests directory:**
```bash
mkdir -p environments/hydra/tasks/TASK/workspace/tests
```

2. **Create minimal test file:**
```python
#!/usr/bin/env python3
"""Regression tests for TASK."""
import pytest
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_endpoint_exists(client):
    """Test that endpoint responds."""
    response = client.get('/endpoint')
    assert response.status_code == 200

def test_endpoint_returns_expected_format(client):
    """Test response format."""
    response = client.get('/endpoint')
    data = response.json
    assert "expected_key" in data
```

3. **Test locally first:**
```bash
cd environments/hydra/tasks/TASK/workspace
pytest tests/ -v
```

4. **Deploy and validate:**
```bash
tar czf TASK-fix.tar.gz environments/hydra/tasks/TASK
scp TASK-fix.tar.gz root@training-server:/root/hydra/
ssh root@training-server "cd /root/hydra && tar xzf TASK-fix.tar.gz && ./test_single_task.sh TASK"
```

---

## Task-by-Task Status

### ✅ sqli-001: SQL Injection (LIKE query)

**Status:** Validated, working

**Vulnerability:** String concatenation in LIKE query
```python
sql = f"SELECT * FROM users WHERE username LIKE '%{query}%'"
```

**Fix:** Parameterized query
```python
sql = "SELECT * FROM users WHERE username LIKE ?"
cursor = conn.execute(sql, (f"%{query}%",))
```

**Why it works:**
- Exploit tests SQL injection with `' OR '1'='1`
- Tests verify `/search` endpoint functionality
- All components aligned

**Reference:** Use this as template for other SQL injection tasks

---

### ✅ sqli-002: SQL Injection (WHERE id)

**Status:** Fixed 2026-01-30

**What was broken:**
- Exploit attacked `/search` endpoint (doesn't exist)
- Tests tested `/search` functionality (doesn't exist)
- Patch targeted `search_users()` function (doesn't exist)
- Actual workspace has `/user` endpoint with `get_user()` function

**Fixes applied:**
1. Rewrote exploit to attack `/user?id=` with payload `0 OR 1=1`
2. Rewrote tests to test `/user` endpoint
3. Rewrote patch to target actual `get_user()` function

**Known-good patch:**
```diff
--- a/app.py
+++ b/app.py
@@ -43,8 +43,8 @@ def get_user():
     init_db(conn)

-    # VULNERABLE: String concatenation in WHERE clause
-    sql = f"SELECT * FROM users WHERE id = {user_id}"
-    cursor = conn.execute(sql)
+    # FIXED: Parameterized query
+    sql = "SELECT * FROM users WHERE id = ?"
+    cursor = conn.execute(sql, (user_id,))
```

**Lesson learned:** All task components must match actual workspace code

---

### ✅ xss-001: Reflected XSS

**Status:** Fixed 2026-01-30

**What was broken:**
- No tests directory (always failed regression_test_failure)
- Import error: `from flask import escape` doesn't work in modern Flask

**Fixes applied:**
1. Created `workspace/tests/` directory
2. Added basic regression tests for `/search` endpoint
3. Fixed import: `from markupsafe import escape`

**Known-good patch:**
```diff
--- a/app.py
+++ b/app.py
@@ -1,5 +1,6 @@
 """Vulnerable Flask app with reflected XSS."""
 from flask import Flask, request
+from markupsafe import escape

 app = Flask(__name__)

@@ -12,7 +13,7 @@ def search():
     <html>
     <head><title>Search Results</title></head>
     <body>
-        <h1>Search results for: {query}</h1>
+        <h1>Search results for: {escape(query)}</h1>
         <p>No results found.</p>
     </body>
     </html>
```

**Lesson learned:** Always create tests, even simple ones. Use correct imports for the environment.

---

### ✅ trivial-001: Hardcoded Password

**Status:** Created 2026-01-30 as canary task

**Purpose:** Smoke test that's trivially easy

**Vulnerability:** Hardcoded password in code
```python
PASSWORD = "admin123"
```

**Fix:** Remove hardcoded value
```python
PASSWORD = None  # Must be set via environment
```

**Why it exists:** If this fails, something is fundamentally broken with the pipeline

---

### ❌ sqli-005: SQL Injection (DELETE)

**Status:** Broken - no tests, exploit doesn't work

**Issues:**
1. No tests directory
2. Exploit checks for 500 errors, but vulnerable code returns 200
3. Difficult to test DELETE without database inspection

**To fix:**
1. Create tests in `workspace/tests/`
2. Rewrite exploit to test actual SQL injection behavior
3. Consider simplifying or replacing this task

**Priority:** Medium (DELETE SQL injection is less common)

---

### ❌ cmd-001, idor-001, path-001: Command Injection, IDOR, Path Traversal

**Status:** No known-good patches

**To fix:**
1. Review base model evaluation results for near-misses
2. Manually create correct fixes
3. Test with harness
4. Document as working examples

**Priority:** High (diverse vulnerability types needed)

---

### ❌ sqli-003, sqli-004, sqli-006: SQL Injection variants

**Status:** No known-good patches

**To fix:**
1. Check if these are duplicates of sqli-001/002
2. If duplicates, remove from task list
3. If unique, create known-good patches
4. Validate with harness

**Priority:** Medium (already have 2 SQL injection tasks)

---

### ❌ xss-002: XSS variant

**Status:** No known-good patch

**To fix:**
1. Check if different from xss-001 (stored vs reflected?)
2. Create known-good patch following xss-001 pattern
3. Ensure tests exist
4. Validate

**Priority:** High (need more than one XSS task)

---

## Validation Checklist

Use this checklist when creating or fixing a task:

### Pre-Validation (Structure)
- [ ] Task directory structure is complete
- [ ] `workspace/tests/` directory exists with test files
- [ ] `exploit/exploit.py` exists
- [ ] `patches/known-good.diff` exists
- [ ] `task.json` has required fields (id, category, language, files)

### Copy/Paste Drift Prevention
- [ ] Run endpoint verification: `grep "@app.route" workspace/app.py` vs exploit URLs
- [ ] Run function verification: `grep "^def " workspace/app.py` vs patch targets
- [ ] Run test verification: tests only call endpoints that exist
- [ ] Run patch context verification: `patch --dry-run` succeeds (context matches, not line numbers)
- [ ] (SQL tasks) Verify table names match between code/exploit/tests

### Known-Good Patch Hygiene
- [ ] Patch applies cleanly: `patch --dry-run -p1 < patches/known-good.diff`
- [ ] Minimal diff: ≤5 lines changed (ideally 1-3)
- [ ] No comments like "# FIXED:" in the patch
- [ ] No API contract changes (unless task explicitly requires it)
- [ ] No extra files created

### Endpoint Polling
- [ ] Exploit polls an endpoint that **actually exists** in workspace
- [ ] Either polls vulnerable endpoint itself OR workspace implements `/health`

### Component Alignment
- [ ] Read `workspace/app.py` to understand actual code FIRST
- [ ] Exploit tests the vulnerability in the actual code
- [ ] Tests test the actual endpoints/functions that exist
- [ ] Patch fixes the actual vulnerable lines

### Difficulty Check
- [ ] Human can solve in <5 minutes
- [ ] Fix changes ≤5 lines in a single file
- [ ] No multi-file refactors
- [ ] Vulnerability is obvious (well-commented)

### Harness Testing (CI-Style)
- [ ] Run `./test_single_task.sh <task-id>`
- [ ] Exploit succeeds on original: `Exploit Original: True`
- [ ] Exploit fails on patched: `Exploit Patched: False`
- [ ] Tests pass: `Tests Passed: True`
- [ ] Overall result: `✅ PASSED`

### Model Testing (Optional)
- [ ] Test if base model can generate similar patch
- [ ] Check if patch is learnable (minimal, obvious fix)
- [ ] Verify a human can understand the fix in <30 seconds
- [ ] (Optional) Create negative controls: known-bad.diff, breaks-tests.diff

---

## Scripts Reference

### test_single_task.sh
**Location:** `/root/hydra/test_single_task.sh`

**Usage:**
```bash
./test_single_task.sh <task-id>
```

**Purpose:** Test one task at a time with detailed output

**Output:** Shows exploit results, test output, failure reasons

---

### test_all_known_good.sh
**Location:** `/root/hydra/test_all_known_good.sh`

**Usage:**
```bash
./test_all_known_good.sh
```

**Purpose:** Validate all tasks with known-good patches

**Output:** Summary of pass/fail for all tasks

**Exit codes:**
- 0: All known-good patches pass
- 1: One or more failures (test infrastructure broken)

---

### test_harness_canary.py
**Location:** `/root/hydra/test_harness_canary.py`

**Usage:**
```bash
python3 test_harness_canary.py
```

**Purpose:** Smoke test that harness itself works

**What it does:** Runs sqli-001 known-good patch through harness

**If this fails:** The test infrastructure is broken, not the tasks

---

## Next Steps

### Immediate (Use what works)
1. ✅ Train/eval on 4 validated tasks
2. ✅ Establish baseline performance
3. ✅ Verify training pipeline works

### Short-term (Expand task set)
1. Fix xss-002 (follow xss-001 pattern)
2. Create known-good patches for cmd-001, idor-001, path-001
3. Validate 3 new tasks → 7 total

### Long-term (Complete task set)
1. Review and fix remaining SQL injection tasks
2. Add diverse vulnerability types
3. Target: 10-12 validated tasks

---

## Key Lessons Learned

### 1. "Known-good patches" are mandatory
Without reference solutions, you can't tell if:
- The task is solvable
- The test infrastructure works
- The model's output is correct

**Rule:** Don't add tasks without known-good patches.

### 2. Components must be aligned (Prevents Copy/Paste Drift)
Many tasks had exploit/tests for **different code** than what's in workspace.

**Example:** sqli-002 exploit attacked `/search`, tests tested `search_users()`, but workspace had `/user` and `get_user()`.

**Rule:** Always read workspace FIRST, then verify all components match actual endpoints/functions.

**Prevention:** Run the Copy/Paste Drift Checklist before validation.

### 3. Tests should test functionality, not vulnerability
Tests that check if vulnerability exists will fail when patched.

**Rule:** Tests verify the app still works, not that it's still broken.

### 4. Make tasks learnable with mechanical criteria
If a top model can't solve it easily, a 7B model won't learn it.

**Rule:** Tasks should teach security concepts, not be puzzles.
- Human-solvable in <5 minutes
- ≤5 lines changed in a single file
- Obvious, well-commented vulnerabilities

### 5. Known-good patches must be hygienic
Patches that include "# FIXED:" comments or cosmetic changes leak training signal.

**Rule:** Minimal diffs only (1-5 lines), no hints, no refactoring.

### 6. Endpoint polling must use actual endpoints
Exploits that poll `/health` fail when workspace doesn't implement it.

**Rule:** Poll the vulnerable endpoint itself, or standardize all workspaces to have `/health`.

### 7. Distinguish harness canary from task validity
"9 tasks with no known-good" ≠ "harness is broken"

**Rule:**
- Harness canary (`test_harness_canary.py`) proves infrastructure works
- Task validity (`test_single_task.sh`) proves each task is correct

### 8. Validate early, validate often
Don't train on broken tasks. Always validate first.

**Rule:** Run `test_all_known_good.sh` before every training run.

---

## Contact & Contribution

When adding new tasks:
1. Follow the structure above
2. Create known-good patch FIRST
3. Validate with `test_single_task.sh`
4. Document in this guide

When fixing tasks:
1. Identify root cause (see Common Issues)
2. Fix minimally
3. Validate
4. Update this guide

**This is a living document.** Update it as tasks are fixed or added.

---

**Last updated:** 2026-01-30
**Validated tasks:** 4/12 (sqli-001, sqli-002, xss-001, trivial-001)
**Status:** Training-ready with 4-task subset
