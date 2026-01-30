#!/usr/bin/env python3
"""Regression tests for idor-001 - profile endpoint."""
import pytest
from app import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_profile_endpoint_exists(client):
    """Test that /profile endpoint responds."""
    response = client.get('/profile?id=1')
    assert response.status_code == 200


def test_profile_returns_json(client):
    """Test that /profile returns JSON."""
    response = client.get('/profile?id=1')
    assert response.status_code == 200
    data = response.json
    assert isinstance(data, dict)


def test_profile_default_id(client):
    """Test that default id works."""
    response = client.get('/profile')
    assert response.status_code == 200
    data = response.json
    assert "username" in data or "error" in data


def test_profile_valid_user(client):
    """Test accessing user 1's profile."""
    response = client.get('/profile?id=1')
    assert response.status_code == 200
    data = response.json
    if "username" in data:
        assert data["username"] == "alice"
