# tasks/sqli-001/workspace/tests/conftest.py
"""Pytest configuration - ensures app is importable."""
import sys
from pathlib import Path

# Add workspace to path (backup for PYTHONPATH)
workspace = Path(__file__).parent.parent
if str(workspace) not in sys.path:
    sys.path.insert(0, str(workspace))
