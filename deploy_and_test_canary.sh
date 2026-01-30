#!/bin/bash
# Deploy and test trivial-001 canary task on training server

set -euo pipefail

echo "========================================="
echo "Deploying trivial-001 Canary Task"
echo "========================================="
echo

# Package trivial-001
echo "[1/3] Packaging trivial-001..."
cd /home/bron/projects/atropos
tar czf trivial-001.tar.gz environments/hydra/tasks/trivial-001
echo "✓ Package created"
echo

# Copy to server
echo "[2/3] Copying to training server..."
scp -i ~/.ssh/gcp/ngcp_root_key trivial-001.tar.gz root@35.202.149.44:/root/hydra/
echo "✓ Copied to server"
echo

# Extract and test on server
echo "[3/3] Testing on server..."
echo
ssh -i ~/.ssh/gcp/ngcp_root_key root@35.202.149.44 "
cd /root/hydra && \
tar xzf trivial-001.tar.gz && \
python3 -c \"
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
    print('Next step: Add trivial-001 to evaluation and test with base model')
    sys.exit(0)
else:
    print()
    print('❌ CANARY FAILED')
    print(f'Reason: {result.failure_reason}')
    print(f'Tests output: {result.tests_output[:200]}')
    sys.exit(1)
\"
"

echo
echo "========================================="
echo "Deployment Complete"
echo "========================================="
