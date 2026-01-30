#!/usr/bin/env python3
"""
Regression tests for sqli-002 - /user endpoint.

Tests that the app still functions correctly after the fix.
"""
import pytest

# Import works because PYTHONPATH=/workspace is set in container
from app import app, init_db, get_db


@pytest.fixture
def client():
    """Create test client with initialized database."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        with app.app_context():
            conn = get_db()
            init_db(conn)
        yield client


def test_get_user_valid_id(client):
    """Test that /user returns correct user for valid id."""
    response = client.get('/user?id=1')
    assert response.status_code == 200
    data = response.json
    assert "users" in data
    assert len(data["users"]) == 1
    assert data["users"][0]["username"] == "alice"


def test_get_user_another_valid_id(client):
    """Test that /user returns correct user for another valid id."""
    response = client.get('/user?id=2')
    assert response.status_code == 200
    data = response.json
    assert "users" in data
    assert len(data["users"]) == 1
    assert data["users"][0]["username"] == "bob"


def test_get_user_invalid_id(client):
    """Test that /user returns empty for non-existent id."""
    response = client.get('/user?id=999')
    assert response.status_code == 200
    data = response.json
    assert "users" in data
    assert len(data["users"]) == 0


def test_get_user_no_id(client):
    """Test that /user handles missing id parameter."""
    response = client.get('/user')
    assert response.status_code == 200
    data = response.json
    assert "users" in data
    # Empty id should return no users
    assert isinstance(data["users"], list)


def test_response_format(client):
    """Response has expected format."""
    response = client.get('/user?id=1')
    data = response.json
    assert "users" in data
    assert isinstance(data["users"], list)
    if len(data["users"]) > 0:
        user = data["users"][0]
        assert "id" in user
        assert "username" in user
        assert "email" in user


def test_malicious_input_no_crash(client):
    """Test that malicious input doesn't crash the server."""
    # SQL injection attempt should be rejected gracefully, not crash
    response = client.get('/user?id=0 OR 1=1')

    # Must not crash (500 error)
    assert response.status_code != 500, "Server crashed on malicious input"

    # If it returns 200, should have empty or minimal results (not all users)
    if response.status_code == 200:
        data = response.json
        assert "users" in data
        assert len(data["users"]) < 3, "SQL injection succeeded - all users returned"
