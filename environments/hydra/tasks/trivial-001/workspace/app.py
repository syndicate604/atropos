#!/usr/bin/env python3
"""
Trivial security test - hardcoded password.
This should be trivially easy for any model to fix.
"""

PASSWORD = "admin123"

def check_password(user_input):
    return user_input == PASSWORD
