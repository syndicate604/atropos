#!/bin/bash
# Test ALL tasks with their known-good patches to verify test infrastructure

set -euo pipefail

cd /root/hydra

echo "========================================="
echo "Testing ALL Known-Good Patches"
echo "========================================="
echo "This verifies the test infrastructure works correctly."
echo "If any known-good patch fails, the test harness is broken."
echo
echo "Testing 12 tasks..."
echo

python3 << 'PYTHON'
import sys
from pathlib import Path
sys.path.insert(0, 'environments/hydra')
from harness.runner import HarnessRunner

tasks_dir = Path('environments/hydra/tasks')
harness = HarnessRunner(tasks_dir)

# Find all tasks
all_tasks = sorted([d.name for d in tasks_dir.iterdir() if d.is_dir()])

results = []
passed_count = 0
failed_count = 0
no_patch_count = 0

for task_id in all_tasks:
    task_dir = tasks_dir / task_id
    known_good = task_dir / "patches" / "known-good.diff"

    if not known_good.exists():
        print(f"⊘ {task_id:15} - No known-good patch")
        no_patch_count += 1
        results.append((task_id, "NO_PATCH", None))
        continue

    try:
        result = harness.run_task(task_id, patch_name='known-good')

        if result.passed:
            print(f"✅ {task_id:15} - PASSED")
            passed_count += 1
            results.append((task_id, "PASS", None))
        else:
            print(f"❌ {task_id:15} - FAILED: {result.failure_reason}")
            failed_count += 1
            results.append((task_id, "FAIL", result.failure_reason))
    except Exception as e:
        print(f"❌ {task_id:15} - ERROR: {str(e)[:50]}")
        failed_count += 1
        results.append((task_id, "ERROR", str(e)))

print()
print("="*60)
print("SUMMARY")
print("="*60)
print(f"Total Tasks: {len(all_tasks)}")
print(f"✅ Passed: {passed_count}")
print(f"❌ Failed: {failed_count}")
print(f"⊘  No Patch: {no_patch_count}")
print("="*60)

if failed_count > 0:
    print()
    print("FAILURES:")
    for task_id, status, reason in results:
        if status in ["FAIL", "ERROR"]:
            print(f"  {task_id}: {reason}")
    print()
    print("⚠️  TEST INFRASTRUCTURE HAS ISSUES")
    sys.exit(1)
elif passed_count == 0:
    print()
    print("⚠️  No tasks with known-good patches found")
    sys.exit(1)
else:
    print()
    print("✅ ALL KNOWN-GOOD PATCHES PASS")
    print("✅ TEST INFRASTRUCTURE IS WORKING CORRECTLY")
    print()
    print("Conclusion: Model failures are due to incorrect patches,")
    print("            not broken test infrastructure.")
    sys.exit(0)
PYTHON
