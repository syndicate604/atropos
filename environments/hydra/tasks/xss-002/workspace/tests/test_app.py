#!/usr/bin/env python3
"""Regression tests for xss-002 - comment functionality."""
import pytest
from app import app, comments


@pytest.fixture
def client():
    app.config['TESTING'] = True
    # Clear comments before each test
    comments.clear()
    with app.test_client() as client:
        yield client


def test_add_comment_endpoint_exists(client):
    """Test that POST /comment endpoint responds."""
    response = client.post('/comment', json={"comment": "test"})
    assert response.status_code == 200


def test_view_comments_endpoint_exists(client):
    """Test that GET /comments endpoint responds."""
    response = client.get('/comments')
    assert response.status_code == 200


def test_add_comment_returns_json(client):
    """Test that adding comment returns JSON status."""
    response = client.post('/comment', json={"comment": "Hello"})
    assert response.status_code == 200
    data = response.json
    assert "status" in data


def test_view_comments_returns_html(client):
    """Test that comments page returns HTML."""
    response = client.get('/comments')
    assert response.status_code == 200
    assert b'<html>' in response.data
    assert b'Comments' in response.data


def test_comment_appears_in_list(client):
    """Test that added comment appears in comments page."""
    # Add a comment
    client.post('/comment', json={"comment": "Test comment"})

    # Check it appears
    response = client.get('/comments')
    assert response.status_code == 200
    # Should appear (escaped or not, it should be there)
    assert b'Test comment' in response.data or b'Test' in response.data
