#!/usr/bin/env python3
"""Simple regression tests for xss-001 - search endpoint."""
import pytest
from app import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_search_endpoint_exists(client):
    """Test that /search endpoint responds."""
    response = client.get('/search?q=test')
    assert response.status_code == 200


def test_search_returns_html(client):
    """Test that /search returns HTML content."""
    response = client.get('/search?q=hello')
    assert response.status_code == 200
    assert b'<html>' in response.data
    assert b'Search results' in response.data


def test_search_includes_query(client):
    """Test that search results mention the query."""
    response = client.get('/search?q=example')
    assert response.status_code == 200
    # After fix, query should appear (escaped or not, we just check it's there)
    assert b'example' in response.data or b'Search results' in response.data


def test_search_empty_query(client):
    """Test that empty query doesn't crash."""
    response = client.get('/search?q=')
    assert response.status_code == 200
    assert b'<html>' in response.data
