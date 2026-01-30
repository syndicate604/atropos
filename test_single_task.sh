#!/bin/bash
# Test a single task with its known-good patch

set -euo pipefail

TASK_ID="${1:-}"

if [ -z "$TASK_ID" ]; then
    echo "Usage: $0 <task-id>"
    echo "Example: $0 sqli-005"
    exit 1
fi

cd /root/hydra

python3 << PYTHON
import sys
from pathlib import Path
sys.path.insert(0, 'environments/hydra')
from harness.runner import HarnessRunner

task_id = "$TASK_ID"
tasks_dir = Path('environments/hydra/tasks')
harness = HarnessRunner(tasks_dir)

task_dir = tasks_dir / task_id
known_good = task_dir / "patches" / "known-good.diff"

print(f"Testing: {task_id}")
print("="*60)

if not known_good.exists():
    print(f"❌ No known-good patch found")
    sys.exit(1)

try:
    result = harness.run_task(task_id, patch_name='known-good')

    print(f"Passed: {result.passed}")
    print(f"Exploit Original: {result.exploit_original_succeeded}")
    print(f"Exploit Patched: {result.exploit_patched_succeeded}")
    print(f"Tests Passed: {result.tests_passed}")
    print(f"Scanner Clean: {result.scanner_clean}")

    if not result.passed:
        print()
        print(f"Failure Reason: {result.failure_reason}")

        if result.patch_error:
            print()
            print("Patch Error:")
            print(result.patch_error[:300])

        if not result.exploit_patched_succeeded:
            print()
            print("✅ Good: Exploit failed after patch (vulnerability fixed)")
        elif result.exploit_patched_succeeded and result.exploit_original_succeeded:
            print()
            print("❌ Bad: Exploit still works after patch")
            print()
            print("Exploit Output (patched):")
            print(result.exploit_patched_output[-400:])

        if not result.tests_passed:
            print()
            print("Test Output:")
            print(result.tests_output[-500:])

    print("="*60)

    if result.passed:
        print("✅ PASSED")
        sys.exit(0)
    else:
        print(f"❌ FAILED: {result.failure_reason}")
        sys.exit(1)

except Exception as e:
    print(f"❌ ERROR: {e}")
    sys.exit(1)
PYTHON
