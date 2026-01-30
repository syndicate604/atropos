#!/usr/bin/env python3
"""
Harness Canary Test - Validate test infrastructure with known-good patch.

This script runs a known-good patch (sqli-001/patches/known-good.diff) through
the harness to verify the test infrastructure works correctly.

If this fails, the problem is with the harness/tests/scanner, not the model.
"""

import sys
from pathlib import Path

# Add project to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "environments" / "hydra"))

from harness.runner import HarnessRunner, TaskResult


def test_known_good_patch():
    """Test that a known-good patch passes the harness."""

    print("="*60)
    print("HARNESS CANARY TEST")
    print("="*60)
    print()

    # Initialize harness
    print("[1/4] Initializing harness...")
    harness = HarnessRunner(
        tasks_dir=project_root / "environments" / "hydra" / "tasks"
    )
    print(f"✓ Harness initialized")
    print()

    # Load known-good patch
    task_id = "sqli-001"
    known_good_patch = project_root / "environments" / "hydra" / "tasks" / task_id / "patches" / "known-good.diff"

    print(f"[2/4] Loading known-good patch for {task_id}...")
    if not known_good_patch.exists():
        print(f"✗ ERROR: Known-good patch not found at {known_good_patch}")
        return False

    patch_content = known_good_patch.read_text()
    print(f"✓ Loaded patch ({len(patch_content)} bytes)")
    print()
    print("Patch preview:")
    print("-" * 60)
    for line in patch_content.split('\n')[:10]:
        print(f"  {line}")
    print("-" * 60)
    print()

    # Run through harness
    print(f"[3/4] Running patch through harness...")
    print(f"  Task: {task_id}")
    print(f"  Patch: {known_good_patch.name}")
    print()

    result: TaskResult = harness.run_task(
        task_id=task_id,
        patch_file=known_good_patch
    )

    # Report results
    print("[4/4] Results:")
    print("-" * 60)
    print(f"  Passed: {result.passed}")
    print(f"  Failure Reason: {result.failure_reason or 'N/A'}")
    print(f"  Patch Error: {result.patch_error or 'N/A'}")
    print(f"  Exploit Original: {'✓ Succeeded' if result.exploit_original_succeeded else '✗ Failed'}")
    print(f"  Exploit Patched: {'✗ Failed (good!)' if not result.exploit_patched_succeeded else '✓ Succeeded (bad!)'}")
    print(f"  Tests: {'✓ Passed' if result.tests_passed else '✗ Failed'}")
    print(f"  Scanner: {'✓ Clean' if result.scanner_clean else '✗ Findings'}")
    print("-" * 60)
    print()

    # Final verdict
    print("="*60)
    if result.passed:
        print("✅ CANARY PASSED - Harness is working correctly!")
        print("="*60)
        print()
        print("The test infrastructure is functioning properly.")
        print("Model failures are likely due to incorrect patches, not harness bugs.")
        return True
    else:
        print("❌ CANARY FAILED - Harness has issues!")
        print("="*60)
        print()
        print("⚠️  A known-good patch failed the harness.")
        print("This indicates a problem with the test infrastructure, not the model.")
        print()
        print("Possible issues:")
        print("  - Exploit script not working")
        print("  - Regression tests failing incorrectly")
        print("  - Security scanner misconfigured")
        print("  - Workspace setup broken")
        print()
        print(f"Failure reason: {result.failure_reason}")
        if result.patch_error:
            print(f"Patch error: {result.patch_error}")
        return False


if __name__ == "__main__":
    success = test_known_good_patch()
    sys.exit(0 if success else 1)
