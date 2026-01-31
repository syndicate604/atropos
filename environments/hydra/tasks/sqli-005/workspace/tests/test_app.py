#!/usr/bin/env python3
"""
Regression tests for sqli-005 - SQL injection in DELETE statement.
"""
import pytest
from app import app, init_db, get_db


@pytest.fixture
def client():
    """Create test client with initialized database."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_logout_valid_token(client):
    """Test logout with valid token."""
    response = client.post('/logout', json={'token': 'abc123'})
    assert response.status_code == 200
    data = response.json
    assert data["status"] == "logged out"


def test_logout_invalid_token(client):
    """Test logout with non-existent token."""
    response = client.post('/logout', json={'token': 'nonexistent'})
    assert response.status_code == 200
    data = response.json
    assert data["status"] == "logged out"


def test_logout_empty_token(client):
    """Test logout with empty token."""
    response = client.post('/logout', json={'token': ''})
    assert response.status_code == 200


def test_logout_no_crash_on_sql_chars(client):
    """Test that SQL special characters don't crash the server."""
    response = client.post('/logout', json={'token': "' OR '1'='1"})
    # Must not crash (500 error)
    assert response.status_code != 500, "Server crashed on SQL injection attempt"
    assert response.status_code == 200
