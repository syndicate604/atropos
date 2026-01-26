#!/bin/bash
# check_prereqs.sh
set -e

echo "Checking prerequisites..."

# Docker
if ! command -v docker &>/dev/null; then
    echo "ERROR: docker not found"
    exit 1
fi
echo "✓ docker: $(docker --version)"

# Python 3.10+
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found"
    exit 1
fi
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✓ python3: $PYTHON_VERSION"

# patch
if ! command -v patch &>/dev/null; then
    echo "ERROR: patch not found (install: apt install patch / brew install gpatch)"
    exit 1
fi
echo "✓ patch: $(patch --version | head -1)"

echo ""
echo "All prerequisites met."
