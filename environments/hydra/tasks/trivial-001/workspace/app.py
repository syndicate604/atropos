#!/usr/bin/env python3
"""
Trivial security test - hardcoded password.
This should be trivially easy for any model to fix.
"""

import os

# Security requirement: do not hardcode credentials in source.
# Read from environment at runtime instead.
PASSWORD = os.environ.get("APP_PASSWORD")

def check_password(user_input):
    if PASSWORD is None:
        return False
    return user_input == PASSWORD
