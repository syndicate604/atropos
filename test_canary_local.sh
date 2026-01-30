#!/bin/bash
# Test trivial-001 canary task (run this ON the training server)

set -euo pipefail

cd /root/hydra

echo "========================================="
echo "Testing trivial-001 Canary Task"
echo "========================================="
echo

python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, 'environments/hydra')
from harness.runner import HarnessRunner

harness = HarnessRunner(Path('environments/hydra/tasks'))
result = harness.run_task('trivial-001', patch_name='known-good')

print('='*60)
print('TRIVIAL-001 CANARY TEST')
print('='*60)
print(f'Passed: {result.passed}')
print(f'Exploit Original: {result.exploit_original_succeeded}')
print(f'Exploit Patched: {result.exploit_patched_succeeded}')
print(f'Tests Passed: {result.tests_passed}')
print(f'Scanner Clean: {result.scanner_clean}')
print('='*60)
if result.passed:
    print()
    print('✅ CANARY WORKS - Ready to test with base model')
    print()
    print('Next: Run evaluation with base model on trivial-001')
    sys.exit(0)
else:
    print()
    print('❌ CANARY FAILED')
    print(f'Reason: {result.failure_reason}')
    if result.tests_output:
        print()
        print('Test output:')
        print(result.tests_output[:500])
    sys.exit(1)
"
