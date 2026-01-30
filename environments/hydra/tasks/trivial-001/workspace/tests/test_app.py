#!/usr/bin/env python3
"""Trivial test - just check module imports."""
import sys
sys.path.insert(0, '/workspace')

from app import check_password

def test_function_exists():
    """Test that check_password function exists."""
    assert callable(check_password)
