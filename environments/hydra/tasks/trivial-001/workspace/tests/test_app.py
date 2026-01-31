#!/usr/bin/env python3
"""Trivial tests - ensure functionality and no hardcoded credential."""
import sys
sys.path.insert(0, '/workspace')

import ast
import importlib

import app

def test_function_exists():
    """Test that check_password function exists."""
    assert callable(app.check_password)


def test_check_password_uses_env(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "s3cret")
    importlib.reload(app)
    assert app.check_password("s3cret") is True
    assert app.check_password("wrong") is False


def test_no_hardcoded_password_literal():
    src = open("/workspace/app.py", "r", encoding="utf-8").read()
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PASSWORD":
                    assert not (
                        isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)
                    )
