#!/bin/bash
# run_primary.sh - Week 1 harness entry point
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Parse arguments
TASK_ID="${1:?Usage: ./run_primary.sh <task_id> <patch_name>}"
PATCH_NAME="${2:?Usage: ./run_primary.sh <task_id> <patch_name>}"

# Check prerequisites
if ! command -v docker &>/dev/null; then
    echo "ERROR: docker not found" >&2
    exit 1
fi

if ! command -v patch &>/dev/null; then
    echo "ERROR: patch not found (install: apt install patch)" >&2
    exit 1
fi

# Build harness image if needed
if ! docker image inspect hydra-harness:latest &>/dev/null; then
    echo "Building harness image..."
    docker build -t hydra-harness:latest harness/
fi

# Ensure results directory exists
mkdir -p results

# Run the task
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_FILE="results/${TASK_ID}_${PATCH_NAME}_${TIMESTAMP}.json"

# Disable set -e for runner invocation so we can capture exit code
# and still print summary even on expected failures (Win B/C)
set +e
python3 harness/runner.py "$TASK_ID" "$PATCH_NAME" \
    --tasks-dir tasks \
    --output "$OUTPUT_FILE"
EXIT_CODE=$?
set -e

echo ""
echo "=== Summary ==="
python3 -c "
import sys, json
with open('$OUTPUT_FILE') as f:
    data = json.load(f)
print(f'Task:   {data[\"task_id\"]}')
print(f'Patch:  {data[\"patch_name\"]}')
print(f'Result: {\"PASSED\" if data[\"passed\"] else \"FAILED\"}')
if data['failure_reason']:
    print(f'Reason: {data[\"failure_reason\"]}')
"

exit $EXIT_CODE
