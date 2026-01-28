# tasks/sqli-001/workspace/tests/test_app.py
"""Regression tests for search functionality."""

import pytest

# Import works because PYTHONPATH=/workspace is set in container
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_health(client):
    """Health endpoint works."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json["status"] == "ok"


def test_search_normal(client):
    """Normal search returns results."""
    response = client.get("/search?q=alice")
    assert response.status_code == 200
    data = response.json
    assert "results" in data
    assert "count" in data
    assert data["count"] >= 0


def test_search_empty(client):
    """Empty search returns all users."""
    response = client.get("/search?q=")
    assert response.status_code == 200
    data = response.json
    assert data["count"] == 3  # alice, bob, admin


def test_search_no_match(client):
    """Non-matching search returns empty."""
    response = client.get("/search?q=nonexistent")
    assert response.status_code == 200
    assert response.json["count"] == 0


def test_search_special_chars(client):
    """Search handles special characters."""
    # This should not crash the app
    response = client.get("/search?q=O'Brien")
    assert response.status_code == 200
    assert "results" in response.json


def test_response_format(client):
    """Response has expected format."""
    response = client.get("/search?q=bob")
    data = response.json
    assert "results" in data
    assert "count" in data
    assert isinstance(data["results"], list)
    if data["count"] > 0:
        user = data["results"][0]
        assert "id" in user
        assert "username" in user
        assert "email" in user
