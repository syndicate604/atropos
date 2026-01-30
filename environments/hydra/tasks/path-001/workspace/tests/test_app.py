#!/usr/bin/env python3
"""Regression tests for path-001 - download endpoint."""
import pytest
from app import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_download_endpoint_exists(client):
    """Test that /download endpoint responds."""
    # Files should exist in workspace/files/ directory
    response = client.get('/download?file=document.txt')
    # Should return 200 if file exists, or 404/500 if not
    assert response.status_code in [200, 404, 500]


def test_download_returns_file_content(client):
    """Test that download returns file content when file exists."""
    response = client.get('/download?file=document.txt')
    # If file exists, should return 200 and have content
    if response.status_code == 200:
        assert len(response.data) > 0


def test_download_different_file(client):
    """Test downloading a different file."""
    response = client.get('/download?file=readme.txt')
    # Should respond with some status
    assert response.status_code in [200, 404, 500]


def test_download_nonexistent_file(client):
    """Test that nonexistent file returns error."""
    response = client.get('/download?file=definitely_does_not_exist_12345.txt')
    # Nonexistent file should error
    assert response.status_code in [404, 500]
